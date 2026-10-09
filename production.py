"""Operational ledgers and release gates. All writes use the caller's transaction.

Materials represent accepted quantities reserved for an explicit requirement,
not an invented warehouse balance. Unknown commercial values remain null.
"""
from datetime import date, datetime, timezone
from copy import deepcopy
import hashlib
import json
import math
from uuid import uuid4

import fulfillment


class ProductionError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, status=400, **details):
    raise ProductionError(status, message, details or None)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def uid(prefix):
    return prefix + '_' + uuid4().hex[:16]


def text(value, label, required=False, limit=2000):
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        fail(label + '须为有效文字' + ('，不能为空' if required else ''))
    return value.strip()


def number(value, label, nullable=False, positive=False, maximum=1e12):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not (0 < value <= maximum if positive else 0 <= value <= maximum):
        fail(label + '须为有效' + ('正数' if positive else '非负数'))
    return round(value, 4)


def day(value, label='日期', required=False):
    value = text(value, label, required, 10)
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            fail(label + '格式须为 YYYY-MM-DD')
    return value or None


def get(store, con, kind, identifier):
    if not isinstance(identifier, str):
        fail('请选择有效记录')
    record = next((r for r in store.all(con, kind) if r['id'] == identifier), None)
    if not record:
        fail('未找到记录：' + identifier, 404)
    return record


def expected(item, data, key='expected_version', field='version'):
    value = data.get(key)
    if type(value) is not int or value != item.get(field, 0):
        fail('记录已更新，请刷新后重新核对', 409, code='version_conflict', version=item.get(field, 0))


def project(store, con, identifier, writable=True):
    p = get(store, con, 'projects', identifier)
    if writable and (fulfillment.is_closed(p) or p.get('archived')):
        fail('项目已完成或发货，不能新增生产工作', 409)
    return p


def task_for(store, con, identifier, project_id=None):
    t = get(store, con, 'tasks', identifier)
    p = project(store, con, t['project_id'])
    if project_id and t['project_id'] != project_id:
        fail('任务不属于所选项目', 409)
    if t.get('archived') or t.get('status') == 'invalidated' or t.get('revision') != p.get('revision'):
        fail('任务工程版本已失效', 409)
    return t


def owner(store, con, owner_id, p):
    if not owner_id:
        return None
    import operations
    person = get(store, con, 'people', owner_id)
    issues = operations.assignment_issues(p, person)
    if issues:
        fail('负责人不适用于这个项目', 409, blockers=issues)
    return person['id']


def base(store, con, kind, data, p):
    identifier = data.get('id')
    item = deepcopy(get(store, con, kind, identifier)) if identifier else {'id': uid(kind), 'project_id': p['id'], 'version': 0, 'created_at': stamp()}
    if item['project_id'] != p['id']:
        fail('不可更改记录所属项目', 409)
    if identifier:
        expected(item, data)
    return item


def save(store, con, kind, item, title):
    item.update(version=item.get('version', 0) + 1, updated_at=stamp())
    store.put(con, kind, item)
    store.event(con, item.get('project_id'), kind + '_saved', title, record_id=item['id'], version=item['version'])
    return item


def mutate(store, con, action, data, callback):
    """An unchanged modal retry can recover a lost response without double entry."""
    payload = dict(data)
    request_id = payload.pop('request_id', None)
    if request_id is None:
        return callback(store, con, payload)
    request_id = text(request_id, '请求编号', True, 128)
    identifier = 'prodreq_' + hashlib.sha256((action + ':' + request_id).encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    prior = next((r for r in store.all(con, 'production_requests') if r['id'] == identifier), None)
    if prior:
        if prior['payload_hash'] != digest:
            fail('此操作已经保存，但重试内容不同。请刷新核对原记录后再新增操作', 409, code='request_conflict')
        return dict(prior['result'], duplicate=True)
    result = callback(store, con, payload)
    store.put(con, 'production_requests', {'id': identifier, 'project_id': payload.get('project_id'), 'request_id': request_id,
              'action': action, 'payload_hash': digest, 'created_at': stamp(), 'result': result})
    return result


def material_view(m):
    result = dict(m)
    result['shortage_quantity'] = round(max(0, m['required_quantity'] - m['accepted_quantity']), 4)
    result['status'] = 'shortage' if result['shortage_quantity'] else 'ready'
    return result


def save_material(store, con, data):
    p = project(store, con, data.get('project_id'))
    m = base(store, con, 'materials', data, p)
    ids = data.get('task_ids', m.get('task_ids', []))
    if not isinstance(ids, list) or len(ids) > 500 or any(not isinstance(x, str) for x in ids):
        fail('关联任务须为有效列表')
    for identifier in ids:
        task_for(store, con, identifier, p['id'])
    before = {'required_quantity': m.get('required_quantity'), 'accepted_quantity': m.get('accepted_quantity'), 'task_ids': m.get('task_ids', [])}
    m.update(name=text(data.get('name', m.get('name')), '物料名称', True, 200),
             sku=text(data.get('sku', m.get('sku')), '物料编码', limit=200),
             scope=text(data.get('scope', m.get('scope')), '所属部件或区域', limit=200),
             unit=text(data.get('unit', m.get('unit', '件')), '单位', True, 30), task_ids=list(dict.fromkeys(ids)),
             required_quantity=number(data.get('required_quantity', m.get('required_quantity')), '需求数量', positive=True),
             accepted_quantity=number(data.get('accepted_quantity', m.get('accepted_quantity', 0)), '已验收并预留数量'),
             expected_date=day(data.get('expected_date', m.get('expected_date')), '预计到料日期'),
             supplier=text(data.get('supplier', m.get('supplier')), '供应商', limit=200),
             owner_id=owner(store, con, data.get('owner_id', m.get('owner_id')), p),
             note=text(data.get('note', m.get('note')), '物料备注'))
    if m['accepted_quantity'] > m['required_quantity']:
        fail('预留数量不能超过本项需求，余料请保留在库存或另建需求')
    save(store, con, 'materials', m, '更新物料齐套：' + m['name'])
    store.put(con, 'material_movements', {'id': uid('matmove'), 'project_id': p['id'], 'material_id': m['id'],
              'version': m['version'], 'before': before, 'after': {k: m[k] for k in before}, 'note': m['note'], 'created_at': stamp()})
    return {'material': material_view(m)}


def save_issue(store, con, data):
    p = project(store, con, data.get('project_id'))
    item = base(store, con, 'issues', data, p)
    task_id = data.get('task_id', item.get('task_id')) or None
    if task_id:
        task_for(store, con, task_id, p['id'])
    category = data.get('type', item.get('type', 'other'))
    status = data.get('status', item.get('status', 'open'))
    if category not in ('material', 'quality', 'equipment', 'drawing', 'site', 'urgent', 'other') or status not in ('open', 'in_progress', 'resolved'):
        fail('请选择有效异常类型和状态')
    item.update(task_id=task_id, type=category, status=status,
                title=text(data.get('title', item.get('title')), '问题描述', True, 500),
                owner_id=owner(store, con, data.get('owner_id', item.get('owner_id')), p),
                due_date=day(data.get('due_date', item.get('due_date')), '处理期限'),
                note=text(data.get('note', item.get('note')), '备注'),
                resolution=text(data.get('resolution', item.get('resolution')), '解决结果', status == 'resolved'))
    if status == 'resolved':
        item['resolved_at'] = stamp()
    else:
        item.pop('resolved_at', None)
    return {'issue': save(store, con, 'issues', item, '处理异常：' + item['title'])}


def check_sheet(store, con, task):
    labels = task.get('start_checks', [])
    saved = next((x for x in store.all(con, 'entry_checks', task['project_id']) if x['task_id'] == task['id'] and x.get('revision') == task['revision']), None)
    row = deepcopy(saved) if saved else {'id': 'checks_' + task['id'], 'project_id': task['project_id'], 'task_id': task['id'], 'revision': task['revision'], 'version': 0, 'items': []}
    previous = {x['key']: x for x in row['items']}
    row['items'] = [dict(previous.get(hashlib.sha256(str(label).encode()).hexdigest()[:16], {}),
                         key=hashlib.sha256(str(label).encode()).hexdigest()[:16], label=str(label)) for label in labels]
    for item in row['items']:
        item.setdefault('status', 'pending')
        item.setdefault('note', '')
    row['task_execution_version'] = task.get('execution_version', 0)
    return row


def save_checks(store, con, data):
    t = task_for(store, con, data.get('task_id'))
    if t['status'] == 'done':
        fail('已完成任务的开工检查不可改写', 409)
    expected(t, data, 'expected_task_version', 'execution_version')
    sheet = check_sheet(store, con, t)
    expected(sheet, data)
    supplied = data.get('items')
    if not isinstance(supplied, list) or len(supplied) != len(sheet['items']) or {i.get('key') for i in supplied if isinstance(i, dict)} != {i['key'] for i in sheet['items']}:
        fail('请逐项核对当前模板的开工条件')
    p = project(store, con, t['project_id'])
    by_key = {i['key']: i for i in supplied}
    for item in sheet['items']:
        value = by_key[item['key']]
        if value.get('status') not in ('pending', 'ready', 'blocked'):
            fail('检查结果须为待确认、已就绪或受阻')
        item.update(status=value['status'], note=text(value.get('note'), '核对说明', value['status'] != 'pending'),
                    owner_id=owner(store, con, value.get('owner_id'), p), due_date=day(value.get('due_date'), '预计解除日期'), checked_at=stamp())
    return {'check': save(store, con, 'entry_checks', sheet, '核对开工条件：' + t['title'])}


def start_blockers(store, con, task, *, include_checks=True):
    reasons = []
    for m in store.all(con, 'materials', task['project_id']):
        if task['id'] in m.get('task_ids', []) and material_view(m)['shortage_quantity'] > 0:
            reasons.append('缺料：' + m['name'] + ' ' + str(material_view(m)['shortage_quantity']) + m['unit'])
    for issue in store.all(con, 'issues', task['project_id']):
        if issue.get('task_id') == task['id'] and issue.get('status') != 'resolved' and issue.get('type') != 'urgent':
            reasons.append('异常未关闭：' + issue['title'])
    if include_checks:
        for item in check_sheet(store, con, task)['items']:
            if item['status'] != 'ready':
                reasons.append('开工条件未确认：' + item['label'])
    for identifier in dict.fromkeys(task.get('dependencies', []) + task.get('schedule_dependencies', [])):
        dependency = next((t for t in store.all(con, 'tasks', task['project_id']) if t['id'] == identifier), None)
        if dependency and dependency.get('status') == 'done' and completion_blockers(store, con, dependency):
            reasons.append('前序质量待放行：' + dependency['title'])
    return reasons


def after_execution(store, con, task, action, details):
    """Track actual active intervals only; delivery acknowledgements never call here."""
    at = stamp()
    if task['status'] == 'blocked' and task.get('pause_reason') == 'quality':
        task['quality_hold_since'] = at
        store.put(con, 'tasks', task)
    sessions = [s for s in store.all(con, 'work_sessions', task['project_id']) if s['task_id'] == task['id'] and not s.get('ended_at')]
    if task['status'] != 'in_progress':
        for session in sessions:
            elapsed = max(0, (datetime.fromisoformat(at) - datetime.fromisoformat(session['started_at'])).total_seconds() / 60)
            session.update(ended_at=at, minutes=round(elapsed, 4), end_execution_version=task['execution_version'], end_status=task['status'])
            store.put(con, 'work_sessions', session)
    elif not sessions:
        store.put(con, 'work_sessions', {'id': uid('session'), 'project_id': task['project_id'], 'task_id': task['id'],
                 'revision': task['revision'], 'person_id': task.get('assignee'), 'started_at': at, 'ended_at': None,
                 'minutes': None, 'start_execution_version': task['execution_version']})
    if task['status'] == 'blocked' and task.get('start_checks'):
        sheet = check_sheet(store, con, task)
        for item in sheet['items']:
            item.update(status='pending', note='', invalidated_reason='暂停后重新核对')
        save(store, con, 'entry_checks', sheet, '暂停后重新核对开工条件：' + task['title'])


def latest_inspection(store, con, task):
    rows = [x for x in store.all(con, 'inspections', task['project_id']) if x['task_id'] == task['id'] and x['revision'] == task['revision']]
    return rows[-1] if rows else None


def completion_blockers(store, con, task):
    latest = latest_inspection(store, con, task)
    if not task.get('inspection_required') and not task.get('quality_hold_since') and not latest:
        return []
    current = latest and latest['result'] == 'passed' and (not task.get('quality_hold_since') or latest['created_at'] > task['quality_hold_since'])
    reasons = [] if current else ['请先登记当前工序的合格检验结果；质量暂停后须重新检验']
    active = [t for t in store.active_tasks(con, task['project_id']) if t.get('rework_of') == task['id'] and t['status'] != 'done']
    if active:
        reasons.append('关联返工尚未完成')
    return reasons


def project_quality_blockers(store, con, project_id):
    blockers = []
    for task in store.active_tasks(con, project_id):
        if (latest_inspection(store, con, task) or task.get('quality_hold_since')) and completion_blockers(store, con, task):
            blockers.append('质量未放行：' + task['title'])
    return blockers


def project_transition(store, con, project_id, target):
    at = stamp()
    if target == 'active':
        for task in store.active_tasks(con, project_id):
            if task['status'] == 'in_progress':
                after_execution(store, con, task, 'project_reopened', {})
    else:
        for session in store.all(con, 'work_sessions', project_id):
            if not session.get('ended_at'):
                session.update(ended_at=at, minutes=round(max(0, (datetime.fromisoformat(at) - datetime.fromisoformat(session['started_at'])).total_seconds() / 60), 4),
                               end_status='project_closed')
                store.put(con, 'work_sessions', session)


def save_inspection(store, con, data):
    t = task_for(store, con, data.get('task_id'), data.get('project_id'))
    p = project(store, con, t['project_id'])
    if t['status'] not in ('in_progress', 'blocked', 'done'):
        fail('开工后才能登记检验结果', 409)
    if 'expected_task_version' in data:
        expected(t, data, 'expected_task_version', 'execution_version')
    result = data.get('result')
    if result not in ('passed', 'failed'):
        fail('检验结果须为合格或不合格')
    checks = t.get('acceptance_checks', [])
    measurements = data.get('measurements', [])
    if not isinstance(measurements, list) or len(measurements) > 100 or any(not isinstance(x, dict) for x in measurements):
        fail('检验实测项须为列表')
    measurements = [{k: text(v.get(k), '检验实测项', k == 'name', 500) for k in ('name', 'value', 'unit', 'criterion')} for v in measurements]
    reworks = [x for x in store.active_tasks(con, p['id']) if x.get('rework_of') == t['id'] and x['status'] != 'done']
    if result == 'passed' and reworks:
        fail('返工任务完成后才能复检合格', 409)
    item = {'id': uid('inspection'), 'project_id': p['id'], 'task_id': t['id'], 'revision': t['revision'],
            'execution_version': t['execution_version'], 'result': result, 'note': text(data.get('note'), '检验记录', True),
            'measurements': measurements, 'acceptance_checks': deepcopy(checks), 'created_at': stamp()}
    rework = None
    if data.get('create_rework'):
        if result != 'failed' or reworks:
            fail('仅不合格且无在途返工时可创建返工任务', 409)
        quantity = data.get('quantity', t['quantity'])
        if type(quantity) is not int or not 1 <= quantity <= t['quantity']:
            fail('返工数量须为不超过原任务数量的正整数')
        assignee = owner(store, con, data.get('owner_id'), p)
        if assignee and t['trade'] not in get(store, con, 'people', assignee).get('skills', []):
            fail('返工负责人不具备对应工种技能', 409)
        minutes = number(data.get('estimated_minutes'), '预计返工分钟', nullable=True, positive=True)
        rework = dict(t, id=uid('task'), title='返工 · ' + t['title'], status='draft', rework_of=t['id'],
                      inspection_id=item['id'], quantity=quantity, completed_quantity=0, remaining_quantity=quantity,
                      progress_recorded=False, execution_version=1, assignee=assignee, dependencies=[],
                      start_checks=[], inspection_required=False, estimated_minutes=minutes, hours=minutes / 60 if minutes is not None else None,
                      notes=text(data.get('rework_note'), '返工要求', True), created_at=stamp(), updated_at=stamp(),
                      pause_reason='', pause_note='', handover_note='', priority=2, released_at=None)
        for key in ('started_at', 'completed_at', 'inspection_result', 'inspection_recorded_at', 'paused_at'):
            rework.pop(key, None)
        store.put(con, 'tasks', rework)
        item['rework_task_id'] = rework['id']
    store.put(con, 'inspections', item)
    store.event(con, p['id'], 'inspection_recorded', '登记检验：' + t['title'], inspection_id=item['id'], result=result, rework_task_id=rework['id'] if rework else None)
    return {'inspection': item, 'rework': rework}


def release_rework(store, con, task_id, data):
    t = task_for(store, con, task_id)
    expected(t, data, 'expected_task_version', 'execution_version')
    if not t.get('rework_of') or t['status'] != 'draft':
        fail('请选择待复核的返工任务', 409)
    p = project(store, con, t['project_id'])
    if p.get('released_revision') != t['revision']:
        fail('项目版本尚未发布', 409)
    note = text(data.get('note'), '返工复核意见', True)
    t.update(status='ready', rework_review_note=note, released_at=stamp())
    store.bump_execution(t)
    store.put(con, 'tasks', t)
    store.event(con, p['id'], 'rework_released', '发布返工：' + t['title'], task_id=t['id'], note=note)
    return {'task': t}


def save_cost(store, con, data):
    p = project(store, con, data.get('project_id'), writable=False)
    task_id = data.get('task_id') or None
    if task_id and get(store, con, 'tasks', task_id)['project_id'] != p['id']:
        fail('成本任务不属于所选项目', 409)
    if data.get('category') not in ('material', 'labor', 'outsourcing', 'equipment', 'rework', 'other'):
        fail('请选择成本类别')
    amount = number(data.get('amount'), '实际成本金额', positive=True)
    item = {'id': uid('cost'), 'project_id': p['id'], 'task_id': task_id, 'category': data['category'], 'amount': amount,
            'quantity': number(data.get('quantity'), '数量', nullable=True, positive=True),
            'unit_price': number(data.get('unit_price'), '单价', nullable=True),
            'occurred_on': day(data.get('occurred_on'), '发生日期', True),
            'note': text(data.get('note'), '成本依据', True), 'created_at': stamp()}
    store.put(con, 'actual_costs', item)
    store.event(con, p['id'], 'cost_recorded', '登记实际成本', cost_id=item['id'], amount=amount, category=item['category'])
    return {'cost': item}


def save_financial(store, con, data):
    p = project(store, con, data.get('project_id'), writable=False)
    current = next((r for r in store.all(con, 'financials', p['id'])), None)
    item = deepcopy(current) if current else {'id': uid('finance'), 'project_id': p['id'], 'version': 0}
    expected(item, data)
    for key, label in [('contract_amount', '合同金额'), ('budget_cost', '目标成本'), ('remaining_cost', '预计剩余成本'), ('received_amount', '已收款'), ('approved_change_amount', '已批准变更金额')]:
        item[key] = number(data.get(key, item.get(key)), label, nullable=True)
    item['note'] = text(data.get('note'), '确认依据', True)
    return {'financial': save(store, con, 'financials', item, '更新经营基准：' + p['name'])}


def save_delivery(store, con, data):
    p = project(store, con, data.get('project_id'))
    item = {'id': uid('shipment'), 'project_id': p['id'], 'scope': text(data.get('scope'), '交付部件、设备或区域', True, 500),
            'quantity': number(data.get('quantity'), '本次交付数量', positive=True), 'unit': text(data.get('unit'), '单位', True, 30),
            'delivered_on': day(data.get('delivered_on'), '交付日期', True), 'reference': text(data.get('reference'), '签收单或运单号', True, 300),
            'note': text(data.get('note'), '交付备注'), 'created_at': stamp()}
    store.put(con, 'shipments', item)
    store.event(con, p['id'], 'partial_delivery', '分批交付：' + item['scope'], delivery_id=item['id'], quantity=item['quantity'], unit=item['unit'])
    return {'delivery': item}


def save_change(store, con, data):
    project_data = project(store, con, data.get('project_id'))
    item = base(store, con, 'change_orders', data, project_data)
    if item.get('status') in ('approved', 'rejected'):
        fail('已签认变更保留原记录，后续调整请建立新变更单', 409)
    status = data.get('status', 'pending')
    if status not in ('pending', 'approved', 'rejected'):
        fail('变更状态无效')
    ids = data.get('task_ids', [])
    if not isinstance(ids, list) or len(ids) > 500 or any(not isinstance(i, str) for i in ids):
        fail('影响任务列表无效')
    for identifier in ids:
        task_for(store, con, identifier, project_data['id'])
    item.update(title=text(data.get('title'), '变更内容', True, 300), scope=text(data.get('scope'), '区域、柜号或设备编号', True, 500),
                task_ids=list(dict.fromkeys(ids)), status=status,
                amount=number(data.get('amount'), '变更收入金额', nullable=True),
                estimated_cost=number(data.get('estimated_cost'), '预计追加成本', nullable=True),
                owner_id=owner(store, con, data.get('owner_id'), project_data), due_date=day(data.get('due_date'), '签认期限'),
                decision_reference=text(data.get('decision_reference'), '签认凭据或审批编号', status != 'pending'),
                note=text(data.get('note'), '变更说明', True), revision=project_data['revision'])
    if status == 'approved' and (item['amount'] is None or item['estimated_cost'] is None):
        fail('签认通过前请确认变更收入和预计成本，无费用请明确填 0')
    if status != 'pending':
        item['decided_at'] = stamp()
    return {'change': save(store, con, 'change_orders', item, '记录变更签认：' + item['title'])}


def save_milestone(store, con, data):
    project_data = project(store, con, data.get('project_id'), writable=False)
    item = base(store, con, 'contract_milestones', data, project_data)
    stages = ['planned', 'accepted', 'claimed', 'invoiced', 'paid']
    status = data.get('status', item.get('status', 'planned'))
    if status not in stages:
        fail('合同节点状态无效')
    prior = item.get('status', 'planned')
    # Historical records may enter with an explicit document; subsequent state
    # changes proceed one stage at a time and cannot silently erase evidence.
    if data.get('id') and not 0 <= stages.index(status) - stages.index(prior) <= 1:
        fail('请按验收、申报、开票、收款顺序推进节点', 409)
    amount = number(data.get('amount', item.get('amount')), '合同节点金额', positive=True)
    received = number(data.get('received_amount', item.get('received_amount', 0)), '本节点已收金额')
    if received > amount or received < item.get('received_amount', 0):
        fail('已收款不能超过节点金额或覆盖为较小数量')
    if status == 'paid' and received != amount:
        fail('标为已收款前须收齐本节点金额；部分收款保留在开票阶段')
    item.update(name=text(data.get('name', item.get('name')), '合同节点', True, 200),
                scope=text(data.get('scope', item.get('scope')), '关联区域、柜号或设备', True, 500),
                amount=amount, received_amount=received, due_date=day(data.get('due_date', item.get('due_date')), '约定回款日'), status=status,
                reference=text(data.get('reference', item.get('reference')), '验收、申报或收款凭据', status != 'planned'),
                note=text(data.get('note'), '节点依据', True))
    return {'milestone': save(store, con, 'contract_milestones', item, '更新合同节点：' + item['name'])}


def build(store, con, project_id=None, factory_type=None, include_demo=False):
    projects = [p for p in store.all(con, 'projects') if not p.get('archived') and (include_demo or not p.get('demo'))
                and (not project_id or p['id'] == project_id) and (not factory_type or p.get('factory_type', 'cabinet') == factory_type)]
    ids = {p['id'] for p in projects}
    active = {p['id'] for p in projects if not fulfillment.is_closed(p)}
    def rows(kind):
        return [x for x in store.all(con, kind) if x.get('project_id') in ids]
    tasks = [t for t in rows('tasks') if not t.get('archived') and t['status'] != 'invalidated']
    materials = [material_view(x) for x in rows('materials')]
    issues, costs, financials, inspections = rows('issues'), rows('actual_costs'), rows('financials'), rows('inspections')
    changes, milestones = rows('change_orders'), rows('contract_milestones')
    checks = [check_sheet(store, con, t) for t in tasks if t.get('start_checks')]
    for t in tasks:
        t['readiness_blockers'] = start_blockers(store, con, t)
    actions = []
    def action(kind, record_id, pid, title, owner_id=None, due_date=None, task_id=None, severity='warning'):
        actions.append({'id': kind + ':' + record_id, 'type': kind, 'project_id': pid, 'task_id': task_id, 'title': title,
                        'owner_id': owner_id, 'due_date': due_date, 'severity': severity,
                        'href': '#page=readiness&project=' + pid})
    for m in materials:
        if m['project_id'] in active and m['shortage_quantity']:
            action('material', m['id'], m['project_id'], m['name'] + ' 缺 ' + str(m['shortage_quantity']) + m['unit'], m.get('owner_id'), m.get('expected_date'))
    for i in issues:
        if i['project_id'] in active and i['status'] != 'resolved':
            action('issue', i['id'], i['project_id'], i['title'], i.get('owner_id'), i.get('due_date'), i.get('task_id'))
    for t in tasks:
        if t['project_id'] not in active or t['status'] in ('done', 'invalidated'):
            continue
        if t['status'] == 'blocked':
            action('pause', t['id'], t['project_id'], t['title'] + ' · ' + (t.get('pause_note') or '暂停待处理'), t.get('assignee'), task_id=t['id'])
        if t.get('rework_of'):
            action('rework', t['id'], t['project_id'], t['title'], t.get('assignee'), task_id=t['id'])
    economics = []
    today = date.today().isoformat()
    for change in changes:
        if change['status'] == 'pending' and change['project_id'] in active:
            action('change', change['id'], change['project_id'], '待签认：' + change['title'], change.get('owner_id'), change.get('due_date'))
    for milestone in milestones:
        if milestone['status'] == 'accepted':
            action('milestone', milestone['id'], milestone['project_id'], '已验收待申报：' + milestone['name'], due_date=milestone.get('due_date'))
        elif milestone['status'] != 'paid' and milestone.get('due_date') and milestone['due_date'] < today:
            action('milestone', milestone['id'], milestone['project_id'], '合同节点回款待处理：' + milestone['name'], due_date=milestone['due_date'])
    for p in projects:
        f = next((r for r in financials if r['project_id'] == p['id']), {})
        actual = round(sum(r['amount'] for r in costs if r['project_id'] == p['id']), 2)
        total_revenue = None if f.get('contract_amount') is None or f.get('approved_change_amount') is None else f['contract_amount'] + f['approved_change_amount']
        forecast_cost = None if f.get('remaining_cost') is None else round(actual + f['remaining_cost'], 2)
        margin = None if forecast_cost is None or total_revenue is None else round(total_revenue - forecast_cost, 2)
        economics.append({'project_id': p['id'], 'actual_cost': actual, 'cost_record_count': sum(c['project_id'] == p['id'] for c in costs),
                          'contract_total': total_revenue, 'budget_cost': f.get('budget_cost'), 'forecast_cost': forecast_cost,
                          'forecast_profit': margin, 'received_amount': f.get('received_amount'),
                          'unreceived_amount': None if total_revenue is None or f.get('received_amount') is None else round(total_revenue - f['received_amount'], 2)})
        if p['id'] in active:
            if p.get('due_date') and p['due_date'] < today:
                action('overdue', p['id'], p['id'], p['name'] + ' 已过交期', due_date=p['due_date'], severity='danger')
            if forecast_cost is not None and f.get('budget_cost') is not None and forecast_cost > f['budget_cost']:
                action('cost', p['id'], p['id'], p['name'] + ' 预计超出目标成本 ' + str(round(forecast_cost - f['budget_cost'], 2)), severity='danger')
    current_inspections = {}
    for i in inspections:
        current_inspections[(i['task_id'], i['revision'])] = i
    return {'materials': materials, 'issues': issues, 'checks': checks, 'inspections': inspections, 'costs': costs,
            'financials': financials, 'deliveries': rows('shipments'), 'changes': changes, 'milestones': milestones, 'projects': projects, 'tasks': tasks,
            'people': store.all(con, 'people'), 'actions': actions, 'economics': economics,
            'work_sessions': rows('work_sessions'), 'scenarios': [], 'calibrations': [],
            'metrics': {'open_projects': len(active), 'material_shortages': sum(m['project_id'] in active and m['shortage_quantity'] > 0 for m in materials),
                        'open_issues': sum(i['project_id'] in active and i['status'] != 'resolved' for i in issues),
                        'paused_tasks': sum(t['project_id'] in active and t['status'] == 'blocked' for t in tasks),
                        'actual_cost': round(sum(c['amount'] for c in costs), 2), 'cost_records': len(costs),
                        'financial_coverage': sum(f.get('contract_amount') is not None for f in financials),
                        'failed_inspections': sum(i['result'] == 'failed' for i in current_inspections.values()),
                        'unowned_actions': sum(not a.get('owner_id') for a in actions)}}
