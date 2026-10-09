"""Finite-capacity, minute-resolution what-if scheduling with explicit commit.

Existing daily plans are frozen. Their occupied portion is conservatively at
the start of each workday. New tasks require simultaneous person/workcenter
availability. Waiting releases both resources. This is a dispatch heuristic,
not an optimal APS solver; unknown duration/dependency data stays unplaced.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math

import operations
import planning
import production as p
import fulfillment

SchedulingError = p.ProductionError


def context(store, con):
    return {'projects': {x['id']: x for x in store.all(con, 'projects')},
            'tasks': {x['id']: x for x in store.all(con, 'tasks')},
            'people': {x['id']: x for x in store.all(con, 'people')},
            'workcenters': {x['id']: x for x in store.all(con, 'workcenters')},
            'plans': store.all(con, 'plans'), 'calendar': planning.calendar(store, con),
            'materials': store.all(con, 'materials'), 'issues': store.all(con, 'issues'),
            'checks': store.all(con, 'entry_checks')}


def fingerprint(ctx):
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def eligible(t, ctx, typ=None, demo=False):
    project = ctx['projects'].get(t.get('project_id'), {})
    return planning.eligible(t, ctx) and (demo or not project.get('demo')) and (not typ or project.get('factory_type', 'cabinet') == typ)


def iso(value):
    return value.isoformat(timespec='minutes')


def request(data):
    start = p.day(data.get('start_date'), '模拟开始日期', True)
    horizon = data.get('horizon_days', 30)
    if type(horizon) is not int or not 1 <= horizon <= 180:
        p.fail('模拟范围须为 1–180 天')
    typ = data.get('factory_type', 'cabinet')
    if typ not in operations.FACTORY_TYPES:
        p.fail('请选择有效工厂类型')
    ids, rush = data.get('task_ids', []), data.get('rush_task_ids', [])
    if any(not isinstance(value, list) or len(value) > 300 or any(not isinstance(x, str) for x in value) for value in (ids, rush)):
        p.fail('任务列表无效或超过 300 项')
    overrides = data.get('overrides', [])
    if not isinstance(overrides, list) or len(overrides) > 300:
        p.fail('工时参数列表无效')
    rows = []
    for value in overrides:
        if not isinstance(value, dict):
            p.fail('工时参数须为对象')
        row = {'task_id': p.text(value.get('task_id'), '任务编号', True, 128)}
        row['minutes'] = p.number(value.get('minutes'), '加工分钟', nullable=True, positive=True, maximum=100000)
        row['setup_minutes'] = p.number(value.get('setup_minutes', 0), '准备分钟', maximum=10000)
        row['wait_hours'] = p.number(value.get('wait_hours', 0), '工后等待小时', maximum=4320)
        rows.append(row)
    if len({r['task_id'] for r in rows}) != len(rows):
        p.fail('同一任务不能重复填写工时参数')
    return {'name': p.text(data.get('name') or '生产排产模拟', '模拟名称', True, 120), 'start_date': start,
            'horizon_days': horizon, 'factory_type': typ, 'task_ids': list(dict.fromkeys(ids)),
            'rush_task_ids': list(dict.fromkeys(rush)), 'overrides': rows, 'note': p.text(data.get('note'), '模拟说明')}


def simulate(store, con, config, ctx, rush=None):
    first = date.fromisoformat(config['start_date'])
    days = [first + timedelta(days=i) for i in range(config['horizon_days']) if (first + timedelta(days=i)).isoweekday() in ctx['calendar']['weekdays']]
    horizons = [datetime.combine(d, time(8)) for d in days]
    candidates = [t for t in ctx['tasks'].values() if eligible(t, ctx, config['factory_type']) and (not config['task_ids'] or t['id'] in config['task_ids'])]
    if len(candidates) > 300:
        p.fail('本次最多模拟 300 道工序，请缩小任务范围')
    missing = set(config['task_ids']) - {t['id'] for t in candidates}
    if missing:
        p.fail('所选任务未发布、已关闭、属于其他场景或已失效', 409, task_ids=sorted(missing))
    fixed = planning.effective_plans(ctx)
    fixed_ids = {x['task_id'] for x in fixed}
    overrides = {x['task_id']: x for x in config['overrides']}
    rush_ids = set(config['rush_task_ids'] if rush is None else rush)
    if (set(overrides) | rush_ids) - {t['id'] for t in candidates}:
        p.fail('工时参数或插单任务不在本次模拟范围内')
    occupied = defaultdict(set)
    ready = {}
    frozen = []
    for plan in fixed:
        t = ctx['tasks'][plan['task_id']]
        resources = ['person:' + plan['person_id']]
        if t.get('workcenter_id'):
            resources.append('wc:' + t['workcenter_id'])
        segments = plan.get('minute_segments')
        if segments:
            # Published minute schedules keep their actual simultaneous slots.
            # Moving them to the morning would overlap other frozen jobs and
            # erase deliberate waiting gaps between linked operations.
            for segment in segments:
                day_key = segment['date']
                occupied_minutes = range(segment['start_minute'], segment['end_minute'])
                for resource in resources:
                    occupied[(resource, day_key)].update(occupied_minutes)
        else:
            for a in plan.get('allocations', []):
                beginning = max((max(occupied[(resource, a['date'])], default=-1) + 1 for resource in resources), default=0)
                for resource in resources:
                    occupied[(resource, a['date'])].update(range(beginning, beginning + math.ceil(a['minutes'])))
        if plan.get('ready_at'):
            ready[t['id']] = datetime.fromisoformat(plan['ready_at'])
        else:
            ready[t['id']] = datetime.combine(date.fromisoformat(plan['end_date']) + timedelta(days=1), time())
        frozen.append(plan['id'])
    pending = {t['id']: t for t in candidates if t['id'] not in fixed_ids}
    result, unplaced = [], []
    rejected = set()
    while pending:
        available = [t for t in pending.values() if not any(dep in pending for dep in t.get('dependencies', []))]
        if not available:
            for t in pending.values():
                unplaced.append({'task_id': t['id'], 'title': t['title'], 'blockers': ['前置关系循环或缺少可排顺序']})
            break
        available.sort(key=lambda t: (0 if t['status'] == 'in_progress' else 1, 0 if t['id'] in rush_ids else 1,
                                      -t.get('priority', 0), ctx['projects'][t['project_id']].get('due_date') or '9999-12-31', t['id']))
        t = available[0]
        del pending[t['id']]
        project = ctx['projects'][t['project_id']]
        errors, warnings = planning.person_issues(t, ctx), []
        opt = overrides.get(t['id'], {})
        minutes = opt.get('minutes') if opt.get('minutes') is not None else planning.estimate(t)
        setup, wait = opt.get('setup_minutes', 0), opt.get('wait_hours', 0)
        if minutes is None or minutes <= 0:
            errors.append('加工时间待确认')
        earliest = datetime.combine(first, time(8))
        for dep in t.get('dependencies', []):
            previous = ctx['tasks'].get(dep)
            if not previous or previous.get('project_id') != t['project_id'] or previous.get('archived') or previous.get('revision') != t['revision']:
                errors.append('前置任务不存在或工程版本无效')
            elif previous['status'] == 'done':
                pass
            elif dep in rejected:
                errors.append('前置工序暂不能排产：' + previous['title'])
            elif dep in ready:
                earliest = max(earliest, ready[dep])
            else:
                errors.append('前置工序未完成且未纳入排程：' + previous['title'])
        for material in ctx['materials']:
            if t['id'] in material.get('task_ids', []) and p.material_view(material)['shortage_quantity']:
                if material.get('expected_date'):
                    earliest = max(earliest, datetime.combine(date.fromisoformat(material['expected_date']), time(8)))
                    warnings.append('以 ' + material['name'] + ' 预计到料日排程，开工仍需实际齐套')
                else:
                    errors.append('物料缺口未确认到货日：' + material['name'])
        for issue in ctx['issues']:
            if issue.get('task_id') == t['id'] and issue['status'] != 'resolved' and issue['type'] != 'urgent':
                errors.append('现场异常未解除：' + issue['title'])
        for check in p.check_sheet(store, con, t)['items']:
            if check['status'] != 'ready':
                warnings.append('开工前确认：' + check['label'])
        if t['status'] == 'blocked':
            warnings.append('已暂停，排程不会自动恢复开工')
        resources = [('person:' + str(t.get('assignee')), ctx['people'].get(t.get('assignee'), {}).get('capacity_minutes'))]
        wc = ctx['workcenters'].get(t.get('workcenter_id'))
        if t.get('workcenter_id'):
            if not wc or wc.get('factory_id') != project.get('factory_id'):
                errors.append('工作中心归属无效')
            resources.append(('wc:' + str(t['workcenter_id']), wc.get('capacity_minutes') if wc else None))
        if any(type(cap) not in (int, float) or not 0 < cap <= 960 for _, cap in resources):
            errors.append('需确认人员和工作中心每日有效容量（最多 16 小时）')
        if errors:
            unplaced.append({'task_id': t['id'], 'title': t['title'], 'blockers': list(dict.fromkeys(errors))})
            rejected.add(t['id'])
            continue
        total = math.ceil(minutes + setup)
        slots = []
        limit = int(min(cap for _, cap in resources))
        for beginning in horizons:
            day_key = beginning.date().isoformat()
            offset = max(0, math.ceil((earliest - beginning).total_seconds() / 60))
            for minute in range(offset, limit):
                if all(minute not in occupied[(key, day_key)] for key, _ in resources):
                    slots.append((beginning, minute))
                    if len(slots) == total:
                        break
            if len(slots) == total:
                break
        if len(slots) < total:
            unplaced.append({'task_id': t['id'], 'title': t['title'], 'blockers': ['模拟范围内剩余人员或工作中心容量不足']})
            rejected.add(t['id'])
            continue
        allocs = defaultdict(int)
        for beginning, minute in slots:
            day_key = beginning.date().isoformat()
            allocs[day_key] += 1
            for key, _ in resources:
                occupied[(key, day_key)].add(minute)
        start_at = slots[0][0] + timedelta(minutes=slots[0][1])
        end_at = slots[-1][0] + timedelta(minutes=slots[-1][1] + 1)
        ready_at = end_at + timedelta(hours=wait)
        if ready_at.second or ready_at.microsecond:
            ready_at = ready_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        ready[t['id']] = ready_at
        segments = []
        for beginning, minute in slots:
            day_key = beginning.date().isoformat()
            if segments and segments[-1]['date'] == day_key and segments[-1]['end_minute'] == minute:
                segments[-1]['end_minute'] = minute + 1
            else:
                segments.append({'date': day_key, 'start_minute': minute, 'end_minute': minute + 1})
        delay = max(0, (ready_at.date() - date.fromisoformat(project['due_date'])).days) if project.get('due_date') else None
        result.append({'task_id': t['id'], 'title': t['title'], 'project_id': t['project_id'], 'person_id': t['assignee'],
                       'workcenter_id': t.get('workcenter_id'), 'start_at': iso(start_at), 'end_at': iso(end_at), 'ready_at': iso(ready_at),
                       'minutes': round(minutes, 2), 'setup_minutes': setup, 'wait_hours': wait, 'planned_minutes': total,
                       'allocations': [{'date': d, 'minutes': m} for d, m in allocs.items()], 'minute_segments': segments, 'warnings': warnings, 'delay_days': delay,
                       'task_revision': t['revision'], 'task_execution_version': t.get('execution_version', 0),
                       'minutes_source': 'manual' if opt.get('minutes') is not None else 'task_estimate'})
    return {'rows': result, 'unplaced': unplaced, 'frozen_plan_ids': frozen,
            'summary': {'scheduled': len(result), 'unplaced': len(unplaced), 'late_tasks': sum(bool(r['delay_days']) for r in result),
                        'finish_date': max((r['ready_at'][:10] for r in result), default=None), 'frozen_plans': len(frozen)}}


def preview(store, con, data):
    config = request(data)
    ctx = context(store, con)
    result = simulate(store, con, config, ctx)
    baseline = simulate(store, con, config, ctx, rush=[]) if config['rush_task_ids'] else result
    prior = {r['task_id']: r for r in baseline['rows']}
    impacts = [{'task_id': r['task_id'], 'title': r['title'], 'before_end': prior[r['task_id']]['ready_at'], 'after_end': r['ready_at'],
                'shift_days': (date.fromisoformat(r['ready_at'][:10]) - date.fromisoformat(prior[r['task_id']]['ready_at'][:10])).days,
                'shift_minutes': round((datetime.fromisoformat(r['ready_at']) - datetime.fromisoformat(prior[r['task_id']]['ready_at'])).total_seconds() / 60)}
               for r in result['rows'] if r['task_id'] in prior and r['ready_at'] != prior[r['task_id']]['ready_at']]
    current = {r['task_id']: r for r in result['rows']}
    for identifier in sorted(set(prior) - set(current)):
        row = prior[identifier]
        impacts.append({'task_id': identifier, 'title': row['title'], 'before_end': row['ready_at'], 'after_end': None,
                        'shift_days': None, 'shift_minutes': None, 'change': 'unplaced'})
    for identifier in sorted(set(current) - set(prior)):
        row = current[identifier]
        impacts.append({'task_id': identifier, 'title': row['title'], 'before_end': None, 'after_end': row['ready_at'],
                        'shift_days': None, 'shift_minutes': None, 'change': 'scheduled'})
    scenario = {'id': p.uid('scenario'), 'version': 1, 'status': 'preview', 'created_at': p.stamp(), 'factory_type': config['factory_type'],
                'name': config['name'], 'start_date': config['start_date'], 'config': config, 'fingerprint': fingerprint(ctx), 'impact': impacts, **result}
    store.put(con, 'scheduling_scenarios', scenario)
    return {'scenario': scenario}


def apply(store, con, identifier, data):
    scenario = p.get(store, con, 'scheduling_scenarios', identifier)
    if scenario['status'] == 'applied':
        return {'scenario': scenario, 'plans': [p.get(store, con, 'plans', i) for i in scenario['plan_ids']], 'duplicate': True}
    p.expected(scenario, data)
    note = p.text(data.get('note'), '排产确认说明', True)
    ctx = context(store, con)
    if scenario['fingerprint'] != fingerprint(ctx):
        p.fail('生产数据或资源已变化，请重新模拟后确认', 409, code='scenario_stale')
    if not scenario['rows']:
        p.fail('没有可写入的排程，请先补齐工时、资源或前置条件', 409)
    plans = []
    for row in scenario['rows']:
        plan = {'id': p.uid('plan'), 'project_id': row['project_id'], 'task_id': row['task_id'], 'person_id': row['person_id'],
                'task_revision': row['task_revision'], 'task_execution_version': row['task_execution_version'],
                'start_date': row['start_at'][:10], 'end_date': row['end_at'][:10], 'start_at': row['start_at'], 'end_at': row['end_at'],
                'ready_at': row['ready_at'], 'workcenter_id': row['workcenter_id'], 'setup_minutes': row['setup_minutes'], 'wait_hours': row['wait_hours'],
                'planned_minutes': row['planned_minutes'], 'minutes_source': row['minutes_source'],
                'material_status': 'pending', 'note': note, 'allocations': row['allocations'], 'minute_segments': row['minute_segments'], 'status': 'scheduled', 'version': 1,
                'created_at': p.stamp(), 'updated_at': p.stamp(), 'scenario_id': identifier}
        store.put(con, 'plans', plan)
        store.event(con, plan['project_id'], 'scenario_plan_applied', '确认排产：' + row['title'], plan_id=plan['id'], scenario_id=identifier)
        plans.append(plan)
    scenario.update(status='applied', version=scenario['version'] + 1, applied_at=p.stamp(), apply_note=note, plan_ids=[x['id'] for x in plans])
    store.put(con, 'scheduling_scenarios', scenario)
    return {'scenario': scenario, 'plans': plans}


def build(store, con, factory_type=None, include_demo=False):
    ctx = context(store, con)
    projects = [v for v in ctx['projects'].values() if (not factory_type or v.get('factory_type', 'cabinet') == factory_type) and (include_demo or not v.get('demo'))]
    factory_ids = {p.get('factory_id') for p in projects if p.get('factory_id')}
    return {'scenarios': [s for s in store.all(con, 'scheduling_scenarios') if not factory_type or s['factory_type'] == factory_type],
            'tasks': [t for t in ctx['tasks'].values() if eligible(t, ctx, factory_type, include_demo)], 'projects': projects,
            'people': [r for r in ctx['people'].values() if include_demo or not r.get('demo')],
            'workcenters': [r for r in ctx['workcenters'].values() if not factory_type or r['factory_id'] in factory_ids],
            'calendar': ctx['calendar'], 'method': '人员与工作中心有限容量；前置串并行；已有人日排程冻结；插单优先；工后等待不占资源'}
