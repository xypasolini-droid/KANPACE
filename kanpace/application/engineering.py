"""EngineeringService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from datetime import datetime, timezone
from drawing_media import project_media, asset_path, validate_render, render_media, RenderImageError
from kanpace.core.constants import MAX_UPLOAD, MAX_CAD_UPLOAD, MAX_PDF_UPLOAD
from kanpace.core.errors import APIError
from kanpace.core.validation import now
from kanpace.core.validation import number
from kanpace.core.validation import short_text
from kanpace.core.validation import uid
from kanpace.domain.parts import part_blockers
from pathlib import Path
from upload_preview import preview_pdf, PreviewError
import access_control
import base64
import binascii
import engine
import engineering_readiness
import hashlib
import json
import operations
import order_drafts
import order_packet


class EngineeringService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def invalidate(self, con, project, reason, part_id=None):
        self.store.require_project_open(project)
        tasks = self.store.active_tasks(con, project['id'])
        affected = {t['id'] for t in tasks if part_id is None or t.get('part_id') == part_id}
        while True:
            additional = {t['id'] for t in tasks if set(t.get('dependencies', [])) & affected}
            if additional <= affected:
                break
            affected |= additional
        for task in tasks:
            if task['id'] in affected:
                if task['status'] != 'invalidated':
                    task['previous_status'] = task['status']
                task['status'] = 'invalidated'
                task['invalidation_reason'] = reason
                self.store.bump_execution(task)
                self.store.put(con, 'tasks', task)
        old_revision = project['revision']
        project['revision'] += 1
        project['status'] = 'review'
        project['updated_at'] = now()
        project['change_notice'] = reason + '；请重新审核、生成任务并发布版本。'
        self.store.put(con, 'projects', project)
        self.store.event(con, project['id'], 'revision_changed', reason, previous_revision=old_revision,
                   revision=project['revision'], affected_tasks=sorted(affected))
        return sorted(affected)

    def create_part(self, con, data):
        project = self.store.get(con, 'projects', str(data.get('project_id', '')))
        self.store.require_project_open(project)
        source_doc = None
        if 'source_document_id' in data:
            identifier = data['source_document_id']
            if not isinstance(identifier, str) or not identifier.startswith('doc_'):
                raise APIError(400, '请选择本项目的工程依据文件')
            source_doc = self.store.get(con, 'documents', identifier)
            if (source_doc.get('project_id') != project['id'] or source_doc.get('superseded')
                    or source_doc.get('archived') or source_doc.get('purpose', 'drawing') != 'drawing'
                    or not source_doc.get('sha256')):
                raise APIError(409, '只能关联本项目当前有效的工程依据文件')
        part = {'id': uid('part'), 'project_id': project['id'], 'document_id': None, 'unit': 'mm',
                'review_status': 'pending', 'issues': [], 'source': {'file': '人工录入', 'reference': '手工部件', 'revision': project['revision'] + 1},
                'created_at': now(), 'demo': project.get('demo', False)}
        if source_doc:
            part['document_id'] = source_doc['id']
            part['source'] = {'file': source_doc['filename'], 'reference': '人工对照原图补录',
                              'revision': project['revision'] + 1, 'sha256': source_doc['sha256'],
                              'source_document_id': source_doc['id'], 'manual_source_link': True}
        self.store.apply_part_edits(part, data)
        part.setdefault('name', '未命名部件')
        part.setdefault('quantity', None)
        part.setdefault('category', None)
        part.setdefault('material', '')
        self.store.invalidate(con, project, '人工新增部件：' + part['name'])
        part['revision'] = project['revision']
        self.store.put(con, 'parts', part)
        self.store.event(con, project['id'], 'part_created', '新增待审核部件：' + part['name'], part_id=part['id'])
        return part

    def apply_part_edits(self, part, edits):
        for alias in ('length_mm', 'width_mm', 'thickness_mm'):
            if alias in edits:
                edits = dict(edits)
                edits[alias.replace('_mm', '')] = edits[alias]
        for key in ('name', 'material', 'category', 'finish', 'notes', 'pricing_unit'):
            if key in edits:
                part[key] = short_text(edits[key], key, key == 'name', 2000 if key == 'notes' else 200)
        for key in ('length', 'width', 'thickness', 'quantity', 'unit_price', 'weight_kg'):
            if key in edits:
                value = edits[key]
                part[key] = None if value is None or value == '' else number(value, key, positive=key != 'unit_price')
        if 'unit' in edits and edits['unit'] != 'mm':
            raise APIError(400, '人工编辑统一使用毫米 mm')
        if 'unit' in edits or all(key in edits for key in ('length', 'width', 'thickness')):
            part['unit'] = 'mm'
            part['unit_confirmed_at'] = now()
        if 'processes' in edits:
            if not isinstance(edits['processes'], list) or any(not isinstance(x, str) for x in edits['processes']):
                raise APIError(400, 'processes 必须为字符串数组')
            part['processes'] = edits['processes'][:30]

    def review_part(self, con, identifier, data):
        part = self.store.get(con, 'parts', identifier)
        if part.get('archived'):
            raise APIError(409, '历史部件不可修改，请操作当前版本')
        if not isinstance(data.get('approved'), bool):
            raise APIError(400, 'approved 必须为 true 或 false')
        project = self.store.get(con, 'projects', part['project_id'])
        self.store.require_project_open(project)
        edits = data.get('edits', {})
        if not isinstance(edits, dict):
            raise APIError(400, 'edits 必须为对象')
        before = dict(part)
        self.store.apply_part_edits(part, edits)
        changed = any(part.get(k) != before.get(k) for k in ('name','material','category','length','width','thickness','quantity','finish','processes','unit_price','pricing_unit','weight_kg'))
        blockers = part_blockers(part)
        review_note = short_text(data.get('review_note', edits.get('notes', part.get('notes', ''))), '审核依据', limit=2000)
        if data['approved'] and part.get('source', {}).get('manual_source_link') and not review_note:
            raise APIError(409, '人工补录构件须填写与所关联工程文件的核对依据')
        critical_source_issues = [issue for issue in part.get('source_issues', []) if
            '重复' in issue or '示意样本' in issue or ('尺寸单位未明确' in issue and not part.get('unit_confirmed_at'))]
        if data['approved'] and critical_source_issues and not review_note:
            raise APIError(409, '来源存在冲突或待核验说明，请填写审核依据后批准', critical_source_issues)
        if data['approved'] and part.get('source', {}).get('step_proposal'):
            confirmation = data.get('engineering_confirmation')
            if not isinstance(confirmation, dict) or confirmation.get('quantity_confirmed') is not True \
                    or confirmation.get('manufacturing_dimensions_confirmed') is not True:
                raise APIError(409, 'STEP 候选批准前，须重新确认订单数量与加工尺寸')
            if not review_note:
                raise APIError(409, 'STEP 候选批准前，须填写施工图或工程核对依据')
            proposal = part['source']['step_proposal']
            proposal['approved_values'] = {key: part.get(key) for key in ('quantity', 'length', 'width', 'thickness')}
            proposal['approved_at'] = now()
            part['source']['manufacturing_dimensions_confirmed'] = True
        if review_note:
            part['review_note'] = review_note
        if data['approved'] and blockers:
            raise APIError(409, '部件信息不完整，无法审核通过', blockers)
        invalidated = []
        if changed or (before.get('approved') and not data['approved']):
            invalidated = self.store.invalidate(con, project, '部件变更：' + part['name'], part['id'])
            part['history'] = before.get('history', []) + [{'revision': before.get('revision'), 'changed_at': now(),
                'values': {k: before.get(k) for k in ('name','material','category','length','width','thickness','quantity','finish','review_status')}}]
        part['review_status'] = 'approved' if data['approved'] else 'pending'
        part['reviewed_at'] = now() if data['approved'] else None
        part['revision'] = project['revision']
        part['issues'] = blockers
        self.store.put(con, 'parts', part)
        self.store.event(con, project['id'], 'part_reviewed', ('审核通过：' if data['approved'] else '退回待审：') + part['name'],
                   part_id=part['id'], edits=edits, invalidated_tasks=invalidated)
        return {'part': part, 'invalidated_tasks': invalidated}

    def related_order_drafts(self, con, digest, projects=None):
        if not digest:
            return []
        projects = projects if projects is not None else self.store.all(con, 'projects')
        return [{'project_id': p['id'], 'name': p['name'], 'part_count': p['order_draft'].get('part_count', 0)}
                for p in projects if any(source.get('sha256') == digest
                    for source in p.get('order_draft', {}).get('sources', []))]

    def validate_draft_sources(self, con, payload, project):
        """Bind registered provenance to this factory's current document snapshot.

        A model's source identity/hash is a claim until resolved here. Legacy
        absolute paths remain draft references, never file reads or approval.
        """
        for source in payload.get('sources', []):
            if not source.get('document_id'):
                continue
            try:
                document = self.store.get(con, 'documents', source['document_id'])
            except APIError as exc:
                raise APIError(400, 'EvidenceRef 未对应已登记文件') from exc
            if (document.get('project_id') != project['id'] or document.get('superseded')
                    or document.get('archived') or document.get('purpose', 'drawing') != 'drawing'):
                raise APIError(409, 'EvidenceRef 只能引用本项目当前有效工程文件')
            if not document.get('sha256') or source.get('source_sha256') != document['sha256']:
                raise APIError(409, 'EvidenceRef 文件 SHA-256 与登记版本不一致')
            claimed_revision = source.get('source_revision')
            if claimed_revision is None:
                claimed_revision = source.get('revision')
            if claimed_revision is not None and str(claimed_revision) != str(document.get('revision')):
                raise APIError(409, 'EvidenceRef 文件版本已变化')
            source['source_revision'] = document.get('revision')
            source.setdefault('revision', document.get('revision'))
            source['filename'] = document['filename']
        # Resolve inherited hashes/revisions again after server registration.
        for part in payload.get('parts', []):
            try:
                part['evidence'] = [order_drafts.bind_evidence(item, payload.get('sources', []))
                                    for item in part.get('evidence', [])]
            except ValueError as exc:
                raise APIError(400, str(exc)) from exc

    def import_file(self, con, data):
        project = self.store.get(con, 'projects', str(data.get('project_id', '')))
        self.store.require_project_open(project)
        purpose = data.get('purpose', 'drawing')
        if purpose not in ('drawing', 'render', 'process'):
            raise APIError(400, '文件用途必须为 drawing、render 或 process')
        filename = short_text(data.get('filename'), '文件名', True, 240)
        if '/' in filename or '\\' in filename or filename in ('.', '..') or any(ord(c) < 32 for c in filename):
            raise APIError(400, '文件名不可含路径或控制字符')
        source_relative = order_packet.relative_path(data.get('relative_path'), filename)
        encoded = data.get('content_base64')
        if not isinstance(encoded, str):
            raise APIError(400, '缺少 content_base64')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise APIError(400, '文件内容不是合法 Base64')
        extension=Path(filename).suffix.lower()
        limit=(MAX_PDF_UPLOAD if extension=='.pdf' else MAX_CAD_UPLOAD if extension in ('.dwg','.sldprt','.sldasm','.slddrw','.step','.stp','.iges','.igs','.brep') else MAX_UPLOAD) if purpose!='render' else MAX_UPLOAD
        if not content or len(content) > limit:
            raise APIError(413, f'文件必须非空且不大于 {limit//1024//1024} MB')
        digest = hashlib.sha256(content).hexdigest()
        existing = self.store.all(con, 'documents', project['id'])
        if purpose == 'render':
            return self.store.import_render(con, project, filename, content, digest, existing, data.get('render_scope','project'))
        if purpose == 'process':
            return self.store.import_process_basis(con, project, filename, content, digest, existing)
        # A native CAD file is kept as the source of truth.  A viewable export
        # can be explicitly attached to it, but must never masquerade as the
        # parsed original or inherit its approval/revision automatically.
        related_id = data.get('related_document_id')
        companion_for = None
        if related_id is not None:
            if not isinstance(related_id, str) or not related_id.startswith('doc_') or len(related_id) > 100:
                raise APIError(400, '关联工程原件编号无效')
            source_doc = self.store.get(con, 'documents', related_id)
            if (source_doc.get('project_id') != project['id'] or source_doc.get('superseded')
                    or source_doc.get('purpose', 'drawing') != 'drawing'
                    or Path(source_doc.get('filename', '')).suffix.lower() not in ('.dwg', '.sldasm', '.sldprt', '.slddrw')):
                raise APIError(409, '只能关联本项目当前有效的 DWG 或 SolidWorks 原件')
            if extension not in ('.pdf', '.dxf', '.step', '.stp', '.iges', '.igs', '.brep', '.xlsx', '.xls', '.csv', '.json'):
                raise APIError(422, '配套核对资料请使用 PDF、DXF、STEP 或 BOM 表格')
            companion_for = {'document_id': source_doc['id'], 'sha256': source_doc['sha256']}
        for doc in existing:
            if doc.get('purpose', 'drawing') == purpose and doc['sha256'] == digest and not doc.get('superseded'):
                doc.setdefault('relative_path', source_relative)
                doc['source_paths'] = list(dict.fromkeys(doc.get('source_paths', [doc['relative_path']]) + [source_relative]))
                if companion_for and companion_for not in doc.get('companion_for', []):
                    doc['companion_for'] = doc.get('companion_for', []) + [companion_for]
                self.store.put(con, 'documents', doc)
                return {'document': doc, 'parts': [p for p in self.store.active_parts(con, project['id']) if p.get('document_id') == doc['id']],
                        'warnings': doc.get('warnings', []), 'duplicate': True,
                        'existing_drafts': self.store.related_order_drafts(con, digest)}
        try:
            parsed = engine.parse_document(filename, content)
        except Exception as exc:
            parsed = {'format': Path(filename).suffix.lstrip('.').upper() or 'UNKNOWN', 'status': 'error',
                      'parts': [], 'geometry': [], 'warnings': ['解析失败：' + str(exc)[:500]]}
        if not isinstance(parsed, dict):
            raise APIError(422, '解析器未返回有效文档')
        if parsed.get('format') == 'order_draft':
            draft = dict(parsed.get('order_draft', {}), parts=parsed.get('parts', []))
            self.validate_draft_sources(con, draft, project)
        doc_id = uid('doc')
        path = self.store.uploads / (doc_id + '.source')
        path.write_bytes(content)
        doc = {'id': doc_id, 'project_id': project['id'], 'filename': filename, 'sha256': digest,
               'relative_path': source_relative, 'source_paths': [source_relative],
               'size': len(content), 'storage_name': path.name, 'created_at': now(),
               'format': parsed.get('format', 'UNKNOWN'), 'status': parsed.get('status', 'error'),
               'warnings': parsed.get('warnings', []), 'geometry': parsed.get('geometry', []),
               'demo': False, 'resolved': False, 'purpose': purpose}
        if companion_for:
            doc['companion_for'] = [companion_for]
        replaced = []
        for d in existing:
            if d.get('purpose', 'drawing') != purpose or d.get('superseded'): continue
            aliases = d.get('source_paths') or [d.get('relative_path') or d['filename']]
            remaining = [a for a in aliases if a.casefold() != source_relative.casefold()]
            if len(remaining) == len(aliases): continue
            if remaining:
                # A byte-identical shared file can have several source paths.
                # Replacing one must not retire the other cabinet's copy.
                d['source_paths'] = remaining
                d['relative_path'] = remaining[0]
                self.store.put(con, 'documents', d)
            else: replaced.append(d)
        for previous in replaced:
            previous['superseded'] = True
            previous['superseded_by'] = doc_id
            self.store.put(con, 'documents', previous)
            for part in self.store.active_parts(con, project['id']):
                if part.get('document_id') == previous['id']:
                    part['archived'] = True
                    self.store.put(con, 'parts', part)
        self.store.invalidate(con, project, ('同名图纸/BOM 版本更新：' if replaced else '导入文件：') + filename)
        doc['revision'] = project['revision']
        parts = []
        for index, incoming in enumerate(parsed.get('parts', [])):
            if not isinstance(incoming, dict):
                continue
            part = access_control.filter_imported_part_prices(incoming)
            part['source_issues'] = list(incoming.get('issues', []))
            part.update({'id': uid('part'), 'project_id': project['id'], 'document_id': doc_id,
                         'revision': project['revision'], 'review_status': 'pending', 'created_at': now(),
                         'demo': False, 'archived': False})
            # Never trust parser-provided workflow approval or arbitrary client IDs.
            part.setdefault('source', {'file': filename, 'reference': str(index + 1), 'revision': None})
            part['source']['external_id'] = str(incoming.get('id') or '')
            if project.get('order_draft'):
                part.setdefault('item_level', 'component')
                part['draft_only'] = True
            self.store.put(con, 'parts', part)
            parts.append(part)
        doc['part_count'] = len(parts)
        if Path(filename).suffix.lower() == '.pdf':
            try:
                preview = preview_pdf(self.store.data_dir, doc, path)
                doc.update({'page_count': preview['page_count'], 'preview_status': 'ready', 'previews': [preview]})
            except (PreviewError, OSError) as exc:
                doc.update({'preview_status': 'error', 'preview_error': str(exc)})
        if not parts and doc['status'] in ('parsed', 'needs_review'):
            doc['status'] = 'needs_review'
            doc['warnings'] = doc.get('warnings', []) + ['没有可用部件；须补齐 BOM 或人工录入后注明替代关系。']
        self.store.put(con, 'documents', doc)
        self.store.event(con, project['id'], 'file_imported', '导入 ' + filename + '，识别 ' + str(len(parts)) + ' 个待审核部件',
                   document_id=doc_id, sha256=digest, parser_status=doc['status'], replaces=[d['id'] for d in replaced])
        return {'document': doc, 'parts': parts, 'warnings': doc['warnings'], 'duplicate': False,
                'existing_drafts': self.store.related_order_drafts(con, digest)}

    def import_process_basis(self, con, project, filename, content, digest, existing):
        """Store explicit industry work instructions without interpreting a cabinet BOM."""
        workflow = (operations.get(self.store, con, 'project_workflows', project['workflow_id'])
                    if project.get('workflow_id') else None)
        if not project.get('industry_id') and not (workflow or {}).get('industry_id'):
            raise APIError(409, '请先选择本厂行业流程，再上传行业工艺依据', {'code': 'industry_workflow_required'})
        allowed = {'.pdf', '.xlsx', '.xls', '.csv', '.json', '.docx', '.doc', '.txt', '.jpg', '.jpeg', '.png', '.webp',
                   '.max', '.dwg', '.dxf', '.sldasm', '.sldprt', '.slddrw', '.step', '.stp', '.iges', '.igs', '.brep', '.stl', '.obj', '.glb'}
        if Path(filename).suffix.lower() not in allowed:
            raise APIError(422, '此文件类型暂不支持作为行业工艺依据')
        for doc in existing:
            if doc.get('purpose') == 'process' and doc.get('sha256') == digest and not doc.get('superseded'):
                return {'document': doc, 'parts': [], 'warnings': doc.get('warnings', []), 'duplicate': True,
                        'existing_drafts': [], 'archive_only': True}
        # A draft can be rebuilt and reviewed after its source changes. Released
        # or executed work cannot be silently invalidated by an archive upload.
        if any(not operations.workflow_task_replaceable(t) for t in self.store.active_tasks(con, project['id'])):
            raise APIError(409, '已有已发布或执行过的工序，请先明确变更工作范围再更新工艺依据；当前生产版本未改变',
                           {'code': 'process_source_in_use'})
        doc_id = uid('doc')
        path = self.store.uploads / (doc_id + '.source')
        replaced = [d for d in existing if d.get('purpose') == 'process' and not d.get('superseded')
                    and d['filename'].casefold() == filename.casefold()]
        path.write_bytes(content)
        for previous in replaced:
            previous.update(superseded=True, superseded_by=doc_id)
            self.store.put(con, 'documents', previous)
        self.store.invalidate(con, project, ('更新工艺依据：' if replaced else '上传工艺依据：') + filename)
        doc = {'id': doc_id, 'project_id': project['id'], 'filename': filename, 'sha256': digest,
               'size': len(content), 'storage_name': path.name, 'created_at': now(), 'revision': project['revision'],
               'purpose': 'process', 'format': Path(filename).suffix.lstrip('.').upper(), 'status': 'needs_review',
               'resolved': False, 'archive_only': True, 'part_count': 0, 'geometry': [], 'demo': False,
               'industry_id': project.get('industry_id') or workflow['industry_id'],
               'warnings': ['工艺依据待关联工作包并核验']}
        if Path(filename).suffix.lower() == '.pdf':
            try:
                preview = preview_pdf(self.store.data_dir, doc, path)
                doc.update(page_count=preview['page_count'], preview_status='ready', previews=[preview])
            except (PreviewError, OSError) as exc:
                doc.update(preview_status='error', preview_error=str(exc))
        self.store.put(con, 'documents', doc)
        self.store.event(con, project['id'], 'process_basis_uploaded', '工艺依据存档：' + filename,
                   document_id=doc_id, sha256=digest, replaces=[d['id'] for d in replaced], archive_only=True)
        return {'document': doc, 'parts': [], 'warnings': doc['warnings'], 'duplicate': False,
                'existing_drafts': [], 'archive_only': True}

    def process_basis_verified(self, con, project, doc):
        """A previous check never authorizes a changed file or a later work package."""
        binding = doc.get('process_verification') or {}
        if doc.get('superseded') or not doc.get('resolved') or not project.get('workflow_id'):
            return False
        workflow = operations.get(self.store, con, 'project_workflows', project['workflow_id'])
        linked = any(doc['id'] in obj.get('document_ids', []) for obj in workflow['objects'])
        return bool(workflow.get('industry_id') and workflow['status'] == 'reviewed' and linked
                    and workflow['revision'] == project['revision']
                    and binding.get('workflow_id') == workflow['id']
                    and binding.get('workflow_version') == workflow['version']
                    and binding.get('project_revision') == project['revision']
                    and binding.get('document_sha256') == doc['sha256'])

    def import_render(self, con, project, filename, content, digest, existing, scope='project'):
        # Reference images describe appearance; their upload must not alter the
        # engineering revision, approval, release or any production task.
        if scope not in ('project','cabinet'):
            raise APIError(400, '效果图范围必须为 project 或 cabinet')
        try:
            image = validate_render(filename, content)
        except RenderImageError as exc:
            raise APIError(422, str(exc))
        except RuntimeError as exc:
            raise APIError(503, str(exc))
        for doc in existing:
            if doc.get('purpose') == 'render' and doc.get('sha256') == digest and not doc.get('superseded'):
                return {'document': doc, 'parts': [], 'warnings': [], 'duplicate': True,
                        'existing_drafts': [], 'render': render_media(doc)}
        doc_id = uid('doc')
        path = self.store.uploads / (doc_id + '.source')
        path.write_bytes(content)
        doc = {'id': doc_id, 'project_id': project['id'], 'filename': filename,
               'sha256': digest, 'size': len(content), 'storage_name': path.name,
               'created_at': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
               'purpose': 'render', 'render_scope': scope, 'format': Path(filename).suffix.lstrip('.').upper(),
               'status': 'reference', 'resolved': True, 'warnings': [], 'geometry': [],
               'part_count': 0, 'demo': False, 'image': image,
               'image_url': '/api/documents/' + doc_id + '/image'}
        replaced = [d for d in existing if d.get('purpose') == 'render'
                    and d['filename'].casefold() == filename.casefold() and not d.get('superseded')]
        for previous in replaced:
            previous['superseded'] = True
            previous['superseded_by'] = doc_id
            self.store.put(con, 'documents', previous)
        confirmed = (project.get('document_confirmations') or {}).get('render') or {}
        if any(previous['id'] == confirmed.get('document_id') for previous in replaced):
            # A changed customer-approved appearance may affect fabrication.
            # Keep the old confirmation for audit, but invalidate its tasks.
            self.store.invalidate(con, project, '客户已确认效果图换版：' + filename)
        self.store.put(con, 'documents', doc)
        self.store.event(con, project['id'], 'render_uploaded', '上传效果图：' + filename,
                   document_id=doc_id, sha256=digest, replaces=[d['id'] for d in replaced])
        return {'document': doc, 'parts': [], 'warnings': [], 'duplicate': False,
                'existing_drafts': [], 'render': render_media(doc)}

    def import_order_draft(self, con, data):
        try:
            payload = order_drafts.normalise(data)
        except (ValueError, TypeError, AttributeError) as exc:
            raise APIError(400, str(exc))
        if payload['project']['due_date']:
            try:
                datetime.strptime(payload['project']['due_date'], '%Y-%m-%d')
            except ValueError:
                raise APIError(400, '交期格式应为 YYYY-MM-DD')
        # The source order and source revision identify one draft project.
        identity = hashlib.sha256(json.dumps([payload['order_key'], payload['source_revision']], ensure_ascii=False).encode()).hexdigest()
        existing = next((p for p in self.store.all(con, 'projects') if p.get('order_import_key') == identity), None)
        if payload.get('project_id'):
            project = self.store.get(con, 'projects', payload['project_id'])
            self.store.require_project_open(project)
            if existing and existing['id'] != project['id']:
                raise APIError(409, '该订单版本已经属于另一个拆单项目')
            if payload.get('expected_revision') is None or payload['expected_revision'] != project['revision']:
                raise APIError(409, '项目版本已变化或缺少 expected_revision，请重新核对')
        elif any(source.get('document_id') for source in payload['sources']):
            raise APIError(400, '登记文件拆单导入需要 project_id 与 expected_revision')
        elif existing:
            project = existing
        else:
            project_data = dict(payload['project'])
            project_data['quantity'] = project_data['quantity'] or 1
            project = self.store.new_project(con, project_data)
            project['order_import_key'] = identity
        self.validate_draft_sources(con, payload, project)
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        imported = self.store.import_file(con, {'project_id': project['id'], 'filename': 'order-draft-' + identity[:16] + '.json',
                                         'content_base64': base64.b64encode(content).decode()})
        project = self.store.get(con, 'projects', project['id'])
        project.update(payload['project'])
        project['order_import_key'] = identity
        project['code'] = payload['order_key']
        project['order_draft'] = {key: value for key, value in payload.items() if key not in ('parts', 'project')}
        project['order_draft']['document_id'] = imported['document']['id']
        project['order_draft']['sha256'] = imported['document']['sha256']
        project['order_draft']['part_count'] = len(imported['parts'])
        project['order_draft']['scope_count'] = sum(len(p.get('work_scopes', [])) for p in imported['parts'])
        project['quantity_note'] = '数量按来源清单原计量单位保留；未知数量为空，不推算。'
        self.store.put(con, 'projects', project)
        return {**imported, 'project': project, 'draft': True}

    def generate(self, con, project_id):
        project = self.store.get(con, 'projects', project_id)
        self.store.require_project_open(project)
        if project.get('industry_id') or project.get('factory_type', 'cabinet') != 'cabinet':
            raise APIError(422, '请使用本厂行业流程配置工作包，再生成工种任务', {'code':'industry_workflow_required','page':'templates','project_id':project_id})
        parts = self.store.active_parts(con, project_id)
        blockers = [b for part in parts for b in part_blockers(part)]
        if not parts:
            blockers.append('请先导入 BOM 或人工录入部件')
        if blockers:
            raise APIError(409, '部件数据不足，无法生成完整工艺任务', blockers)
        existing = self.store.active_tasks(con, project_id)
        if existing and all(t.get('revision') == project['revision'] and t['status'] != 'invalidated' for t in existing):
            return {'tasks': existing, 'blockers': [], 'unchanged': True}
        generated = engine.generate_tasks(parts)
        if not generated:
            raise APIError(409, '没有可生成的工艺任务，请检查部件类别')
        # A drawing change invalidates only its affected dependency closure. Carry
        # unchanged operations forward so completed work is not requested twice.
        def operation_key(task):
            return (task.get('part_id'), task.get('process'), task.get('trade'),
                    task.get('rule_id'), task.get('hours'), task.get('quantity'))
        carry = {operation_key(t): dict(t) for t in existing if t['status'] != 'invalidated'}
        for old in existing:
            old['archived'] = True
            if old['status'] != 'invalidated':
                old['previous_status'] = old['status']
            old['status'] = 'invalidated'
            self.store.bump_execution(old)
            self.store.put(con, 'tasks', old)
        mapping = {task['id']: uid('task') for task in generated}
        tasks = []
        for task in generated:
            task = dict(task)
            task['id'] = mapping[task['id']]
            try:
                task['dependencies'] = [mapping[dep] for dep in task.get('dependencies', [])]
            except KeyError:
                raise APIError(500, '工艺依赖存在未定义节点')
            previous = carry.get(operation_key(task))
            task.update({'project_id': project_id, 'revision': project['revision'], 'status': 'draft',
                         'assignee': None, 'created_at': now(), 'archived': False, 'demo': project.get('demo', False)})
            if previous:
                for field in ('status', 'assignee', 'started_at', 'completed_at', 'notes', 'updated_at', 'inspection_result', 'inspection_recorded_at',
                              'completed_quantity', 'progress_recorded', 'priority', 'pause_reason', 'pause_note', 'handover_note', 'paused_at', 'resumed_at',
                              'interrupted_by_task_id', 'execution_version'):
                    if field in previous:
                        task[field] = previous[field]
                task['carried_from_task_id'] = previous['id']
                task['carried_from_revision'] = previous['revision']
                self.store.bump_execution(task)
            self.store.put(con, 'tasks', task)
            tasks.append(task)
        project['status'] = 'review'
        project['planned_revision'] = project['revision']
        self.store.put(con, 'projects', project)
        carried = [t['id'] for t in tasks if t.get('carried_from_task_id')]
        self.store.event(con, project_id, 'tasks_generated', '生成 ' + str(len(tasks)) + ' 项工艺任务，承接 ' + str(len(carried)) + ' 项未受影响工序状态', revision=project['revision'], carried_tasks=carried)
        return {'tasks': tasks, 'blockers': [p['name'] + ' 尚未审核' for p in parts if not p['approved']]}

    def release(self, con, project_id):
        project = self.store.get(con, 'projects', project_id)
        self.store.require_project_open(project)
        parts = self.store.active_parts(con, project_id)
        tasks = self.store.active_tasks(con, project_id)
        blockers = engineering_readiness.release_blockers(self.store, con, project, part_blockers)
        if blockers:
            raise APIError(409, '发布被阻断；先处理以下项目', blockers)
        project['status'] = 'released'
        project['released_revision'] = project['revision']
        project['released_at'] = now()
        project.pop('change_notice', None)
        self.store.put(con, 'projects', project)
        for task in tasks:
            if task['status'] == 'draft':
                task['status'] = 'blocked' if task.get('carried_status') == 'blocked' else 'ready'
                self.store.bump_execution(task)
                self.store.put(con, 'tasks', task)
        # Immutable snapshot records what was authorized for this revision.
        snapshot = {'id': uid('rel'), 'project_id': project_id, 'revision': project['revision'],
                    'created_at': now(), 'parts': parts, 'tasks': tasks}
        prior = [r for r in self.store.all(con, 'releases', project_id) if r['revision'] == project['revision']]
        if not prior:
            self.store.put(con, 'releases', snapshot)
        self.store.event(con, project_id, 'revision_released', '发布生产版本 R' + str(project['revision']), revision=project['revision'])
        return {'project': project, 'tasks': tasks}

    def resolve_document(self, con, identifier, data):
        doc = self.store.get(con, 'documents', identifier)
        project = self.store.get(con, 'projects', doc['project_id'])
        self.store.require_project_open(project)
        note = short_text(data.get('note'), '补录核验说明', True, 2000)
        if doc.get('purpose') == 'process':
            operations.check_fields(data, {'note', 'workflow_id', 'expected_workflow_version', 'expected_revision', 'acknowledge_process_basis'})
            if data.get('acknowledge_process_basis') is not True:
                raise APIError(409, '请确认工艺依据内容、版本与本工作包对应', {'code': 'process_review_required'})
            if doc.get('superseded'):
                raise APIError(409, '该工艺文件已被新版本替代，请核验最新文件')
            if not project.get('workflow_id'):
                raise APIError(409, '请先建立并审核本项目工作包', {'code': 'process_workflow_unreviewed'})
            operations.integer(data.get('expected_revision'), '项目版本', minimum=1)
            operations.integer(data.get('expected_workflow_version'), '工作包版本', minimum=1)
            if data.get('expected_revision') != project['revision'] or data.get('workflow_id') != project.get('workflow_id'):
                raise APIError(409, '项目或工作包版本已变化，请重新核对', {'code': 'process_review_stale'})
            workflow = operations.get(self.store, con, 'project_workflows', project.get('workflow_id'))
            if workflow.get('project_id') != project['id'] or not workflow.get('industry_id'):
                raise APIError(409, '此文件需要本项目的行业工作包核验')
            if data.get('expected_workflow_version') != workflow['version'] or workflow['revision'] != project['revision']:
                raise APIError(409, '工作包版本已变化，请重新核对', {'code': 'process_review_stale'})
            if workflow['status'] != 'reviewed':
                raise APIError(409, '请先完成工作对象和行业字段复核，再核验工艺文件', {'code': 'process_workflow_unreviewed'})
            if not any(doc['id'] in obj.get('document_ids', []) for obj in workflow['objects']):
                raise APIError(409, '工作包尚未关联这份工艺文件，请先补充对应关系并重新复核', {'code': 'process_document_unlinked'})
            actor = access_control.get_actor()
            doc.update(resolved=True, status='verified', resolution_note=note, resolved_at=now(), warnings=[],
                       process_verification={'workflow_id': workflow['id'], 'workflow_version': workflow['version'],
                                             'project_revision': project['revision'], 'document_sha256': doc['sha256'],
                                             'reviewer': actor['name'] if actor else '本机操作员', 'note': note, 'verified_at': now()})
            self.store.put(con, 'documents', doc)
            self.store.event(con, doc['project_id'], 'process_basis_verified', '行业工艺依据已核验：' + doc['filename'],
                       document_id=doc['id'], workflow_id=workflow['id'], workflow_version=workflow['version'], sha256=doc['sha256'], note=note)
            return doc
        if doc.get('superseded') or doc.get('archived'):
            raise APIError(409, '该工程原件已换版，请核验当前文件')
        verified = engineering_readiness.source_resolution_candidates(self.store, con, doc)
        if not verified:
            raise APIError(409, '请将本原件关联配套 BOM，或在人工补录构件时选择本文件并审核部件后再核验')
        doc['resolved'] = True
        doc['resolution_note'] = note
        doc['resolved_at'] = now()
        doc['verified_part_ids'] = [p['id'] for p, _ in verified]
        doc['resolution_evidence'] = engineering_readiness.source_resolution_evidence(doc, verified)
        self.store.put(con, 'documents', doc)
        self.store.event(con, doc['project_id'], 'source_resolved', '原文件已登记人工核验：' + doc['filename'],
                   document_id=doc['id'], note=note, verified_part_ids=doc['verified_part_ids'])
        return doc
