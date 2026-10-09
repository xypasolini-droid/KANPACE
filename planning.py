"""Explicit daily production reservations; never changes task assignment or progress."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import re
from uuid import uuid4

import fulfillment


class PlanningError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, code='planning_conflict', conflicts=None, status=409):
    raise PlanningError(status, message, {'code': code, 'conflicts': conflicts or []})


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def integer(value, label):
    if type(value) is not int or not 0 <= value <= 2147483647:
        fail(label + '须为有效非负整数', status=400)
    return value


def text(value, label, maximum=2000):
    if not isinstance(value, str) or len(value.strip()) > maximum:
        fail(label + '须为有效文字', status=400)
    return value.strip()


def parse_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        fail('日期格式须为 YYYY-MM-DD', status=400)
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail('日期无效', status=400)


def days_between(start, end):
    first, last = parse_day(start), parse_day(end)
    if not 0 <= (last - first).days < 92:
        fail('日期区间须为 1 至 92 天，结束日期不能早于开始日期', status=400)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def calendar(store, con):
    row = con.execute("SELECT value FROM config WHERE key='planning_calendar'").fetchone()
    return json.loads(row['value']) if row else {'version': 0, 'weekdays': [1, 2, 3, 4, 5], 'daily_capacity_source': 'people'}


def context(store, con):
    return {'projects': {p['id']: p for p in store.all(con, 'projects')},
            'tasks': {t['id']: t for t in store.all(con, 'tasks')},
            'people': {p['id']: p for p in store.all(con, 'people')},
            'plans': store.all(con, 'plans'), 'calendar': calendar(store, con)}


def eligible(task, ctx):
    project = ctx['projects'].get(task.get('project_id'), {}) if task else {}
    return bool(task and project and not project.get('archived') and not fulfillment.is_closed(project)
                and not task.get('archived') and task.get('status') in ('ready', 'blocked', 'in_progress')
                and project.get('status') == 'released' and task.get('revision') == project.get('revision')
                and task.get('revision') == project.get('released_revision'))


def person_issues(task, ctx):
    person = ctx['people'].get(task.get('assignee'))
    project = ctx['projects'].get(task['project_id'], {})
    if not person:
        return ['请先分派负责人']
    issues = []
    if project.get('factory_id') and person.get('factory_id') != project['factory_id']:
        issues.append('负责人不属于项目工厂，请先调整分派')
    if task.get('trade') not in person.get('skills', []):
        issues.append('负责人未具备' + task.get('trade', '') + '技能，请先调整分派')
    if bool(project.get('demo')) != bool(person.get('demo')):
        issues.append('真实订单须使用真实员工，请先建立人员并重新分派' if not project.get('demo') else '演示订单须使用演示人员')
    capacity = person.get('capacity_minutes')
    if type(capacity) not in (int, float) or not math.isfinite(capacity) or not 0 < capacity <= 1440:
        issues.append('负责人每日可用分钟未设置或无效')
    return issues


def plan_issues(plan, ctx):
    task = ctx['tasks'].get(plan.get('task_id'))
    if not eligible(task, ctx):
        return ['任务已完成、项目已关闭或工程版本已失效']
    issues = person_issues(task, ctx)
    if task.get('assignee') != plan.get('person_id'):
        issues.append('任务负责人已变更，请重新保存排程')
    if task.get('revision') != plan.get('task_revision'):
        issues.append('工程版本已变更，请重新排程')
    if any(parse_day(row['date']).isoweekday() not in ctx['calendar']['weekdays'] for row in plan.get('allocations', [])):
        issues.append('工作日历已变更，请重新排程')
    return issues


def effective_plans(ctx):
    return [p for p in ctx['plans'] if p.get('status') == 'scheduled' and not plan_issues(p, ctx)]


def estimate(task):
    hours, quantity, remaining = task.get('hours'), task.get('quantity'), task.get('remaining_quantity')
    values = (hours, quantity, remaining)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
        return None
    return round(hours * 60 * remaining / quantity, 2)


def task_dependencies(task):
    return list(dict.fromkeys(task.get('dependencies', []) + task.get('schedule_dependencies', [])))


def decorate(plan, ctx):
    task = ctx['tasks'].get(plan['task_id'], {})
    project = ctx['projects'].get(plan['project_id'], {})
    person = ctx['people'].get(plan['person_id'], {})
    issues = plan_issues(plan, ctx)
    recorded_material = plan.get('material_status')
    confirmation_expired = (task.get('status') == 'blocked' and task.get('pause_reason') == 'material'
                            and plan.get('task_execution_version', -1) < task.get('execution_version', 0))
    effective_material = 'shortage' if confirmation_expired else recorded_material
    warnings = []
    if confirmation_expired:
        warnings.append('缺少物料，原齐套确认已过期，请重新确认齐套')
    elif effective_material != 'ready':
        warnings.append('物料待确认' if effective_material == 'pending' else '缺少物料')
    if task.get('status') == 'blocked':
        warnings.append('任务已暂停：' + str(task.get('pause_note') or '需确认解除原因'))
    start_blockers = list(issues) + list(warnings)
    start_blockers.extend('排程前序尚未对应任务：' + name for name in task.get('schedule_unmapped_predecessors', []))
    for identifier in task_dependencies(task):
        dep = ctx['tasks'].get(identifier)
        if not dep or dep.get('status') != 'done' or dep.get('archived') or dep.get('revision') != task.get('revision'):
            start_blockers.append('前序工序尚未完成：' + str(dep.get('title') if dep else identifier))
    if any(t['id'] != task.get('id') and eligible(t, ctx) and t.get('status') == 'in_progress'
           and t.get('assignee') == task.get('assignee') for t in ctx['tasks'].values()):
        start_blockers.append('负责人已有执行中任务')
    return dict(plan, task=task, project_name=project.get('name', ''), person_name=person.get('name', ''),
                valid=not issues and plan.get('status') == 'scheduled', issues=issues, warnings=warnings,
                recorded_material_status=recorded_material, effective_material_status=effective_material,
                material_confirmation_expired=confirmation_expired,
                start_blockers=start_blockers, can_start=not start_blockers and task.get('status') == 'ready', demo=bool(project.get('demo')))


def build(store, con, start, end, *, project_id=None, person_id=None, trade=None, include_demo=False):
    window = days_between(start, end)
    ctx = context(store, con)
    if project_id and project_id not in ctx['projects']:
        fail('项目不存在', status=404)
    if person_id and person_id not in ctx['people']:
        fail('负责人不存在', status=404)
    workdays = [d.isoformat() for d in window if d.isoweekday() in ctx['calendar']['weekdays']]
    def visible(task):
        p = ctx['projects'].get(task.get('project_id'), {})
        return (eligible(task, ctx) and (include_demo or not p.get('demo')) and
                (not project_id or task['project_id'] == project_id) and
                (not person_id or task.get('assignee') == person_id) and (not trade or task.get('trade') == trade))
    active = effective_plans(ctx)
    scheduled = {p['task_id'] for p in active}
    plans = [decorate(p, ctx) for p in ctx['plans'] if p.get('status') == 'scheduled'
             and p['start_date'] <= end and p['end_date'] >= start and visible(ctx['tasks'].get(p['task_id'], {}))]
    unplanned = []
    for task in ctx['tasks'].values():
        if visible(task) and task['id'] not in scheduled:
            previous = next((p for p in ctx['plans'] if p['task_id'] == task['id'] and p['status'] == 'scheduled'), None)
            person = ctx['people'].get(task.get('assignee'), {})
            demo_assignee = bool(person.get('demo')) and not ctx['projects'][task['project_id']].get('demo')
            unplanned.append(dict(task, project_name=ctx['projects'][task['project_id']]['name'],
                                  person_name='' if demo_assignee else person.get('name', ''), assignee_is_demo=demo_assignee,
                                  estimated_remaining_minutes=estimate(task), remaining_minutes=estimate(task), schedule_blockers=person_issues(task, ctx),
                                  existing_plan_id=previous['id'] if previous else None))
    people = [p for p in ctx['people'].values() if (include_demo or not p.get('demo')) and
              (not person_id or p['id'] == person_id) and (not trade or trade in p.get('skills', []))]
    usage = {}
    for plan in active:
        for row in plan['allocations']:
            key = (plan['person_id'], row['date'])
            usage[key] = round(usage.get(key, 0) + row['minutes'], 2)
    capacity = []
    for person in people:
        for day in workdays:
            used = usage.get((person['id'], day), 0)
            available = person.get('capacity_minutes')
            known = type(available) in (int, float) and math.isfinite(available) and 0 < available <= 1440
            capacity.append({'person_id': person['id'], 'person_name': person['name'], 'date': day,
                             'capacity_minutes': available if known else None, 'planned_minutes': used, 'minutes': used,
                             'remaining_minutes': round(available - used, 2) if known else None,
                             'capacity_unknown': not known, 'over_capacity': known and used > available})
    not_ready = [p for p in ctx['projects'].values() if not fulfillment.is_closed(p) and not p.get('archived')
                 and (include_demo or not p.get('demo')) and (not project_id or p['id'] == project_id)
                 and (p.get('status') != 'released' or not any(eligible(t, ctx) for t in ctx['tasks'].values() if t['project_id'] == p['id']))]
    return {'start': start, 'end': end, 'workdays': workdays, 'calendar': ctx['calendar'],
            'plans': sorted(plans, key=lambda p: (p['start_date'], -p['task'].get('priority', 0), p['task'].get('schedule_position', 0), p['id'])),
            'unscheduled_tasks': sorted(unplanned, key=lambda t: (-t.get('priority', 0), t.get('schedule_position', 0), t['id'])),
            'not_ready_projects': not_ready, 'people': people, 'capacity': capacity,
            'summary': {'planned_tasks': len(plans), 'unscheduled_tasks': len(unplanned),
                        'material_risks': sum(p['effective_material_status'] != 'ready' for p in plans),
                        'paused_tasks': sum(p['task'].get('status') == 'blocked' for p in plans),
                        'over_capacity_days': sum(row['over_capacity'] for row in capacity)}}


def get_plan(store, con, identifier):
    return {'plan': decorate(store.get(con, 'plans', identifier), context(store, con))}


def save(store, con, data, *, replacing_plan_ids=None):
    allowed = {'id', 'expected_version', 'expected_task_version', 'task_id', 'start_date', 'end_date',
               'planned_minutes', 'minutes_source', 'material_status', 'note'}
    if set(data) - allowed:
        fail('排程含未知字段，负责人请在任务分派中调整', status=400)
    ctx = context(store, con)
    task_id = text(data.get('task_id'), '任务标识', 128)
    task = ctx['tasks'].get(task_id)
    if not eligible(task, ctx):
        fail('仅开放项目的已发布有效未完工任务可以排程', 'task_not_schedulable')
    expected_task = integer(data.get('expected_task_version'), '任务执行版本')
    if expected_task != task['execution_version']:
        fail('任务已更新，请刷新后重新排程', 'task_version_conflict')
    issues = person_issues(task, ctx)
    if issues:
        fail('；'.join(issues), 'assignee_not_ready', issues)
    previous = None
    if data.get('id'):
        previous = store.get(con, 'plans', text(data['id'], '排程标识', 128))
        if previous['task_id'] != task_id or previous.get('status') != 'scheduled':
            fail('排程不属于该任务或已取消，请刷新后重排', 'plan_inactive')
        if integer(data.get('expected_version'), '排程版本') != previous['version']:
            fail('排程已被其他操作更新，请刷新后再保存', 'plan_version_conflict')
    elif any(p['task_id'] == task_id and p.get('status') == 'scheduled' for p in ctx['plans']):
        fail('该任务已有排程，请修改现有排程', 'already_planned')
    elif 'expected_version' in data and integer(data['expected_version'], '排程版本') != 0:
        fail('新排程的版本须为 0', status=400)
    if previous and previous.get('scenario_id'):
        # Minute reservations and downstream waiting must survive a material
        # confirmation in the existing day-grid editor.
        unchanged = all(data.get(k, previous[k]) == previous[k] for k in ('start_date', 'end_date', 'planned_minutes'))
        if not unchanged or previous['person_id'] != task.get('assignee') or plan_issues(previous, ctx):
            fail('此排程来自产能模拟；调整时间或资源请先取消，再重新模拟', 'scenario_plan_immutable')
        material = data.get('material_status')
        if material not in ('ready', 'pending', 'shortage'):
            fail('请选择有效物料状态', status=400)
        note = text(data.get('note', ''), '齐套核对依据')
        if not note:
            fail('请填写齐套核对依据', status=400)
        previous.update(material_status=material, note=note, task_execution_version=task['execution_version'],
                        version=previous['version'] + 1, updated_at=stamp())
        store.put(con, 'plans', previous)
        store.event(con, task['project_id'], 'plan_material_checked', '核对排产齐套：' + task['title'], plan_id=previous['id'])
        return {'plan': decorate(previous, context(store, con))}
    start, end = data.get('start_date'), data.get('end_date')
    days = days_between(start, end)
    working = [day for day in days if day.isoweekday() in ctx['calendar']['weekdays']]
    if not working or working[0] != days[0] or working[-1] != days[-1]:
        fail('计划起止日期须为工作日，请检查工作日历', status=400)
    source = data.get('minutes_source', 'manual')
    if source not in ('manual', 'task_estimate'):
        fail('工时来源须为 manual 或 task_estimate', status=400)
    minutes = estimate(task) if source == 'task_estimate' else data.get('planned_minutes')
    if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 0 < minutes <= 1000000:
        fail('缺少有效计划工时，请填写人工计划分钟；未知工时不能按零安排', status=400)
    cents = int((Decimal(str(minutes)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if cents < len(working):
        fail('计划工时不足以分配到所选工作日', status=400)
    quotient, remainder = divmod(cents, len(working))
    allocations = [{'date': day.isoformat(), 'minutes': (quotient + (index < remainder)) / 100}
                   for index, day in enumerate(working)]
    material = data.get('material_status')
    if material not in ('ready', 'pending', 'shortage'):
        fail('请选择物料状态：ready、pending 或 shortage', status=400)
    note = text(data.get('note', ''), '排程备注')
    if previous and not note:
        fail('修改排程请填写调整依据', status=400)
    if material == 'shortage' and not note:
        fail('缺料时请填写缺少的物料或处理安排', status=400)
    # A reviewed multi-task reschedule validates its final graph atomically.
    # The private caller temporarily excludes only its not-yet-replaced old
    # reservations; each saved replacement immediately re-enters capacity checks.
    active = [p for p in effective_plans(ctx) if (not previous or p['id'] != previous['id'])
              and p['id'] not in (replacing_plan_ids or set())]
    by_task = {p['task_id']: p for p in active}
    dependency_conflicts = []
    for dep_id in task_dependencies(task):
        dep = ctx['tasks'].get(dep_id)
        if not dep or dep.get('archived') or dep.get('revision') != task['revision'] or dep.get('project_id') != task['project_id']:
            dependency_conflicts.append({'task_id': dep_id, 'message': '前序工序不存在、跨项目或版本已失效'})
            continue
        if dep and dep.get('status') == 'done' and not dep.get('archived') and dep.get('revision') == task['revision'] and dep.get('project_id') == task['project_id']:
            continue
        predecessor = by_task.get(dep_id)
        if not predecessor:
            dependency_conflicts.append({'task_id': dep_id, 'message': '前序工序尚未完成且没有有效排程：' + str(dep.get('title') if dep else dep_id)})
        elif predecessor['end_date'] >= start:
            dependency_conflicts.append({'task_id': dep_id, 'plan_id': predecessor['id'], 'end_date': predecessor['end_date'], 'message': '须安排在前序工序计划结束后的工作日：' + dep['title']})
    for successor in active:
        later = ctx['tasks'][successor['task_id']]
        if task_id in task_dependencies(later) and end >= successor['start_date']:
            dependency_conflicts.append({'task_id': later['id'], 'plan_id': successor['id'], 'start_date': successor['start_date'], 'message': '后续工序已安排，请先调整后序日期：' + later['title']})
    if dependency_conflicts:
        fail('工序前后顺序冲突，请先调整相关排程', 'dependency_conflict', dependency_conflicts)
    person = ctx['people'][task['assignee']]
    capacity_conflicts = []
    for allocation in allocations:
        occupied = [p for p in active if p['person_id'] == person['id'] and any(a['date'] == allocation['date'] for a in p['allocations'])]
        used = round(sum(a['minutes'] for p in occupied for a in p['allocations'] if a['date'] == allocation['date']), 2)
        if used + allocation['minutes'] > person['capacity_minutes'] + 0.000001:
            capacity_conflicts.append({'date': allocation['date'], 'person_id': person['id'], 'person_name': person['name'],
                'capacity_minutes': person['capacity_minutes'], 'used_minutes': used, 'requested_minutes': allocation['minutes'],
                'plan_ids': [p['id'] for p in occupied], 'message': f"{person['name']} {allocation['date']} 可用 {person['capacity_minutes']} 分钟，已排 {used} 分钟，本次需 {allocation['minutes']} 分钟"})
    if capacity_conflicts:
        fail('；'.join(row['message'] for row in capacity_conflicts), 'capacity_conflict', capacity_conflicts)
    value = {'id': previous['id'] if previous else 'plan_' + uuid4().hex[:12], 'task_id': task_id,
             'project_id': task['project_id'], 'task_revision': task['revision'], 'person_id': task['assignee'],
             'task_execution_version': task['execution_version'], 'start_date': start, 'end_date': end,
             'planned_minutes': cents / 100, 'minutes_source': source, 'material_status': material, 'note': note,
             'allocations': allocations, 'status': 'scheduled', 'version': previous['version'] + 1 if previous else 1,
             'created_at': previous['created_at'] if previous else stamp(), 'updated_at': stamp()}
    store.put(con, 'plans', value)
    store.event(con, task['project_id'], 'plan_updated' if previous else 'plan_created', '保存生产排程：' + task['title'],
                plan_id=value['id'], task_id=task_id, previous=previous, plan=value)
    return {'plan': decorate(value, ctx)}


def cancel(store, con, identifier, data):
    if set(data) - {'expected_version', 'note'}:
        fail('取消排程含未知字段', status=400)
    ctx = context(store, con)
    plan = store.get(con, 'plans', identifier)
    if integer(data.get('expected_version'), '排程版本') != plan['version']:
        fail('排程已更新，请刷新后再取消', 'plan_version_conflict')
    if plan.get('status') == 'cancelled':
        return {'plan': decorate(plan, ctx), 'unchanged': True}
    task = ctx['tasks'].get(plan['task_id'])
    project = ctx['projects'].get(plan['project_id'])
    store.require_project_open(project)
    if task and task.get('status') == 'done':
        fail('已完工任务排程保留为历史记录，不能取消', 'task_not_schedulable')
    successors = [p for p in effective_plans(ctx) if plan['task_id'] in task_dependencies(ctx['tasks'][p['task_id']])]
    if successors:
        fail('存在依赖该工序的后续排程，请先调整或取消后序', 'dependency_conflict',
             [{'plan_id': p['id'], 'task_id': p['task_id'], 'message': ctx['tasks'][p['task_id']]['title']} for p in successors])
    note = text(data.get('note', ''), '取消说明')
    if not note:
        fail('取消排程请填写原因', status=400)
    old = dict(plan)
    plan.update(status='cancelled', version=plan['version'] + 1, updated_at=stamp(),
                cancelled_at=stamp(), cancel_note=note)
    store.put(con, 'plans', plan)
    store.event(con, plan['project_id'], 'plan_cancelled', '取消生产排程：' + (task.get('title', '') if task else ''),
                plan_id=identifier, task_id=plan['task_id'], previous=old, note=plan['cancel_note'])
    return {'plan': decorate(plan, ctx), 'unchanged': False}


def save_calendar(store, con, data):
    if set(data) - {'weekdays', 'expected_version'}:
        fail('工作日历含未知字段', status=400)
    days = data.get('weekdays')
    if not isinstance(days, list) or not days or len(days) > 7 or any(type(d) is not int or not 1 <= d <= 7 for d in days) or len(set(days)) != len(days):
        fail('工作日须为 1（周一）至 7（周日）的不重复整数列表', status=400)
    ctx = context(store, con)
    current = ctx['calendar']
    if integer(data.get('expected_version'), '日历版本') != current['version']:
        fail('工作日历已更新，请刷新后重试', 'calendar_version_conflict')
    if sorted(days) == current['weekdays']:
        return {'calendar': current, 'unchanged': True}
    if any(p.get('status') == 'scheduled' and eligible(ctx['tasks'].get(p['task_id']), ctx) for p in ctx['plans']):
        fail('已有活动排程，请先取消相关排程再修改工作周', 'calendar_in_use')
    value = {'version': current['version'] + 1, 'weekdays': sorted(days), 'daily_capacity_source': 'people'}
    con.execute("INSERT INTO config(key,value) VALUES('planning_calendar',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))
    store.event(con, None, 'planning_calendar_updated', '调整生产工作周', previous=current, calendar=value)
    return {'calendar': value, 'unchanged': False}


def material_blockers(store, con, task):
    if not any(p.get('task_id') == task['id'] and p.get('status') == 'scheduled' for p in store.all(con, 'plans')):
        return []
    ctx = context(store, con)
    plan = next((p for p in effective_plans(ctx) if p['task_id'] == task['id']), None)
    if (plan and task.get('status') == 'blocked' and task.get('pause_reason') == 'material'
            and plan.get('task_execution_version', -1) < task.get('execution_version', 0)):
        return ['任务报告缺料，原齐套确认已过期，请在排程中重新确认齐套后恢复']
    if plan and plan.get('material_status') != 'ready':
        return [('排程物料待确认' if plan.get('material_status') == 'pending' else '排程物料短缺') + ('：' + plan['note'] if plan.get('note') else '')]
    return []


def reorder(store, con, data):
    """Table priority/order affects dispatch order, never rewrites allocations."""
    if set(data) - {'task_id', 'expected_task_version', 'priority', 'position'}:
        fail('排程顺序含未知字段', status=400)
    ctx = context(store, con)
    task = ctx['tasks'].get(text(data.get('task_id'), '任务标识', 128))
    if not eligible(task, ctx):
        fail('已完成、已发货或未发布的任务不能插单', 'task_not_schedulable')
    if integer(data.get('expected_task_version'), '任务执行版本') != task['execution_version']:
        fail('任务已更新，请刷新后调整顺序', 'task_version_conflict')
    priority, position = integer(data.get('priority'), '优先级'), integer(data.get('position'), '表内顺序')
    if priority > 3 or position > 1000000:
        fail('优先级须为0至3，顺序须为0至1000000', status=400)
    old = {'priority': task['priority'], 'position': task.get('schedule_position', 0)}
    if old == {'priority': priority, 'position': position}:
        return {'task': task, 'unchanged': True}
    task.update(priority=priority, schedule_position=position)
    task = store.save_execution(con, task, 'task_priority', '在生产排程表调整顺序', previous=old, priority=priority, position=position)
    return {'task': task, 'unchanged': False}
