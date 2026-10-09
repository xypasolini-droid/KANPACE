"""Local, evidence-only operation duration and recorded-cost calibration.

No estimated task hours, demo rows, open intervals, or partial completions are
training observations. Suggestions never change templates, quotes, or tasks.
"""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math

import operations as ops


class CalibrationError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, status=400):
    raise CalibrationError(status, message)


def finite(value, positive=True):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def quantile(values, proportion):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * proportion
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (position - low), 4)


def signature(project, task):
    """Keep plants, operation semantics, quantities and measurement units separate."""
    scope = {'factory_type': project.get('factory_type', 'cabinet'), 'factory_id': task.get('factory_id') or project.get('factory_id'),
             'trade': task.get('trade', ''), 'work_kind': 'rework' if task.get('rework_of') else 'production',
             'process': task.get('process') or task.get('template_node_id') or task.get('rule_id') or '',
             'unit': task.get('unit') or ('件' if task.get('part_id') else '项'),
             'start_checks': task.get('start_checks', []), 'acceptance': task.get('acceptance_checks') or task.get('acceptance', ''),
             'instructions': task.get('instructions', '')}
    # Object-specific instructions can change the difficulty; keep them distinct.
    key = hashlib.sha256(json.dumps(scope, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return key, scope


def sample_for(project, task, sessions, people):
    if project.get('demo') or task.get('demo'):
        return None, 'demo'
    done = task.get('status') == 'done' or (task.get('archived') and task.get('previous_status') == 'done')
    if not done:
        return None, 'not_complete'
    quantity = task.get('completed_quantity')
    if not finite(quantity) or not finite(task.get('quantity')) or quantity != task['quantity']:
        return None, 'completion_quantity_unknown'
    if not sessions:
        return None, 'no_actual_sessions'
    periods = []
    for session in sessions:
        if session.get('project_id') != project['id'] or session.get('revision') != task.get('revision'):
            return None, 'session_scope_mismatch'
        if people.get(session.get('person_id'), {}).get('demo'):
            return None, 'demo_person'
        start, end = timestamp(session.get('started_at')), timestamp(session.get('ended_at'))
        if not start or not end:
            return None, 'open_or_invalid_session'
        minutes = (end - start).total_seconds() / 60
        if not finite(minutes) or not finite(session.get('minutes')) or abs(minutes - session['minutes']) > .01:
            return None, 'invalid_session_minutes'
        if minutes > 24 * 60:
            return None, 'session_longer_than_one_day'
        periods.append((start, end, minutes, session['id']))
    periods.sort(key=lambda p: p[0])
    if any(periods[i][0] < periods[i - 1][1] for i in range(1, len(periods))):
        return None, 'overlapping_sessions'
    original_start = timestamp(task.get('started_at'))
    completed_at = timestamp(task.get('completed_at'))
    if not original_start or not completed_at or abs((periods[0][0] - original_start).total_seconds()) > 5:
        return None, 'incomplete_start_record'
    if abs((periods[-1][1] - completed_at).total_seconds()) > 5:
        return None, 'incomplete_finish_record'
    elapsed = round(sum(p[2] for p in periods), 4)
    return {'task_id': task['id'], 'project_id': project['id'], 'project_name': project.get('name', ''),
            'task_title': task.get('title', ''), 'quantity': quantity, 'active_minutes': elapsed,
            'minutes_per_unit': round(elapsed / quantity, 4), 'completed_at': task.get('completed_at'),
            'session_ids': [p[3] for p in periods], 'person_ids': sorted({s.get('person_id') for s in sessions if s.get('person_id')})}, None


def holdout_validation(samples):
    """Validate on the most recently completed whole project, never random rows.

    Earlier samples from the holdout project are also excluded from training.
    Training observations must precede its earliest completed sample, preventing
    future information from leaking into an earlier held-out observation.
    """
    projects = defaultdict(list)
    for sample in samples:
        projects[sample['project_id']].append(sample)
    result = {'status': 'insufficient_projects', 'method': 'latest_project_holdout', 'minimum_train_projects': 3,
              'training_project_count': 0, 'training_sample_count': 0, 'holdout_project_count': 0, 'holdout_sample_count': 0,
              'training_project_ids': [], 'holdout_project_ids': [], 'cutoff_at': None, 'predictions': [],
              'mae_minutes': None, 'mape_percent': None, 'p80_coverage': None, 'excluded_future_samples': 0}
    if not projects:
        return result
    holdout_id = max(projects, key=lambda identifier: (max(timestamp(s['completed_at']) for s in projects[identifier]), identifier))
    test = projects[holdout_id]
    cutoff = min(timestamp(s['completed_at']) for s in test)
    prior = [s for s in samples if s['project_id'] != holdout_id]
    train = [s for s in prior if timestamp(s['completed_at']) < cutoff]
    train_ids = sorted({s['project_id'] for s in train})
    result.update(training_project_count=len(train_ids), training_sample_count=len(train), holdout_project_count=1,
                  holdout_sample_count=len(test), training_project_ids=train_ids, holdout_project_ids=[holdout_id],
                  cutoff_at=cutoff.isoformat(), excluded_future_samples=len(prior) - len(train))
    if len(projects) < 4:
        return result
    if len(train_ids) < 3:
        result['status'] = 'insufficient_history'
        return result
    p50 = quantile([s['minutes_per_unit'] for s in train], .5)
    p80 = quantile([s['minutes_per_unit'] for s in train], .8)
    predictions = []
    for sample in sorted(test, key=lambda s: timestamp(s['completed_at'])):
        forecast, upper = p50 * sample['quantity'], p80 * sample['quantity']
        actual = sample['active_minutes']
        error = abs(forecast - actual)
        predictions.append({'task_id': sample['task_id'], 'project_id': sample['project_id'],
                            'project_name': sample['project_name'], 'task_title': sample['task_title'],
                            'quantity': sample['quantity'], 'completed_at': sample['completed_at'],
                            'predicted_minutes': round(forecast, 4), 'actual_minutes': actual,
                            'absolute_error_minutes': round(error, 4), 'relative_error_percent': round(error / actual * 100, 4),
                            'p80_predicted_minutes': round(upper, 4), 'p80_covered': actual <= upper})
    result.update(status='available', predictions=predictions,
                  mae_minutes=round(sum(v['absolute_error_minutes'] for v in predictions) / len(predictions), 4),
                  mape_percent=round(sum(v['relative_error_percent'] for v in predictions) / len(predictions), 4),
                  p80_coverage=round(sum(v['p80_covered'] for v in predictions) / len(predictions), 4))
    return result


def validation_summary(groups):
    available = [g for g in groups if g['validation']['status'] == 'available']
    values = [prediction for g in available for prediction in g['validation']['predictions']]
    return {'available_group_count': len(available), 'holdout_sample_count': len(values),
            'holdout_project_count': len({p['project_id'] for p in values}),
            'mae_minutes': round(sum(p['absolute_error_minutes'] for p in values) / len(values), 4) if values else None,
            'mape_percent': round(sum(p['relative_error_percent'] for p in values) / len(values), 4) if values else None,
            'p80_coverage': round(sum(p['p80_covered'] for p in values) / len(values), 4) if values else None,
            'method': '每个工序组按最近完整项目留出，训练项目与测试项目完全分离'}


def build(store, con, factory_type=None, factory_id=None):
    if factory_type is not None and factory_type not in ops.FACTORY_TYPES:
        fail('工厂类型无效')
    if factory_id:
        ops.get(store, con, 'factories', factory_id)
    projects = {p['id']: p for p in store.all(con, 'projects')}
    people = {p['id']: p for p in store.all(con, 'people')}
    sessions = defaultdict(list)
    for session in store.all(con, 'work_sessions'):
        sessions[session.get('task_id')].append(session)
    costs = defaultdict(list)
    for cost in store.all(con, 'actual_costs'):
        if cost.get('task_id') and finite(cost.get('amount')):
            costs[cost['task_id']].append(cost)
    grouped, excluded = {}, Counter()
    samples_by_task = {}
    tasks = store.all(con, 'tasks')
    # Migration copies retain production evidence on their original task, so
    # only the row with its own complete sessions is used as an observation.
    for task in tasks:
        project = projects.get(task.get('project_id'))
        if not project:
            excluded['missing_project'] += 1
            continue
        if factory_type and project.get('factory_type', 'cabinet') != factory_type:
            continue
        if factory_id and (task.get('factory_id') or project.get('factory_id')) != factory_id:
            continue
        sample, reason = sample_for(project, task, sessions.get(task['id'], []), people)
        if reason:
            excluded[reason] += 1
            continue
        key, scope = signature(project, task)
        if not scope['trade'] or not scope['process']:
            excluded['operation_scope_unknown'] += 1
            continue
        group = grouped.setdefault(key, {'key': key, **scope, 'scope_signature': key, 'samples': [], 'cost_observations': defaultdict(list)})
        sample['recorded_costs'] = []
        by_category = defaultdict(list)
        for cost in costs[task['id']]:
            if cost.get('project_id') == project['id']:
                by_category[cost['category']].append(cost)
        for category, records in by_category.items():
            amount = round(sum(c['amount'] for c in records), 4)
            item = {'category': category, 'recorded_amount': amount, 'recorded_cost_per_unit': round(amount / sample['quantity'], 4),
                    'cost_record_ids': [c['id'] for c in records], 'task_id': task['id']}
            sample['recorded_costs'].append(item)
            group['cost_observations'][category].append(item)
        group['samples'].append(sample)
        samples_by_task[task['id']] = (key, sample)
    groups = []
    for group in grouped.values():
        observations = group.pop('cost_observations')
        values = [s['minutes_per_unit'] for s in group['samples']]
        project_count = len({s['project_id'] for s in group['samples']})
        n = len(values)
        confidence = 'insufficient' if n < 3 else 'limited' if n < 10 or project_count < 3 else 'observed'
        group.update(sample_count=n, project_count=project_count, p50_minutes_per_unit=quantile(values, .5),
                     p80_minutes_per_unit=quantile(values, .8), minimum_minutes_per_unit=min(values), maximum_minutes_per_unit=max(values),
                     confidence=confidence, confidence_label={'insufficient': '样本不足', 'limited': '有限样本', 'observed': '可复核历史区间'}[confidence],
                     recorded_costs=[{'category': category, 'sample_count': len(rows),
                                      'p50_per_unit': quantile([r['recorded_cost_per_unit'] for r in rows], .5),
                                      'p80_per_unit': quantile([r['recorded_cost_per_unit'] for r in rows], .8),
                                      'basis': '已记录成本 / 已完成工作对象数量；不代表完整成本', 'samples': rows}
                                     for category, rows in sorted(observations.items())])
        group['validation'] = holdout_validation(group['samples'])
        group['samples'].sort(key=lambda s: s['completed_at'], reverse=True)
        groups.append(group)
    return {'groups': sorted(groups, key=lambda g: (g['factory_type'], g.get('factory_id') or '', g['trade'], g['process'], g['key'])),
            'validation_summary': validation_summary(groups),
            'excluded': dict(excluded), 'summary': {'group_count': len(groups), 'sample_count': len(samples_by_task),
                'excluded_task_count': sum(excluded.values()), 'status': 'available' if groups else 'no_actual_samples'},
            'basis': '真实完工任务的完整开工—暂停—恢复—完成计时；按同工厂、同工序要求、同单位归组',
            'cost_basis': '已记录成本区间；未完整归集的费用不推定为零，不能直接当作完整报价',
            'automatic_application': False}


def estimate(store, con, data):
    ops.check_fields(data, {'task_id', 'quantity', 'percentile'})
    task = ops.get(store, con, 'tasks', data.get('task_id'))
    project = ops.get(store, con, 'projects', task['project_id'])
    if project.get('demo') or task.get('demo'):
        fail('演示任务不参与真实周期校准')
    percentile = data.get('percentile', 'p50')
    if percentile not in ('p50', 'p80'):
        fail('请选择 P50 或 P80 区间')
    quantity = data.get('quantity', task.get('remaining_quantity', task.get('quantity')))
    if not finite(quantity):
        fail('请提供大于零的明确工作对象数量')
    key, scope = signature(project, task)
    result = build(store, con, factory_type=project.get('factory_type', 'cabinet'), factory_id=scope['factory_id'])
    group = next((g for g in result['groups'] if g['key'] == key), None)
    value = group[percentile + '_minutes_per_unit'] if group else None
    return {'task_id': task['id'], 'scope_signature': key, 'quantity': quantity, 'unit': scope['unit'], 'percentile': percentile,
            'estimated_minutes': round(value * quantity, 2) if value is not None else None,
            'minutes_per_unit': value, 'sample_count': group['sample_count'] if group else 0,
            'confidence': group['confidence'] if group else 'no_samples', 'source_samples': group['samples'] if group else [],
            'recorded_cost_reference': [{'category': c['category'], 'amount': round(c[percentile + '_per_unit'] * quantity, 2),
                                         'sample_count': c['sample_count'], 'basis': c['basis']} for c in group['recorded_costs']] if group else [],
            'applied': False, 'note': '待负责人结合对象难度和资源核对' if group else '尚无相同工序要求的完整实绩样本'}
