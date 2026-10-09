"""Read-only project workflow facts; stages never approve or execute work.

No engine probes, native imports, file hashing, job recovery or writes run here.
Completeness describes recorded facts, not a permission to manufacture.
"""
from pathlib import Path
import json
import math
import re

import access_control
import engineering_readiness
import operations
import planning
import production
import scheduling
from kanpace.core.errors import APIError
from kanpace.domain.parts import part_blockers


STEPS = (
    ('upload', '上传与版本登记', 'drawing'),
    ('recognition', '识别与结构化', 'drawing'),
    ('attribution', '归属与构件核对', 'drawing'),
    ('geometry', '几何证据核对', 'drawing'),
    ('process', '工种与工艺路线', 'templates'),
    ('material', '物料库存与排料', 'readiness'),
    ('cycle', '周期与关键路径', 'scheduling'),
    ('schedule', '有限资源排程', 'scheduling'),
    ('adopt', '复核与正式采用', 'drawing'),
    ('execution', '执行与追溯', 'tasks'),
)


def _unique(values):
    return list(dict.fromkeys(str(value) for value in values if value))


def _step(identifier, state, completed, total, summary, blockers=(), counts=None, evidence=()):
    _, label, page = next(item for item in STEPS if item[0] == identifier)
    return {'id': identifier, 'stage': identifier, 'label': label, 'state': state,
            'completeness': {'completed': completed, 'total': total},
            'blocked': state == 'blocked', 'needs_review': state == 'needs_review',
            'available': state in ('available', 'needs_review'), 'optional': state == 'optional',
            'counts': counts or {}, 'summary': summary, 'blockers': _unique(blockers),
            'evidence': list(evidence)[:50],
            'next_action': None if state in ('complete', 'optional') else {'label': label, 'page': page}}


def _job_summaries(store, project_id, documents, revision):
    """Only small registered job summaries; do not instantiate native services."""
    rows = []
    for dirname, pattern in (('engineering-jobs', r'eng_[a-f0-9]{32}'),
                             ('recognition-jobs', r'rec_[a-f0-9]{32}')):
        root = store.data_dir / dirname
        if root.is_symlink() or not root.is_dir():
            continue
        for folder in sorted(root.iterdir(), key=lambda path: path.name, reverse=True)[:1000]:
            path = folder / 'job.json'
            if not re.fullmatch(pattern, folder.name) or folder.is_symlink() or path.is_symlink():
                continue
            try:
                if not path.is_file() or path.stat().st_size > 128_000:
                    continue
                row = json.loads(path.read_text())
                metadata = row.get('metadata') or {}
                if metadata.get('project_id') != project_id:
                    continue
                current = str(metadata.get('revision')) == str(revision)
                sources = row.get('sources') or [dict(row.get('source') or {}, document_id=metadata.get('document_id'))]
                for source in sources:
                    doc = documents.get(source.get('document_id'))
                    digest = source.get('source_sha256') or source.get('sha256')
                    if not doc or not digest or digest != doc.get('sha256'):
                        current = False
                rows.append({'id': row.get('id', folder.name), 'kind': row.get('kind'),
                             'status': row.get('status'), 'current': current,
                             'revision': metadata.get('revision'),
                             'document_ids': [s.get('document_id') for s in sources if s.get('document_id')]})
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return rows


def _engine_availability():
    # An executable alone does not prove a working import or solver. Absence is
    # conclusive for this configured process; presence awaits the explicit probe.
    import optimization_engines
    exists = optimization_engines._python().is_file()
    return {'ortools': {'available': None if exists else False, 'probe': 'not_run',
                       'reason': '运行时存在，尚未验证实际求解' if exists else '当前配置的优化运行时不存在'}}


def get(store, con, project_id):
    actor = access_control.get_actor()
    if actor and actor.get('access_enabled') and actor.get('role') in ('worker', 'quality'):
        raise APIError(403, '整单流程分析需要主管、技术员或有整单查看权限的账号')
    project = store.get(con, 'projects', project_id)
    revision = project.get('revision')
    docs = [doc for doc in store.all(con, 'documents', project_id)
            if not doc.get('archived') and not doc.get('superseded')]
    documents = {doc['id']: doc for doc in docs}
    manufacture = [doc for doc in docs if engineering_readiness.source_capability(doc)[0]
                   not in ('appearance', 'appearance_model', 'process')]
    all_parts = store.active_parts(con, project_id)
    parts = [part for part in all_parts if part.get('revision') == revision]
    all_tasks = store.active_tasks(con, project_id)
    tasks = [task for task in all_tasks if task.get('revision') == revision and task.get('status') != 'invalidated']
    job_rows = _job_summaries(store, project_id, documents, revision)
    current_jobs = [job for job in job_rows if job['current']]
    doc_refs = [{'kind': 'document', 'id': doc['id'], 'revision': doc.get('revision'),
                 'source_sha256': doc.get('sha256')} for doc in docs]
    part_refs = [{'kind': 'part', 'id': part['id'], 'revision': part.get('revision')} for part in parts]
    task_refs = [{'kind': 'task', 'id': task['id'], 'revision': task.get('revision'),
                  'execution_version': task.get('execution_version', 0)} for task in tasks]
    states = []
    registered = [doc for doc in docs if doc.get('sha256') and doc.get('storage_name')]
    states.append(_step('upload', 'complete' if docs and len(registered) == len(docs) else 'needs_review' if docs else 'available',
                        len(registered), len(docs), f'当前 {len(docs)} 份资料；版本 R{revision}。',
                        ['部分资料缺少原件或校验值登记'] if len(registered) < len(docs) else [],
                        {'documents': len(docs), 'registered': len(registered)}, doc_refs))
    recognized_ids = {identifier for job in current_jobs if job['status'] == 'completed'
                      for identifier in job['document_ids']}
    recognized = [doc for doc in manufacture if doc.get('part_count', 0) > 0 or doc['id'] in recognized_ids]
    pending_parts = [part for part in parts if not part.get('approved') or part.get('draft_only')]
    failures = [job for job in current_jobs if job['status'] in ('failed', 'partial', 'interrupted')]
    recognition_state = ('blocked' if not manufacture else 'needs_review' if failures or pending_parts or len(recognized) < len(manufacture)
                         else 'complete')
    states.append(_step('recognition', recognition_state, len(recognized), len(manufacture),
                        f'{len(recognized)}/{len(manufacture)} 份生产依据有提取记录；识别不等于批准。',
                        ['尚无生产依据；效果图不能代替制造资料'] if not manufacture else
                        ['存在失败、部分处理或中断的识别任务'] if failures else [],
                        {'documents': len(manufacture), 'recognized': len(recognized), 'jobs': len(current_jobs),
                         'stale_jobs': len(job_rows) - len(current_jobs), 'failed_or_partial': len(failures)}, doc_refs))
    trace_issues, valid_parts = [], []
    field_issues = [issue for part in parts for issue in part_blockers(part)]
    for part in parts:
        source = part.get('source') or {}
        doc = documents.get(part.get('document_id'))
        issue = None
        if part.get('document_id') and doc is None:
            issue = '构件来源已换版或缺失'
        elif doc and source.get('sha256') and source['sha256'] != doc.get('sha256'):
            issue = '构件来源校验值不一致'
        elif doc and engineering_readiness.source_capability(doc)[0] in ('appearance', 'appearance_model'):
            issue = '构件仅引用外观资料，尚无制造依据'
        elif not doc and not source.get('manual_source_link'):
            issue = '构件缺少可追溯的来源关联'
        if issue:
            trace_issues.append(str(part.get('name', '构件')) + '：' + issue)
        elif part.get('approved') and not part_blockers(part):
            valid_parts.append(part)
    attribution_blockers = trace_issues + field_issues
    if len(parts) != len(all_parts):
        attribution_blockers.append('存在旧工程版本构件，须按当前版本重新核对')
    states.append(_step('attribution', 'blocked' if attribution_blockers or not parts else 'needs_review' if pending_parts else 'complete',
                        len(valid_parts), len(parts), f'{len(valid_parts)}/{len(parts)} 个构件有当前来源且已审核。',
                        attribution_blockers or (['尚未建立生产构件'] if not parts else []),
                        {'parts': len(parts), 'approved_current': len(valid_parts), 'pending': len(pending_parts),
                         'stale_parts': len(all_parts) - len(parts)}, part_refs))
    cad_docs = [doc for doc in manufacture if Path(doc.get('filename', '')).suffix.lower() in ('.step', '.stp', '.sldprt', '.sldasm', '.iges', '.igs', '.brep')]
    geometry_reviewed = [doc for doc in cad_docs if doc.get('resolved') and engineering_readiness.source_resolution_current(store, con, doc)]
    cad_completed = sum(job['kind'] == 'cad' and job['status'] == 'completed' for job in current_jobs)
    states.append(_step('geometry', 'optional' if not cad_docs else 'complete' if len(geometry_reviewed) == len(cad_docs) else 'needs_review',
                        len(geometry_reviewed), len(cad_docs), '没有当前CAD来源；二维资料路线可继续。' if not cad_docs else
                        f'{cad_completed} 份当前几何处理记录；{len(geometry_reviewed)} 份已记录构件关联核验。外包框不是加工尺寸。',
                        ['CAD处理结果与制造尺寸仍须人工核验'] if cad_docs and len(geometry_reviewed) < len(cad_docs) else [],
                        {'cad_documents': len(cad_docs), 'completed_jobs': cad_completed, 'reviewed_sources': len(geometry_reviewed)},
                        [ref for ref in doc_refs if ref['id'] in {doc['id'] for doc in cad_docs}]))
    unknown_hours = [task for task in tasks if type(task.get('hours')) not in (int, float)
                     or not math.isfinite(task['hours']) or task['hours'] <= 0]
    route_issues = operations.release_blockers(store, con, project)
    if field_issues or trace_issues or pending_parts:
        route_issues += ['构件尺寸、材料或来源尚未完成本版本复核']
    if not tasks:
        route_issues += ['尚未生成当前版本工序']
    if unknown_hours:
        route_issues += [f'{len(unknown_hours)} 道工序加工工时待确认']
    released = project.get('status') == 'released' and project.get('released_revision') == revision
    states.append(_step('process', 'blocked' if route_issues else 'complete' if released else 'needs_review',
                        len(tasks) - len(unknown_hours), len(tasks), f'当前 {len(tasks)} 道工序；规则匹配不等于具体加工工艺已确认。',
                        route_issues or ([] if released else ['工艺任务须经过本版本复核与发布']),
                        {'tasks': len(tasks), 'known_duration': len(tasks) - len(unknown_hours), 'unknown_duration': len(unknown_hours)}, task_refs))
    task_ids = {task['id'] for task in tasks}
    materials = [material for material in store.all(con, 'materials', project_id) if not material.get('archived')
                 and (not material.get('task_ids') or task_ids.intersection(material['task_ids']))]
    shortages = [material for material in materials if production.material_view(material)['shortage_quantity'] > 0]
    packing = [preview for preview in store.all(con, 'packing_previews', project_id)
               if preview.get('revision') == revision]
    packing_validated = [preview for preview in packing if (preview.get('result') or {}).get('validation', {}).get('valid') is True]
    material_issues = ([f'{len(shortages)} 项物料仍有实际缺口；预计到料不等于齐套'] if shortages else [])
    if field_issues or pending_parts or trace_issues:
        material_issues.append('构件加工尺寸、材料与数量尚未确认，不可据此采用排料')
    # A few accepted material lines cannot establish that the entire BOM was
    # covered, or that a cutting preview has been adopted. No such completion
    # record exists in the legacy schema, so retain an explicit review gate.
    states.append(_step('material', 'blocked' if material_issues else 'needs_review',
                        len(materials) - len(shortages), len(materials),
                        f'{len(materials)} 项物料记录，{len(shortages)} 项缺口；当前版本排料记录 {len(packing)}。',
                        material_issues or (['物料需求与齐套状态尚未登记；没有记录不等于齐套'] if not materials else
                                            ['逐项齐套已登记，仍需核对BOM覆盖、库存预留及排料适用性']),
                        {'materials': len(materials), 'shortages': len(shortages), 'packing_previews': len(packing),
                         'validated_packing_previews': len(packing_validated)}))
    known = len(tasks) - len(unknown_hours)
    cycle_issues = ([f'{len(unknown_hours)} 道工序工时未知；不把历史日历天换算为加工分钟'] if unknown_hours else [])
    if not tasks:
        cycle_issues.append('尚无当前工序与已确认时长')
    states.append(_step('cycle', 'blocked' if cycle_issues else 'available', known, len(tasks),
                        f'{known}/{len(tasks)} 道工序有加工分钟依据；日历周期、加工、等待与占用需分别核对。', cycle_issues,
                        {'known_duration': known, 'unknown_duration': len(unknown_hours)}))
    ctx = scheduling.context(store, con)
    fingerprint = scheduling.fingerprint(ctx)
    plans = [plan for plan in planning.effective_plans(ctx) if plan.get('project_id') == project_id]
    scenarios = [scenario for scenario in store.all(con, 'scheduling_scenarios')
                 if any(row.get('project_id') == project_id for row in scenario.get('rows', [])) or
                 task_ids.intersection((scenario.get('config') or {}).get('task_ids') or [])]
    fresh = [scenario for scenario in scenarios if scenario.get('status') == 'preview' and scenario.get('fingerprint') == fingerprint]
    planned_ids = {plan.get('task_id') for plan in plans}
    planned = len(task_ids & planned_ids)
    schedule_issues = cycle_issues + ([f'{len(tasks) - planned} 道工序尚未有有效采用计划'] if tasks and planned < len(tasks) else [])
    states.append(_step('schedule', 'blocked' if cycle_issues else 'complete' if tasks and planned == len(tasks) else 'needs_review' if fresh else 'available',
                        planned, len(tasks), f'当前 {len(fresh)} 个未过期预览，{planned}/{len(tasks)} 道工序有有效计划；采用不等于开工。',
                        schedule_issues, {'current_previews': len(fresh), 'stale_or_applied_previews': len(scenarios) - len(fresh),
                                          'effective_plans': len(plans), 'planned_tasks': planned}))
    release_issues = engineering_readiness.release_blockers(store, con, project, part_blockers)
    release_issues += trace_issues
    if len(parts) != len(all_parts):
        release_issues.append('存在旧工程版本构件，须先核对当前制造依据')
    states.append(_step('adopt', 'complete' if released and not release_issues else 'blocked' if release_issues else 'available',
                        1 if released and not release_issues else 0, 1,
                        f'当前生产版本 R{revision} 已发布；计划采用仍单独核验。' if released and not release_issues else '本版本尚未满足最终复核与发布门槛。',
                        release_issues, {'released': int(released), 'release_blockers': len(_unique(release_issues))}, task_refs))
    done = sum(task.get('status') == 'done' for task in tasks)
    running = sum(task.get('status') == 'in_progress' for task in tasks)
    paused = sum(task.get('status') == 'blocked' for task in tasks)
    startable, start_issues = 0, []
    for task in tasks:
        if task.get('status') == 'done':
            continue
        issues = store.start_blockers(con, task)
        if task.get('status') == 'blocked':
            issues = issues + ['任务已暂停，须明确处理后恢复']
        if issues:
            start_issues += issues
        else:
            startable += 1
    states.append(_step('execution', 'complete' if tasks and done == len(tasks) else 'available' if startable or running else 'blocked',
                        done, len(tasks), f'{running} 道进行中，{paused} 道暂停，{done}/{len(tasks)} 道完成；发布与排程采用不会自动开工。',
                        start_issues or (['尚无可执行的当前版本任务'] if not tasks else []),
                        {'tasks': len(tasks), 'done': done, 'in_progress': running, 'paused': paused, 'startable': startable}, task_refs))
    for step in states:
        if step['next_action']:
            step['next_action']['project_id'] = project_id
    next_action = next((step['next_action'] for step in states if step['state'] not in ('complete', 'optional')), None)
    return {'schema': 'project-workflow-v1', 'project_id': project_id, 'revision': revision,
            'released_revision': project.get('released_revision'), 'read_only': True,
            'steps': states, 'next_action': next_action, 'engine_status': _engine_availability(),
            'summary': f'按当前工程版本 R{revision} 汇总登记事实；任何阶段状态都不替代原有批准、库存与开工校验。'}
