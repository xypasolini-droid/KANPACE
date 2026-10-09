"""Read-only manufacturing analytics from saved tasks and audit events.

Current production and historical completion events intentionally have separate
scopes. Planned workload is never presented as actual hours or efficiency.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import math
import fulfillment

STATUSES = ('ready', 'in_progress', 'blocked', 'done')
PAUSE_LABELS = {'material': '缺材料', 'quality': '质量问题', 'equipment': '设备问题',
                'urgent': '急单插队', 'other': '其他原因', 'unknown': '未分类/未记录'}


def finite(value, positive=False):
    return (type(value) in (int, float) and 0 <= value <= 1e12
            and math.isfinite(value) and (not positive or value > 0))


def ratio(a, b):
    return round(a / b, 4) if b else None


def progress_known(task):
    total, done = task.get('quantity'), task.get('completed_quantity')
    return (task.get('progress_recorded') is True and finite(total, True)
            and finite(done) and total == int(total) and done == int(done) and done <= total)


def workload(tasks):
    known = 0.0
    unknown = unrecorded = 0
    for task in tasks:
        recorded = progress_known(task)
        unrecorded += not recorded
        hours = task.get('hours')
        if not finite(hours):
            unknown += 1
            continue
        known += hours * ((task['quantity'] - task['completed_quantity']) / task['quantity'] if recorded else 1)
    return {'remaining_planned_hours': round(known, 3) if not unknown else None,
            'known_remaining_planned_hours': round(known, 3),
            'unknown_estimate_tasks': unknown, 'unrecorded_progress_tasks': unrecorded}


def counts(tasks):
    c = Counter(t.get('status') for t in tasks)
    return {'total': len(tasks), **{s: c[s] for s in STATUSES}}


def parse_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def build_analytics(state, *, project_id=None, trade=None, days=14, as_of=None, fulfillment_status=None):
    current = as_of or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    today = current.date()
    all_projects = {p['id']: p for p in state.get('projects', [])}
    def lifecycle_match(project):
        status = project.get('fulfillment_status', 'active')
        return not fulfillment_status or fulfillment_status == 'all' or (fulfillment_status == 'closed' and status in fulfillment.CLOSED) or status == fulfillment_status
    projects = {p['id']: p for p in state.get('projects', []) if not p.get('archived') and lifecycle_match(p)}
    all_tasks = {t['id']: t for t in state.get('tasks', [])}
    people = {p['id']: p for p in state.get('people', [])}
    selected_projects = {key: p for key, p in projects.items() if not project_id or key == project_id}
    current_tasks = [t for t in all_tasks.values() if t.get('project_id') in selected_projects
                     and not fulfillment.is_closed(selected_projects[t['project_id']])
                     and not t.get('archived') and t.get('status') in STATUSES
                     and selected_projects[t['project_id']].get('status') == 'released'
                     and t.get('revision') == selected_projects[t['project_id']].get('revision')
                     and t.get('revision') == selected_projects[t['project_id']].get('released_revision')
                     and (not trade or t.get('trade') == trade)]
    closed_projects = {pid: p for pid, p in selected_projects.items() if fulfillment.is_closed(p)}
    closed_tasks = [t for t in all_tasks.values() if t.get('project_id') in closed_projects and (not trade or t.get('trade') == trade)]
    if trade:
        closed_project_ids = {t['project_id'] for t in closed_tasks}
        closed_projects = {pid: p for pid, p in closed_projects.items() if pid in closed_project_ids}
    production_ids = {t['project_id'] for t in current_tasks}
    if trade:
        selected_projects = {key: p for key, p in selected_projects.items() if key in production_ids or key in closed_projects}
    pending = [t for t in current_tasks if t['status'] != 'done']
    blockers = {'paused': [], 'dependencies': [], 'unassigned': [], 'skill_mismatch': []}
    for task in pending:
        tid = task['id']
        if task['status'] == 'blocked':
            blockers['paused'].append({'task_id': tid, 'reason': task.get('pause_reason') or 'unknown'})
        deps = [key for key in task.get('dependencies', []) if key not in all_tasks
                or all_tasks[key].get('status') != 'done' or all_tasks[key].get('archived')
                or all_tasks[key].get('revision') != task.get('revision')
                or all_tasks[key].get('project_id') != task.get('project_id')]
        if deps:
            blockers['dependencies'].append({'task_id': tid, 'pending_task_ids': deps})
        person = people.get(task.get('assignee'))
        if not person:
            blockers['unassigned'].append({'task_id': tid, 'reason': '负责人未分派或人员记录缺失'})
        elif task.get('trade') not in person.get('skills', []):
            blockers['skill_mismatch'].append({'task_id': tid, 'person_id': person['id']})
    blocked_ids = {row['task_id'] for items in blockers.values() for row in items}
    blockers['unique_task_count'] = len(blocked_ids)
    assigned_blocked = {r['task_id'] for r in blockers['unassigned'] + blockers['skill_mismatch']}
    project_rows = []
    for pid in sorted(production_ids, key=lambda key: (projects[key].get('due_date') or '9999', key)):
        project = projects[pid]
        tasks = [t for t in current_tasks if t['project_id'] == pid]
        c = counts(tasks)
        due = parse_date(project.get('due_date'))
        delta = (due - today).days if due else None
        unfinished = c['total'] - c['done']
        reasons = []
        if unfinished and due and delta < 0:
            reasons.append('已过交期且当前范围仍有未完工工序')
        if c['blocked']:
            reasons.append(str(c['blocked']) + ' 项暂停待恢复')
        if any(t['id'] in assigned_blocked for t in tasks):
            reasons.append('存在未分派人员或技能不匹配任务')
        if not due:
            reasons.append('交期未记录或日期无效')
        if not unfinished:
            risk = 'completed'
        elif due and delta < 0:
            risk = 'overdue'
        elif c['blocked']:
            risk = 'paused'
        elif any(t['id'] in assigned_blocked for t in tasks):
            risk = 'needs_assignment'
        elif due and delta <= 3:
            risk = 'due_soon'
            reasons.append('距交期不超过 3 天；此提示不预测能否按时交付')
        else:
            risk = 'no_known_blocker' if due else 'unknown_due'
        project_rows.append({'id': pid, 'name': project.get('name', ''), 'due_date': due.isoformat() if due else None,
                             'days_to_due': delta, **c, 'completion_ratio': ratio(c['done'], c['total']),
                             'risk': risk, 'risk_reasons': reasons, 'task_ids': [t['id'] for t in tasks],
                             'demo': bool(project.get('demo')), 'fulfillment_status': project.get('fulfillment_status', 'active'), 'project_closed': False})
    trade_rows = []
    for name in sorted({t.get('trade') or '未记录工种' for t in current_tasks}):
        tasks = [t for t in current_tasks if (t.get('trade') or '未记录工种') == name]
        trade_rows.append({'trade': name, **counts(tasks), 'task_ids': [t['id'] for t in tasks]})
    pause_rows = []
    for reason, label in PAUSE_LABELS.items():
        tasks = [t for t in pending if t['status'] == 'blocked'
                 and (t.get('pause_reason') if t.get('pause_reason') in PAUSE_LABELS else 'unknown') == reason]
        pause_rows.append({'reason': reason, 'label': label, 'count': len(tasks), 'task_ids': [t['id'] for t in tasks]})
    person_ids = {t.get('assignee') for t in pending}
    person_ids |= {key for key, person in people.items() if not trade or trade in person.get('skills', [])}
    people_rows = []
    for person_id in sorted(person_ids, key=lambda key: (key is None, key or '')):
        tasks = [t for t in pending if t.get('assignee') == person_id]
        person = people.get(person_id)
        people_rows.append({'person_id': person_id, 'name': person.get('name', '') if person else ('未分派' if person_id is None else '人员记录缺失'),
                            'task_count': len(tasks), **workload(tasks), 'task_ids': [t['id'] for t in tasks]})
    first_day = today - timedelta(days=days - 1)
    trend = {(first_day + timedelta(days=i)).isoformat(): [] for i in range(days)}
    first_completions = {}
    unknown_event_dates = 0
    for event in state.get('events', []):
        details = event.get('details') or {}
        if event.get('action') != 'task_status' or not (details.get('status') == 'done' or (details.get('status') is None and str(event.get('message', '')).endswith(' → done'))):
            continue
        tid = details.get('task_id')
        task = all_tasks.get(tid)
        if not task or not lifecycle_match(all_projects.get(task.get('project_id'), {})) or (project_id and task.get('project_id') != project_id) or (trade and task.get('trade') != trade):
            continue
        try:
            timestamp = event.get('created_at')
            if not isinstance(timestamp, str):
                raise ValueError('Missing event timestamp')
            date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if date.tzinfo is None:
                raise ValueError('Unknown event timezone')
            # The system zone must be resolved for the event date as well, so
            # a range spanning a daylight-saving change uses local midnight.
            date = date.astimezone(current.tzinfo if as_of is not None else None)
        except (KeyError, ValueError, TypeError):
            unknown_event_dates += 1
            continue
        if tid not in first_completions or date < first_completions[tid]:
            first_completions[tid] = date
    for tid, date in first_completions.items():
        if date.date().isoformat() in trend and date <= current:
            trend[date.date().isoformat()].append(tid)
    c = counts(current_tasks)
    recorded = sum(progress_known(t) for t in current_tasks)
    load = workload(pending)
    closed_rows = []
    for pid, project in closed_projects.items():
        history_tasks = [t for t in closed_tasks if t['project_id'] == pid and not t.get('archived')]
        row = {key: project.get(key) for key in ('id', 'name', 'client', 'due_date', 'completed_at', 'shipped_at', 'closed_at')}
        row.update(fulfillment_status=project.get('fulfillment_status'), fulfillment_label=fulfillment.LABELS.get(project.get('fulfillment_status')), project_closed=True,
                   **counts(history_tasks), task_ids=[t['id'] for t in history_tasks], unfinished_preserved=sum(t.get('status') not in ('done', 'invalidated') for t in history_tasks), demo=bool(project.get('demo')))
        closed_rows.append(row)
    summary = {'project_total': len(selected_projects),
               'active_project_total': sum(not fulfillment.is_closed(p) for p in selected_projects.values()),
               'closed_project_total': len(closed_projects),
               'completed_project_total': sum(p.get('fulfillment_status') == 'completed' for p in closed_projects.values()),
               'shipped_project_total': sum(p.get('fulfillment_status') == 'shipped' for p in closed_projects.values()), 'production_project_total': len(production_ids),
               'in_production_projects': sum(p['done'] < p['total'] for p in project_rows),
               'overdue_projects': sum(p['risk'] == 'overdue' for p in project_rows),
               'task_total': c['total'], **{s: c[s] for s in STATUSES},
               'completion_ratio': ratio(c['done'], c['total']), **load,
               'unrecorded_progress_tasks': len(current_tasks) - recorded}
    task_index = {}
    current_ids = {t['id'] for t in current_tasks}
    trend_ids = {tid for ids in trend.values() for tid in ids}
    project_lookup = {p['id']: p for p in state.get('projects', [])}
    indexed_tasks = {t['id']: t for t in current_tasks + closed_tasks + [all_tasks[tid] for tid in sorted(trend_ids - current_ids)]}
    for task in indexed_tasks.values():
        record = progress_known(task)
        task_index[task['id']] = {key: task.get(key) for key in ('id', 'title', 'trade', 'status', 'project_id', 'assignee', 'priority', 'quantity', 'pause_reason', 'handover_note')}
        task_index[task['id']].update(project_name=project_lookup.get(task['project_id'], {}).get('name', '项目记录缺失'), progress_recorded=record,
                                     assignee_name=people.get(task.get('assignee'), {}).get('name', '未分派' if not task.get('assignee') else '人员记录缺失'),
                                     completed_quantity=task.get('completed_quantity') if record else None,
                                     remaining_quantity=task['quantity'] - task['completed_quantity'] if record else None,
                                     archived=bool(task.get('archived')), historical=task['id'] not in current_ids,
                                     project_closed=fulfillment.is_closed(project_lookup.get(task.get('project_id'), {})),
                                     fulfillment_status=project_lookup.get(task.get('project_id'), {}).get('fulfillment_status', 'active'),
                                     demo=bool(project_lookup.get(task['project_id'], {}).get('demo')))
    return {'as_of': current.isoformat(), 'filters': {'project_id': project_id, 'trade': trade, 'days': days, 'fulfillment_status': fulfillment_status or 'all'},
            'scope': {'current': '仅未关闭项目的当前已发布版本、未归档生产任务；已完成/已发货项目不计待办与负载，历史仍保留',
                      'projects': '无工种筛选时项目总数包含所有阶段；有工种筛选时仅含该工种当前生产任务涉及项目',
                      'project_completion': '按当前筛选范围的工序数计算完成比例，不是产品完成数量或整单交付率',
                      'workload': '剩余计划工时；已知累计整件进度按剩余比例折算，旧未记录按原完整工时估算；未知工时不补零',
                      'timezone': str(current.tzinfo), 'date': today.isoformat(),
                      'demo_tasks': sum(bool(projects[t['project_id']].get('demo')) for t in current_tasks),
                      'not_available': ['真实库存', '采购到货', '财务收入利润', '实际工时效率', 'OEE', '准交率']},
            'summary': summary, 'trade_status': trade_rows, 'pause_reasons': pause_rows,
            'people': people_rows, 'projects': project_rows, 'closed_projects': closed_rows,
            'closed_task_ids': [t['id'] for t in closed_tasks],
            'completion_trend': {'days': [{'date': date, 'completed_operations': len(ids), 'task_ids': sorted(ids)} for date, ids in trend.items()],
                                 'total': sum(map(len, trend.values())), 'includes_archived': True,
                                 'unknown_date_events': unknown_event_dates,
                                 'definition': '按工序首次完工审计事件日期去重，含历史已归档版本；版本承接不重复计数，不是产品产量或设备回执'},
            'progress_coverage': {'recorded': recorded, 'total': c['total'], 'ratio': ratio(recorded, c['total']),
                                  'definition': '明确初始化或累计报工记录覆盖率，不等于实际报工率'},
            'blockers': blockers, 'task_index': task_index}
