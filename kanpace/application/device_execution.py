"""DeviceExecutionService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from device_bridge import DeviceBridge, DeviceError
from kanpace.core.errors import APIError
from kanpace.core.validation import now
from kanpace.core.validation import uid
import hashlib
import json
import operations
import planning
import production


class DeviceExecutionService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def handle_device_execution(self, frame):
        DeviceBridge.validate_execution_frame(frame)
        digest = hashlib.sha256(json.dumps(frame, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            previous = next((e for e in self.store.all(con, 'badge_execution_events') if e['event_id'] == frame['event_id']), None)
            if previous:
                if previous['payload_hash'] != digest:
                    return {'accepted': False, 'code': 'event_id_conflict', 'message': '同一报工编号内容不同，请重新同步任务'}
                return dict(previous['result'], duplicate=True)
            task = None
            con.execute('SAVEPOINT badge_action')
            try:
                from device_bridge import DELIVERY_KIND
                delivery = self.store.get(con, DELIVERY_KIND, frame['delivery_id'])
                task = self.store.get(con, 'tasks', frame['task_id'])
                if delivery.get('status') != 'received' or delivery.get('test_mode'):
                    raise APIError(409, '任务尚未确认接收或为演示卡，不能报工')
                if any(delivery.get(key) != frame[key] for key in ('device_id', 'task_id', 'revision')):
                    raise APIError(409, '工牌与下发任务不匹配')
                if not delivery.get('assignee_id') or delivery['assignee_id'] != task.get('assignee'):
                    raise APIError(409, '负责人已变更，请重新下发任务')
                if task['revision'] != frame['revision']:
                    raise APIError(409, '图纸版本已变更，请重新下发任务')
                payload = {'expected_execution_version': frame['execution_version']}
                action = frame['action']
                if action == 'start':
                    task = self.store.set_status(con, task['id'], dict(payload, status='in_progress', note='工牌确认开工'))
                elif action == 'pause':
                    labels = {'material': '缺料', 'quality': '质量异常', 'equipment': '设备异常', 'urgent': '插单', 'other': '现场问题'}
                    note = frame.get('note') or '工牌确认' + labels[frame['reason']] + '暂停'
                    payload.update(reason=frame['reason'], note=note, handover_note=frame.get('handover_note') or note)
                    if 'completed_quantity' in frame:
                        payload['completed_quantity'] = frame['completed_quantity']
                    task = self.store.pause_task(con, task['id'], payload)
                elif action == 'resume':
                    task = self.store.resume_task(con, task['id'], dict(payload, note=frame.get('note') or '工牌确认暂停条件已解除'))
                elif action == 'label_confirm':
                    self.store.check_execution_version(task, payload)
                    self.store.daily_workflow.confirm_label(con, frame['label_id'],
                        {'task_id': task['id'], 'revision': frame['revision']}, device_id=frame['device_id'])
                    task = self.store.get(con, 'tasks', task['id'])
                else:
                    if task.get('inspection_required') or task.get('trade') == '质检' or (task.get('part_id') is None and task.get('process') == 'electrical'):
                        raise APIError(409, '请在质量验收中记录检验结果并确认完工')
                    if 'completed_quantity' not in frame:
                        raise APIError(400, '请明确确认本任务完成数量')
                    task = self.store.set_status(con, task['id'], dict(payload, status='done', completed_quantity=frame['completed_quantity'], note='工牌确认全部完成'))
                result = {'accepted': True, 'code': 'saved', 'message': '已记录', 'task': task}
                con.execute('RELEASE badge_action')
            except (APIError, production.ProductionError, operations.OperationError, planning.PlanningError) as exc:
                con.execute('ROLLBACK TO badge_action')
                con.execute('RELEASE badge_action')
                result = {'accepted': False, 'code': 'business_rejected', 'message': str(exc)}
                if task:
                    result['task'] = self.store.get(con, 'tasks', frame['task_id'])
            self.store.put(con, 'badge_execution_events', {'id': uid('badgeevent'), 'event_id': frame['event_id'],
                'project_id': task.get('project_id') if task else None, 'device_id': frame['device_id'],
                'payload_hash': digest, 'frame': frame, 'result': result, 'created_at': now()})
            return result
