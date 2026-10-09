"""Explicit project overview model selection; never creates engineering approval.

The selected document remains an uploaded, project-scoped derivative. Selection
is pinned to its document revision and content digest. A later upload must never
silently replace the overview with a part model.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib


MODEL_FORMATS = {'step', 'stp', 'iges', 'igs', 'brep', 'glb', 'obj', 'stl'}
ROLES = {'assembly': '装配结构模型', 'appearance': '整体外观模型'}


class ProjectSourcesError(ValueError):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


def _reason(store, project, doc):
    if not doc or doc.get('project_id') != project['id']:
        return '模型文件已移除或不属于本项目'
    if doc.get('demo') or doc.get('superseded') or doc.get('archived'):
        return '模型已换版或归档，请重新指定当前文件'
    if doc.get('purpose', 'drawing') not in ('drawing', 'engineering', 'model'):
        return '效果图和共用参考资料不能指定为项目工程模型'
    if any(doc.get(key) for key in ('reference_only', 'shared_reference', 'is_reference')) or doc.get('source_role') in ('reference', 'shared_reference', 'render'):
        return '共用参考资料不能指定为项目工程模型'
    if Path(str(doc.get('filename', ''))).suffix.lower().lstrip('.') not in MODEL_FORMATS:
        return '请选择 STEP、IGES、BREP、GLB、OBJ 或 STL 模型'
    name = doc.get('storage_name')
    if not isinstance(name, str) or not name or Path(name).name != name:
        return '模型原文件不可用，请重新上传'
    path = store.uploads / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve():
        return '模型原文件不可用，请重新上传'
    if not isinstance(doc.get('sha256'), str) or len(doc['sha256']) != 64:
        return '模型文件校验信息缺失，请重新上传'
    return None


def get_sources(store, con, project_id):
    project = store.get(con, 'projects', project_id)
    docs = store.all(con, 'documents', project_id)
    selected_id = project.get('main_model_document_id')
    selected = next((doc for doc in docs if doc['id'] == selected_id), None)
    pin = project.get('main_model_source') or {}
    reason = _reason(store, project, selected) if selected_id else None
    if selected_id and not reason and (pin.get('document_sha256') != selected.get('sha256') or pin.get('document_revision') != selected.get('revision') or pin.get('role') not in ROLES):
        reason = '模型版本已变化，请重新指定并核对'
    return {
        'project': project,
        'selection_version': project.get('main_model_version', 0),
        'selection': {
            'status': 'stale' if reason else 'selected' if selected_id else 'unselected',
            'document_id': selected_id,
            'filename': selected.get('filename') if selected else pin.get('filename'),
            'role': pin.get('role'), 'role_label': ROLES.get(pin.get('role')),
            'reason': reason,
        },
        'candidates': [{key: doc.get(key) for key in ('id', 'filename', 'sha256', 'revision', 'format')}
                       for doc in docs if not _reason(store, project, doc)],
    }


def save_selection(store, con, project_id, data):
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    if not isinstance(data, dict) or set(data) - {'expected_selection_version', 'main_model_document_id', 'document_sha256', 'role'}:
        raise ProjectSourcesError(400, '主模型设置字段无效')
    version = project.get('main_model_version', 0)
    if type(data.get('expected_selection_version')) is not int or data['expected_selection_version'] != version:
        raise ProjectSourcesError(409, '主模型设置已变化，请刷新后重新选择')
    if 'main_model_document_id' not in data:
        raise ProjectSourcesError(400, '请选择主模型，或明确清除当前选择')
    identifier = data['main_model_document_id']
    pin = None
    if identifier is not None:
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            raise ProjectSourcesError(400, '请选择本项目模型文件')
        doc = next((doc for doc in store.all(con, 'documents', project_id) if doc['id'] == identifier), None)
        reason = _reason(store, project, doc)
        if reason:
            raise ProjectSourcesError(400, reason)
        if data.get('document_sha256') != doc['sha256']:
            raise ProjectSourcesError(409, '模型文件已变化，请刷新后重新选择')
        if not isinstance(data.get('role'), str) or data['role'] not in ROLES:
            raise ProjectSourcesError(400, '请选择整体外观模型或装配结构模型')
        if hashlib.sha256((store.uploads / doc['storage_name']).read_bytes()).hexdigest() != doc['sha256']:
            raise ProjectSourcesError(409, '模型原文件与保存版本不一致，请重新上传')
        pin = {'filename': doc['filename'], 'document_sha256': doc['sha256'],
               'document_revision': doc.get('revision'), 'role': data['role']}
    elif data.get('document_sha256') or data.get('role'):
        raise ProjectSourcesError(400, '清除主模型时不要传入模型用途或校验信息')
    old_pin = project.get('main_model_source') or {}
    unchanged = project.get('main_model_document_id') == identifier and (pin is None or all(old_pin.get(key) == value for key, value in pin.items()))
    if not unchanged:
        project['main_model_document_id'] = identifier
        project['main_model_source'] = {**pin, 'selected_at': datetime.now(timezone.utc).isoformat(timespec='seconds')} if pin else None
        project['main_model_version'] = version + 1
        store.put(con, 'projects', project)
        store.event(con, project_id, 'project_main_model_selected' if pin else 'project_main_model_cleared',
                    '指定项目主模型：' + pin['filename'] if pin else '清除项目主模型',
                    document_id=identifier, source=pin, selection_version=project['main_model_version'])
    return {**get_sources(store, con, project_id), 'unchanged': unchanged}
