"""Real POSIX PTY transport checks; no physical device or production database."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_device_bridge as device_fixture


@unittest.skipUnless(device_fixture.POSIX_PTY_AVAILABLE, 'POSIX pseudo-terminal required')
class BadgeExecutionTransportTests(device_fixture.DeviceBridgeTests):
    # Reuse the PTY fixture but do not inherit the unrelated delivery test suite.
    def setUp(self):
        super().setUp()
        self.calls = []
        self.bridge._execution_handler = self.handle_event
        self.connect_badge()

    def handle_event(self, frame):
        self.calls.append(copy.deepcopy(frame))
        return dict(accepted=True, code='accepted', task=self.task)

    def frame(self, **updates):
        event = dict(type='execution_event', protocol=1,
                     event_id='badge_evt_001', device_id=self.badge.hello_device_id,
                     task_id=self.task['id'], delivery_id='delivery_test_001',
                     revision=self.task['revision'], execution_version=self.task['execution_version'],
                     action='start')
        event.update(updates)
        return event

    def ack(self, event):
        before = len(self.badge.messages)
        self.badge.send(event)
        self.wait_for(lambda: any(m.get('type') == 'execution_ack' for m in self.badge.messages[before:]))
        return next(m for m in self.badge.messages[before:] if m.get('type') == 'execution_ack')

    def test_business_ack_has_latest_snapshot_and_distinct_type(self):
        ack = self.ack(self.frame())
        self.assertTrue(ack['accepted'])
        self.assertEqual(ack['event_id'], 'badge_evt_001')
        self.assertEqual(ack['task']['id'], self.task['id'])
        self.assertIn('project_name', ack['task'])
        self.assertIn('requires_web_inspection', ack['task'])
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('received', ack)

    def test_wrong_device_cannot_reach_business_handler(self):
        self.badge.send(self.frame(device_id='different_badge'))
        self.ack(self.frame(event_id='probe_correct'))
        self.assertEqual([f['event_id'] for f in self.calls], ['probe_correct'])

    def test_unknown_event_action_is_rejected_before_business(self):
        ack = self.ack(self.frame(action='delete'))
        self.assertFalse(ack['accepted'])
        self.assertFalse(ack['retryable'])
        self.assertEqual(ack['code'], 'invalid_event')
        self.assertEqual(self.calls, [])

    def test_finish_requires_confirmed_integer_total(self):
        for values in ({}, {'completed_quantity': True}, {'completed_quantity': 1.5}, {'completed_quantity': -1}):
            ack = self.ack(self.frame(action='finish', **values))
            self.assertFalse(ack['accepted'])
        self.assertEqual(self.calls, [])

    def test_versions_do_not_accept_booleans_or_floats(self):
        for field in ('revision', 'execution_version'):
            for bad in (True, 1.0, -1, '1'):
                ack = self.ack(self.frame(**{field: bad}))
                self.assertEqual(ack['code'], 'invalid_event')
        self.assertEqual(self.calls, [])

    def test_transient_failure_requests_same_event_retry_without_disconnect(self):
        def unavailable(_):
            raise RuntimeError('private database details must not be sent')
        self.bridge._execution_handler = unavailable
        ack = self.ack(self.frame())
        self.assertFalse(ack['accepted'])
        self.assertTrue(ack['retryable'])
        self.assertNotIn('private', ack['message'])
        self.assertEqual(self.bridge.snapshot()['device']['state'], 'ready')
        self.bridge._execution_handler = self.handle_event
        self.assertTrue(self.ack(self.frame())['accepted'])

    def test_business_rejection_not_marked_as_received_or_complete(self):
        self.bridge._execution_handler = lambda frame: dict(accepted=False, code='stale_version', message='任务已更新', task=self.task)
        ack = self.ack(self.frame())
        self.assertFalse(ack['accepted'])
        self.assertFalse(ack['retryable'])
        self.assertEqual(ack['code'], 'stale_version')
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id']), self.task)

    def test_delivery_receipt_never_invokes_execution_handler(self):
        self.badge.reply_task = self.badge.ack
        result = self.bridge.send_task(self.task['id'], test_mode=True)
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        self.assertEqual(self.calls, [])
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id']), self.task)

    def test_pause_has_validated_reason_and_preserves_worker_note(self):
        for reason in ('material', 'equipment', 'quality', 'urgent', 'other'):
            ack = self.ack(self.frame(action='pause', reason=reason, note='工牌确认暂停', handover_note='进度保留'))
            self.assertTrue(ack['accepted'])
            self.assertEqual(self.calls[-1]['reason'], reason)
        self.assertFalse(self.ack(self.frame(action='pause', reason='unknown'))['accepted'])

    def test_missing_business_handler_keeps_event_retryable(self):
        self.bridge._execution_handler = None
        ack = self.ack(self.frame())
        self.assertTrue(ack['retryable'])
        self.assertEqual(ack['code'], 'execution_unavailable')

    def test_large_concurrent_task_edit_cannot_trap_accepted_event_in_retry_loop(self):
        changed = copy.deepcopy(self.task)
        changed.update(execution_version=self.task['execution_version'] + 1, status='in_progress',
                       source={'raw': 'X' * 7800})
        with self.store.connect() as con:
            self.store.put(con, 'tasks', changed)
        ack = self.ack(self.frame())
        self.assertTrue(ack['accepted'])
        self.assertTrue(ack['task']['refresh_required'])
        self.assertFalse(ack['task']['execution_allowed'])
        self.assertEqual(ack['task']['execution_version'], changed['execution_version'])
        self.assertIn('重新下发', ack['message'])
        self.assertNotIn('raw', ack['task']['source'])

    def test_delivery_binds_assignee_for_later_business_validation(self):
        self.badge.reply_task = self.badge.ack
        self.bridge.send_task(self.task['id'], test_mode=True)
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        delivery = self.last_delivery()
        self.assertEqual(delivery['assignee_id'], self.task['assignee'])
        self.assertEqual(delivery['execution_version'], self.task['execution_version'])


# unittest's default loader otherwise runs inherited delivery tests a second time.
for _name in list(vars(device_fixture.DeviceBridgeTests)):
    if _name.startswith('test_') and _name not in vars(BadgeExecutionTransportTests):
        setattr(BadgeExecutionTransportTests, _name, None)


if __name__ == '__main__':
    unittest.main()
