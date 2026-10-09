"""Recorded customer drawing confirmations for staged cabinet orders.

Uploads arrive over time. A confirmation pins one current source file, and a
later replacement makes that confirmation stale instead of approving new bytes.
The record is an operator's account of a customer decision, not an e-signature.
"""
from __future__ import annotations

from pathlib import Path
import hashlib

from kanpace.core.errors import APIError
from kanpace.core.validation import now, short_text
import access_control
import engineering_readiness


STAGES = ('render', 'construction', 'engineering')
EXTENSIONS = {
    'construction': {'.dwg', '.dxf', '.pdf', '.png', '.jpg', '.jpeg', '.webp'},
    'engineering': {'.sldasm', '.sldprt', '.slddrw', '.step', '.stp', '.iges', '.igs', '.brep', '.pdf', '.dxf', '.dwg'},
}


def staged(project):
    return project.get('factory_type', 'cabinet') == 'cabinet' and not project.get('demo') \
        and project.get('evidence_policy') == 'staged' and not project.get('workflow_id')


def current(store, con, project, stage):
    record = (project.get('document_confirmations') or {}).get(stage)
    if not isinstance(record, dict):
        return None
    doc = next((item for item in store.all(con, 'documents', project['id'])
                if item['id'] == record.get('document_id')), None)
    if not doc or doc.get('project_id') != project['id'] or doc.get('superseded') or doc.get('archived') \
            or doc.get('sha256') != record.get('document_sha256'):
        return None
    if stage == 'render' and doc.get('purpose') != 'render':
        return None
    if stage != 'render' and (doc.get('purpose', 'drawing') != 'drawing'
                              or Path(doc.get('filename', '')).suffix.lower() not in EXTENSIONS[stage]):
        return None
    return doc


def engineering_ready(store, con, doc):
    if doc.get('resolved'):
        return engineering_readiness.source_resolution_current(store, con, doc)
    direct = [part for part in store.active_parts(con, doc['project_id'])
              if part.get('document_id') == doc['id']]
    return bool(direct) and all(part.get('approved') and not part.get('draft_only') for part in direct)


def blockers(store, con, project):
    if not staged(project):
        return []
    labels = {'render': '效果图', 'construction': '施工图', 'engineering': '工程图'}
    messages = []
    for stage in STAGES:
        doc = current(store, con, project, stage)
        if doc is None:
            messages.append(labels[stage] + '尚未记录客户确认，或确认的图纸已换版')
        elif stage == 'engineering':
            if not engineering_ready(store, con, doc):
                messages.append('工程图与构件的核验关联已失效')
    construction = current(store, con, project, 'construction')
    engineering = current(store, con, project, 'engineering')
    if construction and engineering and construction['id'] == engineering['id']:
        messages.append('施工图与工程图须分别选择对应文件')
    return messages


def confirm(store, con, project_id, data):
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    if not staged(project):
        raise APIError(409, '此项目未启用展柜图纸分阶段确认')
    if not isinstance(data, dict) or set(data) - {'stage', 'document_id', 'document_sha256', 'note', 'expected_confirmation_version'}:
        raise APIError(400, '图纸确认字段无效')
    stage = data.get('stage')
    if stage not in STAGES:
        raise APIError(400, '请选择效果图、施工图或工程图确认')
    version = project.get('document_confirmation_version', 0)
    if type(data.get('expected_confirmation_version')) is not int or data['expected_confirmation_version'] != version:
        raise APIError(409, '图纸确认状态已变化，请刷新后核对')
    identifier = data.get('document_id')
    if not isinstance(identifier, str) or not identifier.startswith('doc_') or len(identifier) > 128:
        raise APIError(400, '请选择本项目的图纸文件')
    doc = next((item for item in store.all(con, 'documents', project_id) if item['id'] == identifier), None)
    if not doc or doc.get('superseded') or doc.get('archived') or doc.get('demo') or doc.get('project_id') != project_id:
        raise APIError(409, '只能确认本项目当前有效的图纸')
    if data.get('document_sha256') != doc.get('sha256'):
        raise APIError(409, '图纸文件已变化，请刷新后重新确认')
    suffix = Path(doc.get('filename', '')).suffix.lower()
    if stage == 'render':
        if doc.get('purpose') != 'render':
            raise APIError(409, '效果图确认须选择效果图文件')
    elif doc.get('purpose', 'drawing') != 'drawing' or suffix not in EXTENSIONS[stage]:
        raise APIError(409, '所选文件不属于此阶段的图纸')
    for predecessor in STAGES[:STAGES.index(stage)]:
        if current(store, con, project, predecessor) is None:
            raise APIError(409, '前序图纸确认已缺失或换版，请从该阶段重新核对')
    if stage == 'engineering':
        construction = current(store, con, project, 'construction')
        if construction and construction['id'] == doc['id']:
            raise APIError(409, '工程图须选择区别于施工图的文件')
        if not engineering_ready(store, con, doc):
            raise APIError(409, '请先将工程图与本项目已审核构件或配套清单核验')
    # Uploaded bytes are verified before recording a customer decision.
    name = doc.get('storage_name')
    if not isinstance(name, str) or Path(name).name != name:
        raise APIError(409, '图纸原文件不可用，请重新上传')
    path = store.uploads / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve() \
            or hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
        raise APIError(409, '图纸原文件与记录不一致，请重新上传')
    note = short_text(data.get('note'), '客户确认依据', True, 500)
    old = dict(project.get('document_confirmations') or {})
    previous = old.get(stage) or {}
    if previous.get('document_id') == doc['id'] and previous.get('document_sha256') == doc['sha256'] and previous.get('note') == note:
        return {'project': project, 'unchanged': True}
    actor = access_control.get_actor()
    old[stage] = {'document_id': doc['id'], 'document_sha256': doc['sha256'], 'filename': doc['filename'],
                  'note': note, 'confirmed_at': now(), 'recorded_by': actor['name'] if actor else '本机操作员'}
    for later in STAGES[STAGES.index(stage)+1:]:
        old.pop(later, None)
    project['document_confirmations'] = old
    project['document_confirmation_version'] = version + 1
    project['updated_at'] = now()
    store.put(con, 'projects', project)
    store.event(con, project_id, 'customer_document_confirmation_recorded', '记录客户确认：' + doc['filename'],
                stage=stage, document_id=doc['id'], document_sha256=doc['sha256'], note=note,
                confirmation_version=project['document_confirmation_version'])
    return {'project': project, 'unchanged': False}
