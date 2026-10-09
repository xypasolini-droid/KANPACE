"""Factory-local evidence preflight, shared with the production release gate.

This module aggregates recorded facts. It does not infer dimensions from images,
run an LLM, approve components, create tasks, or change manufacturing records.
The caller must resolve the authorized project before calling inspect_project.
"""
from pathlib import Path
import hashlib
import json
import os

import fulfillment
import engineering_engines
import langgraph_agent
import operations
import production
import project_sources
from kanpace.domain.parts import part_blockers


STAGES = {
    'sources': ('补齐工程资料', 'drawing'),
    'parts': ('核对构件与尺寸', 'drawing'),
    'workflow': ('核对本厂工艺工作包', 'templates'),
    'review': ('完成技术复核', 'drawing'),
    'tasks': ('生成当前版本工序', 'drawing'),
    'publish': ('复核后发布生产版本', 'drawing'),
    'materials': ('处理缺料与暂停', 'readiness'),
    'planning': ('安排生产时间与人员', 'planning'),
    'execution': ('查看现场任务', 'tasks'),
    'delivery': ('验收并安排发货', 'readiness'),
    'closed': ('查看交付记录', 'projects'),
}


_MANUFACTURING_FIELDS = ('name', 'material', 'category', 'quantity', 'unit',
                         'length', 'width', 'thickness', 'finish', 'processes')


def _part_fingerprint(part):
    """Pin the approved manufacturing values, not only the reusable part ID."""
    values = {key: part.get(key) for key in _MANUFACTURING_FIELDS}
    values.update(id=part['id'], document_id=part.get('document_id'),
                  reviewed_at=part.get('reviewed_at'))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def source_resolution_candidates(store, con, doc):
    """Approved parts with an explicit, current lineage to this original.

    A part from an arbitrary BOM in the same project is not evidence. Imported
    parts qualify through a source-SHA-pinned companion; manually entered parts
    qualify only when the source document was chosen at creation and reviewed.
    """
    if (doc.get('superseded') or doc.get('archived')
            or not isinstance(doc.get('id'), str) or not isinstance(doc.get('sha256'), str)
            or not doc['sha256']):
        return []
    documents = {d['id']: d for d in store.all(con, 'documents', doc['project_id'])
                 if d.get('project_id') == doc['project_id'] and not d.get('superseded')
                 and not d.get('archived') and d.get('purpose', 'drawing') == 'drawing'}
    # A viewable PDF and a BOM may be separate exports of one native assembly.
    # They can support each other's manual review only if both were explicitly
    # attached to the same *current* original and exact source hash.
    source_links = {(doc['id'], doc['sha256'])}
    for binding in doc.get('companion_for') or []:
        if not isinstance(binding, dict) or not isinstance(binding.get('document_id'), str) \
                or not isinstance(binding.get('sha256'), str):
            continue
        original = documents.get(binding.get('document_id'))
        if original and original.get('sha256') == binding.get('sha256'):
            source_links.add((original['id'], original['sha256']))
    result = []
    for part in store.active_parts(con, doc['project_id']):
        if not part.get('approved') or part.get('draft_only'):
            continue
        source = documents.get(part.get('document_id'))
        if source is None:
            continue
        part_source = part.get('source') or {}
        if source['id'] == doc['id']:
            if (part_source.get('manual_source_link') is not True
                    or part_source.get('source_document_id') != doc['id']
                    or part_source.get('sha256') != doc['sha256']
                    or not part.get('review_note')):
                continue
        else:
            linked = any(isinstance(binding, dict)
                         and isinstance(binding.get('document_id'), str)
                         and isinstance(binding.get('sha256'), str)
                         and (binding.get('document_id'), binding.get('sha256')) in source_links
                         for binding in source.get('companion_for') or [])
            if not linked or (part_source.get('sha256') and part_source['sha256'] != source.get('sha256')):
                continue
        result.append((part, source))
    return sorted(result, key=lambda pair: pair[0]['id'])


def source_resolution_evidence(doc, candidates):
    return {'schema': 'document-part-lineage-v1', 'document_id': doc['id'],
            'document_sha256': doc['sha256'], 'project_id': doc['project_id'],
            'parts': [{'part_id': part['id'], 'part_fingerprint': _part_fingerprint(part),
                       'source_document_id': source['id'], 'source_sha256': source['sha256']}
                      for part, source in candidates]}


def source_resolution_current(store, con, doc):
    recorded = doc.get('resolution_evidence')
    if not isinstance(recorded, dict) or not isinstance(recorded.get('parts'), list):
        return False
    candidates = source_resolution_candidates(store, con, doc)
    return bool(candidates) and recorded == source_resolution_evidence(doc, candidates)


def release_blockers(store, con, project, part_validator):
    """Exactly the Store.release preconditions, with no writes or approval bypass.

    Keep ordering and wording stable: HTTP release and the assistant consume this
    same function. Open-project authorization remains at the mutation endpoint.
    """
    parts = store.active_parts(con, project['id'])
    tasks = store.active_tasks(con, project['id'])
    blockers = []
    if not parts and not project.get('workflow_id'):
        blockers.append('没有部件')
    if project.get('industry_id') and not project.get('workflow_id'):
        blockers.append('请按本行业流程配置并审核工作包')
    blockers.extend(operations.release_blockers(store, con, project))
    import project_document_flow
    blockers.extend(project_document_flow.blockers(store, con, project))
    approved_construction = project_document_flow.current(store, con, project, 'construction')
    for part in parts:
        blockers.extend(part_validator(part))
        if not part['approved']:
            blockers.append(part['name'] + ' 尚未审核通过')
        step = part.get('source', {}).get('step_proposal')
        if step:
            approved_values = step.get('approved_values') or {}
            if part['source'].get('manufacturing_dimensions_confirmed') is not True \
                    or not step.get('approved_at') \
                    or any(approved_values.get(key) != part.get(key)
                           for key in ('quantity', 'length', 'width', 'thickness')):
                blockers.append(part['name'] + ' 的 STEP 候选数量与加工尺寸尚未完成本版本核验')
    for doc in store.all(con, 'documents', project['id']):
        if doc.get('purpose') == 'process':
            if not doc.get('superseded') and not store.process_basis_verified(con, project, doc):
                blockers.append(doc['filename'] + ' 行业工艺依据待核验，请关联已审核的当前工作包后核验')
            continue
        if doc.get('purpose') == 'render' or doc.get('superseded'):
            continue
        if approved_construction and doc['id'] == approved_construction['id']:
            # Customer-approved construction drawings may contain no extractable
            # BOM; engineering evidence is checked separately below.
            continue
        if doc.get('resolved'):
            if (doc['status'] in ('needs_conversion', 'error') or doc.get('part_count', 0) == 0) \
                    and not source_resolution_current(store, con, doc):
                blockers.append(doc['filename'] + ' 的原件、配套清单或构件核验关联已失效，请重新核对')
            continue
        if doc['status'] in ('needs_conversion', 'error') or doc.get('part_count', 0) == 0:
            blockers.append(doc['filename'] + ' 尚未完成转换/补录核验')
    if not tasks or any(t.get('revision') != project['revision'] or t['status'] == 'invalidated' for t in tasks):
        blockers.append('请按当前版本重新生成工艺任务')
    return blockers


def source_capability(doc):
    suffix = Path(str(doc.get('filename', ''))).suffix.lower()
    if doc.get('purpose') == 'render' or doc.get('source_role') in ('render', 'reference', 'shared_reference') or any(doc.get(k) for k in ('reference_only', 'shared_reference', 'is_reference')):
        return 'appearance', '外观参考', '用于看整体外观；不能作为尺寸、数量或下料依据'
    if doc.get('purpose') == 'process':
        return 'process', '工艺依据', '关联当前工作包后，由负责人核验技术范围与版本'
    if suffix in ('.csv', '.json'):
        return 'bom', '结构化清单', '按文件明示字段读取构件；草稿、尺寸与材质仍须复核'
    if suffix == '.dxf':
        return 'drawing', 'CAD 工程图', '支持带明确构件属性的 ASCII DXF；普通线条不自动等同生产 BOM'
    if suffix in ('.sldasm', '.sldprt', '.slddrw'):
        return 'native_cad', 'SolidWorks 原生文件', '需由 SolidWorks 导出 BOM CSV、工程图 PDF；STEP 可用于几何核对'
    if suffix == '.max':
        return 'appearance_model', '3ds Max 外观模型', '由 3ds Max 导出可查看模型；施工尺寸仍需工程图或生产 BOM'
    if suffix == '.dwg':
        return 'native_cad', 'DWG 工程图', '导出工程图 PDF、带构件属性的 ASCII DXF 或 BOM 后拆解'
    if suffix in ('.step', '.stp'):
        return 'geometry', 'STEP 工程模型', '可用本地 CAD 引擎核对实体几何；材质、加工尺寸及工艺须另行确认'
    if suffix in ('.glb', '.obj', '.stl', '.iges', '.igs', '.brep'):
        return 'geometry', '三维模型', '可查看几何结构；不能仅凭外形推算生产 BOM'
    if suffix in ('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tiff', '.tif', '.bmp'):
        return 'drawing', '施工图待核对', '可查看原图并识别标注文字；关联原图位置后复核尺寸与数量'
    return 'unknown', '待确认文件', '当前格式没有自动构件提取能力，请补充工程图或结构化 BOM'


def source_integrity(store, doc, budget):
    """Bounded file verification inside this factory; never opens caller paths.

    Imported files carry storage_name. Historical external references without a
    registered stored copy remain metadata-only, never reported hash-verified.
    """
    name = doc.get('storage_name')
    if not name:
        return 'recorded_metadata'
    if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
        return 'unavailable'
    try:
        path = engineering_engines._inside(store.uploads / name, store.data_dir)
        if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve():
            return 'unavailable'
        size = path.stat().st_size
        if size > budget[0]:
            return 'not_checked'
        digest = hashlib.sha256()
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            while block := stream.read(min(1024 * 1024, budget[0] + 1)):
                budget[0] -= len(block)
                if budget[0] < 0:
                    return 'not_checked'
                digest.update(block)
        if not doc.get('sha256'):
            return 'digest_missing'
        return 'verified' if digest.hexdigest() == doc['sha256'] else 'changed'
    except (OSError, engineering_engines.EngineeringError):
        return 'unavailable'


def _route(page, project_id):
    return {'page': page, 'projectId': project_id}


def inspect_project(store, con, project):
    """Read the current factory's current project, returning bounded, safe facts."""
    pid = project['id']
    checks = []

    def add(identifier, title, detail, stage, severity='blocker', priority=50, count=1):
        checks.append({'id': identifier, 'title': title, 'detail': detail, 'stage': stage,
                       'severity': severity, 'priority': priority, 'count': count,
                       'route': _route(STAGES[stage][1], pid)})

    try:
        configured = langgraph_agent.model_settings() is not None
        model_reason = ''
    except langgraph_agent.WorkflowError:
        configured, model_reason = False, '本机模型配置无效'
    engine = {'mode': 'deterministic_evidence_check', 'local_only': True,
              'local_model_configured': configured, 'model_verified': False,
              'model_called': False, 'model_reason': model_reason}
    report = {'project_id': pid, 'revision': project['revision'], 'released_revision': project.get('released_revision'),
              'engine': engine, 'checks': checks, 'sources': [], 'source_counts': {}, 'part_counts': {},
              'release_blockers': [], 'release_ready': False, 'release_gate_passed': False,
              'evidence_boundary': '检查已保存的工程依据与复核记录；未对实物和原图全部尺寸重新测量。'}
    if project.get('fulfillment_status') == 'completed' and not project.get('archived'):
        report.update(stage='delivery', next_step={'label': '核对并登记发货',
                      'route': {**_route('readiness', pid), 'opTab': 'deliveries'}},
                      summary='项目已完成，待发货。下一步：核对交付信息并登记发货。')
        return report
    if fulfillment.is_closed(project) or project.get('archived'):
        report.update(stage='closed', next_step={'label': STAGES['closed'][0], 'route': _route('projects', pid)},
                      summary='项目已归档，可查看交付记录。' if project.get('archived') else '项目已发货，可查看交付记录。')
        return report

    validator = part_blockers
    parts = [p for p in store.active_parts(con, pid) if not p.get('demo')]
    tasks = [t for t in store.active_tasks(con, pid) if not t.get('demo')]
    all_docs = {d['id']: d for d in store.all(con, 'documents', pid) if not d.get('demo')}
    docs = [d for d in all_docs.values() if not d.get('superseded') and not d.get('archived')]
    gates = release_blockers(store, con, project, validator)
    report['release_blockers'] = gates
    report['release_gate_passed'] = not gates
    sources = []
    hashes = {}
    unresolved = []
    hash_budget = [64 * 1024 * 1024]
    for doc in docs:
        role, label, ability = source_capability(doc)
        integrity = source_integrity(store, doc, hash_budget) if role != 'appearance' else 'reference_only'
        sources.append({'id': doc['id'], 'filename': str(doc.get('filename', ''))[:240],
                        'role': role, 'role_label': label, 'ability': ability,
                        'revision': doc.get('revision'), 'sha256': doc.get('sha256'),
                        'status': doc.get('status'), 'resolved': bool(doc.get('resolved')),
                        'integrity': integrity, 'route': _route('drawing', pid)})
        if doc.get('sha256') and role != 'appearance':
            hashes.setdefault(doc['sha256'], []).append(doc)
        if role == 'appearance':
            continue
        if integrity in ('unavailable', 'changed'):
            add('integrity_' + doc['id'], '来源文件需要重新上传或核验',
                doc['filename'] + ('：保存文件与校验值不一致' if integrity == 'changed' else '：当前工厂的原文件不可读取'),
                'sources', priority=7)
        elif integrity in ('digest_missing', 'not_checked'):
            add('integrity_' + doc['id'], '来源文件尚未完成校验',
                doc['filename'] + ('：缺少原文件校验值' if integrity == 'digest_missing' else '：本次已达到文件校验量上限，请单独核验此文件'),
                'sources', severity='attention', priority=70)
        if doc.get('purpose') == 'process':
            if not store.process_basis_verified(con, project, doc):
                add('process_' + doc['id'], '工艺依据待核验', doc['filename'], 'workflow', priority=25)
        elif not doc.get('resolved') and (doc.get('status') in ('needs_conversion', 'error') or doc.get('part_count', 0) == 0):
            unresolved.append(doc)
            add('source_' + doc['id'], doc['filename'] + '：尚未完成拆解', ability, 'sources', priority=10)
    report['sources'] = sources[:50]
    report['sources_truncated'] = len(sources) > 50
    report['source_counts'] = {role: sum(s['role'] == role for s in sources) for role in sorted({s['role'] for s in sources})}
    report['source_counts'].update(total=len(sources), unresolved=len(unresolved),
                                   duplicate_groups=sum(len(group) > 1 for group in hashes.values()),
                                   verified=sum(s['integrity'] == 'verified' for s in sources))
    duplicates = [group for group in hashes.values() if len(group) > 1]
    if duplicates:
        add('duplicate_documents', '发现内容相同的来源文件',
            '；'.join(' / '.join(d['filename'] for d in group[:3]) for group in duplicates[:3]) + '。请核对引用关系，避免按文件份数重复计算数量。',
            'sources', severity='attention', priority=70, count=len(duplicates))
    if not sources and not parts and not project.get('workflow_id'):
        add('missing_sources', '先补充生产依据', '上传施工图、SolidWorks 导出的 BOM，或按已确认图纸录入构件。', 'sources', priority=5)
    elif sources and all(s['role'] in ('appearance', 'appearance_model') for s in sources) and not parts and not project.get('workflow_id'):
        add('appearance_only', '当前只有外观资料', '效果图用于确认整体样子；拆任务还需要施工图、明确尺寸清单或 SolidWorks 工程资料。', 'sources', priority=5)

    invalid_parts = []
    pending_parts = []
    trace_issues = []
    critical_sources = []
    for part in parts:
        missing = validator(part)
        if missing:
            invalid_parts.append((part, missing))
        if not part.get('approved'):
            pending_parts.append(part)
        source = part.get('source') or {}
        doc = all_docs.get(part.get('document_id'))
        if part.get('document_id') and (doc is None or doc.get('superseded') or doc.get('archived')):
            trace_issues.append(str(part.get('name', '构件')) + '：来源已换版或缺失')
        elif doc and source.get('sha256') and source['sha256'] != doc.get('sha256'):
            trace_issues.append(str(part.get('name', '构件')) + '：提取依据与当前文件校验值不一致')
        elif doc and source_capability(doc)[0] in ('appearance', 'appearance_model'):
            trace_issues.append(str(part.get('name', '构件')) + '：当前引用外观资料，须补充工程依据')
        for issue in part.get('source_issues', []):
            if '重复' in issue or '示意样本' in issue or ('尺寸单位未明确' in issue and not part.get('unit_confirmed_at')):
                if not part.get('review_note'):
                    critical_sources.append(str(part.get('name', '构件')) + '：' + str(issue))
    if trace_issues:
        add('source_conflicts', '构件来源需要重新核对', '；'.join(trace_issues[:4]), 'sources', priority=8, count=len(trace_issues))
    if invalid_parts:
        add('part_fields', f'{len(invalid_parts)} 个构件需要补齐',
            '；'.join(issue for _, issues in invalid_parts[:3] for issue in issues[:3]), 'parts', priority=30, count=len(invalid_parts))
    if critical_sources:
        add('source_review_notes', '冲突来源缺少复核依据', '；'.join(critical_sources[:3]), 'review', priority=35, count=len(critical_sources))
    if pending_parts:
        add('part_review', f'{len(pending_parts)} 个构件尚未复核',
            '、'.join(str(p.get('name', '构件')) for p in pending_parts[:5]), 'review', priority=40, count=len(pending_parts))
    if not parts and not project.get('workflow_id'):
        add('no_parts', '还没有生产构件', '按工程依据提取或补录构件，再核对材质、尺寸、数量与表面处理。', 'parts', priority=30)
    report['part_counts'] = {'total': len(parts), 'approved': len(parts) - len(pending_parts),
                             'pending': len(pending_parts), 'incomplete': len(invalid_parts),
                             'draft_only': sum(bool(p.get('draft_only')) for p in parts),
                             'source_conflicts': len(trace_issues)}

    workflow_gaps = operations.release_blockers(store, con, project)
    if project.get('industry_id') and not project.get('workflow_id'):
        workflow_gaps.insert(0, '请按本行业流程配置并审核工作包')
    if workflow_gaps:
        add('workflow_gates', '工艺工作包尚未就绪', '；'.join(workflow_gaps[:4]), 'workflow', priority=35, count=len(workflow_gaps))
    if not tasks or any(t.get('revision') != project['revision'] or t.get('status') == 'invalidated' for t in tasks):
        add('task_revision', '工序需要按当前版本生成', f'当前工程版本 R{project["revision"]}；请在资料和构件复核后生成本版任务。', 'tasks', priority=50)
    selection = project_sources.get_sources(store, con, pid)['selection']
    report['main_model'] = selection
    if selection['status'] == 'stale':
        add('main_model_stale', '项目总览模型已失效', selection['reason'], 'sources', severity='attention', priority=75)

    if gates and not any(c['severity'] == 'blocker' for c in checks):
        add('remaining_release_gates', '还有发布前检查项', '；'.join(gates[:4]), 'review', priority=45, count=len(gates))

    # Readiness diagnostics must not be mistaken for permission to release. The
    # exact release gate is exposed separately from evidence attention findings.
    checks.sort(key=lambda c: (c['severity'] != 'blocker', c['priority'], c['id']))
    released = project.get('status') == 'released' and project.get('released_revision') == project['revision']
    if checks and checks[0]['severity'] == 'blocker':
        stage = checks[0]['stage']
    elif not released:
        stage = 'publish'
    else:
        current = [t for t in tasks if t.get('revision') == project['revision'] and t.get('status') != 'invalidated']
        task_ids = {t['id'] for t in current}
        shortages = [m for m in store.all(con, 'materials', pid)
                     if task_ids.intersection(m.get('task_ids', [])) and production.material_view(m)['shortage_quantity'] > 0]
        paused = [t for t in current if t.get('status') == 'blocked']
        if shortages or paused:
            stage = 'materials'
            add('production_holds', '现场有待处理问题', f'缺料记录 {len(shortages)} 项，暂停任务 {len(paused)} 项。',
                'materials', severity='attention', priority=60, count=len(shortages) + len(paused))
        elif current and all(t.get('status') == 'done' for t in current):
            stage = 'delivery'
        elif any(t.get('status') == 'in_progress' for t in current):
            stage = 'execution'
        else:
            stage = 'planning'
    label, page = STAGES[stage]
    route = _route(page, pid)
    if stage == 'delivery':
        route['opTab'] = 'inspections'
    elif stage == 'materials':
        if shortages:
            route['opTab'] = 'materials'
        else:
            label = '处理暂停任务'
            route = {**_route('tasks', pid), 'taskFocus': 'paused'}
    report.update(stage=stage, next_step={'label': label, 'route': route},
                  release_ready=not gates and not any(c['severity'] == 'blocker' for c in checks),
                  check_count=len(checks), checks=checks[:30], checks_truncated=len(checks) > 30,
                  task_counts={'total': len(tasks), 'current': sum(t.get('revision') == project['revision'] and t.get('status') != 'invalidated' for t in tasks)},
                  summary=f'已检查 R{project["revision"]} 的 {len(docs)} 份资料、{len(parts)} 个构件和 {len(tasks)} 道工序。下一步：{label}。')
    return report
