"""USB protocol tests use a real POSIX pseudo-terminal, never a physical board."""
import copy
import json
import os
from pathlib import Path
import select
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request

POSIX_PTY_AVAILABLE = os.name == 'posix'
if POSIX_PTY_AVAILABLE:
    import pty
    import tty
else:
    pty = tty = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from device_bridge import DeviceBridge, DeviceError


class PTYSerial:
    """pyserial-shaped adapter to an actual isolated pty, with no dependency."""
    def __init__(self, port=None, baudrate=115200, timeout=.15, write_timeout=1):
        self.port, self.timeout, self.write_timeout = port, timeout, write_timeout
        self.fd = None

    def open(self):
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(self.fd)

    def read(self, size):
        fd = self.fd
        if fd is None:
            return b''
        ready, _, _ = select.select([fd], [], [], self.timeout)
        return os.read(fd, size) if ready else b''

    def write(self, data):
        # Match pyserial's complete-buffer write contract. macOS PTYs can accept
        # only part of a large JSON frame even when the peer is reading.
        offset, deadline = 0, time.monotonic() + self.write_timeout
        while offset < len(data):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('isolated PTY write timed out')
            _, ready, _ = select.select([], [self.fd], [], remaining)
            if ready:
                try:
                    offset += os.write(self.fd, data[offset:])
                except BlockingIOError:
                    continue
        return offset

    def close(self):
        fd, self.fd = self.fd, None
        if fd is not None:
            os.close(fd)


class BadgeEmulator:
    def __init__(self):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        os.set_blocking(self.master, False)
        self.port = os.ttyname(self.slave)
        self.stop = threading.Event()
        self.messages = []
        self.received_bytes = bytearray()
        self.announce = True
        self.reply_hello = True
        self.hello_device_id = 'pty-badge-01'
        self.reply_task = None
        self.reply_extra = None
        self.write_lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def send_raw(self, data):
        with self.write_lock:
            offset, deadline = 0, time.monotonic() + 2
            while offset < len(data) and not self.stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('isolated badge emulator write timed out')
                _, ready, _ = select.select([], [self.master], [], .05)
                if ready:
                    try:
                        offset += os.write(self.master, data[offset:])
                    except BlockingIOError:
                        continue

    def send(self, frame):
        self.send_raw(json.dumps(frame, ensure_ascii=False).encode() + b'\n')

    def ack(self, message, **updates):
        result = dict(type='ack', protocol=1, delivery_id=message['delivery_id'],
            request_id=message['request_id'], task_id=message['task']['id'],
            revision=message['task']['revision'], device_id=self.hello_device_id, received=True)
        result.update(updates)
        self.send(result)

    def run(self):
        pending = b''
        next_announcement = time.monotonic() + .05
        while not self.stop.is_set():
            try:
                if self.announce and time.monotonic() >= next_announcement:
                    self.send(dict(type='hello', protocol=1, device_id=self.hello_device_id,
                                   chip='ESP32-C3', firmware='cabinet-badge-1'))
                    next_announcement = time.monotonic() + .1
                ready, _, _ = select.select([self.master], [], [], .05)
                if not ready:
                    continue
                chunk = os.read(self.master, 16384)
                self.received_bytes.extend(chunk)
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    try:
                        msg = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    self.messages.append(msg)
                    if msg.get('type') == 'hello' and self.reply_hello:
                        self.send(dict(type='hello', protocol=1, request_id=msg['request_id'],
                                       device_id=self.hello_device_id, chip='ESP32-C3', firmware='cabinet-badge-1'))
                    if msg.get('type') == 'task' and self.reply_task:
                        self.reply_task(msg)
                    if self.reply_extra:
                        self.reply_extra(msg)
            except OSError:
                break

    def close(self):
        self.stop.set()
        self.thread.join(1)
        os.close(self.master)
        os.close(self.slave)


@unittest.skipUnless(POSIX_PTY_AVAILABLE, '设备模拟测试需要 POSIX pseudo-terminal；Windows 跳过')
class DeviceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name)
        self.badge = BadgeEmulator()
        self.bridge = DeviceBridge(self.store, serial_factory=PTYSerial,
            port_provider=lambda: [SimpleNamespace(device=self.badge.port, vid=0x303A)],
            handshake_timeout=.35, receipt_timeout=.3)
        with self.store.connect() as con:
            self.task = next(t for t in self.store.all(con, 'tasks') if t['status'] != 'done')
            self.project = self.store.get(con, 'projects', self.task['project_id'])

    def tearDown(self):
        self.bridge.disconnect()
        self.badge.close()
        self.temp.cleanup()

    def wait_for(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('condition did not become true')

    def last_delivery(self):
        return self.bridge.deliveries()['deliveries'][0]

    def connect_badge(self):
        result = self.bridge.connect(self.badge.port)
        self.assertEqual(result['device']['state'], 'ready')
        self.assertEqual(result['device']['device_id'], 'pty-badge-01')
        return result

    def test_real_partial_progress_priority_and_handover_reach_badge_without_reporting_done(self):
        self.connect_badge()
        self.badge.reply_task = self.badge.ack
        values = dict(quantity=18, completed_quantity=7, progress_recorded=True,
            priority=3, status='blocked', pause_reason='urgent', pause_note='临时缺辅料，先让急单',
            handover_note='已做7件在木工区A架，孔位按R3核对', paused_at='2026-09-04T10:00:00Z',
            resumed_at=None, interrupted_by_task_id='task-urgent-2', execution_version=4)
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task.update(values)
            self.store.put(con, 'tasks', task)
        self.bridge.send_task(self.task['id'])
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        payload = self.last_delivery()['payload']['task']
        for key, value in values.items():
            self.assertEqual(payload[key], value)
        self.assertEqual(payload['remaining_quantity'], 11)
        with self.store.connect() as con:
            current = self.store.get(con, 'tasks', self.task['id'])
            self.assertEqual(current['status'], 'blocked')
            self.assertEqual(current['completed_quantity'], 7)
            self.assertEqual(current['execution_version'], 4)

    def test_legacy_unknown_progress_is_not_sent_as_actual_zero(self):
        self.connect_badge()
        self.badge.reply_task = self.badge.ack
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task.update(quantity=18, completed_quantity=0, progress_recorded=False)
            self.store.put(con, 'tasks', task)
        self.bridge.send_task(self.task['id'])
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        task = self.last_delivery()['payload']['task']
        self.assertFalse(task['progress_recorded'])
        self.assertIsNone(task['completed_quantity'])
        self.assertIsNone(task['remaining_quantity'])
        self.assertEqual(task['quantity'], 18)

    def test_legacy_order_packet_never_reuses_whole_cabinet_note_as_trade_instruction(self):
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task.update(packet_generated=True, rule_id='order-packet-v4', trade='木工',
                instructions='高密度板；不锈钢拉丝板；灯带')
            self.store.put(con, 'tasks', task)
            self.assertEqual(self.bridge._task_payload(con, task)['instructions'], '')
        self.connect_badge()
        with self.assertRaises(DeviceError) as caught:
            self.bridge.send_task(self.task['id'])
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse(self.bridge.deliveries()['deliveries'])

    def test_execution_fields_validate_whole_counts_and_consistency(self):
        payload = {'task':dict(id='t', project_id='p', project_name='测试项目', title='侧板 · 下料',
            trade='木工', assignee='', acceptance='', status='ready', revision=1, quantity=18,
            hours=1.25, source={}, progress_recorded=True, completed_quantity=7,
            remaining_quantity=11, priority=3, execution_version=4, pause_reason='material')}
        self.assertNotIn('instructions', payload['task'])  # Legacy badge payload.
        DeviceBridge._validate_task_payload(payload)
        for changes in ({'completed_quantity':True}, {'completed_quantity':7.5},
                        {'remaining_quantity':12}, {'priority':4}, {'execution_version':2147483648},
                        {'progress_recorded':'true'}, {'pause_reason':'invented'},
                        {'handover_note':{'not':'text'}}, {'paused_at':'x'*65},
                        {'instructions':{'not':'text'}}, {'instructions':'木工工序' * 700}):
            candidate = copy.deepcopy(payload)
            candidate['task'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(DeviceError):
                DeviceBridge._validate_task_payload(candidate)

    def test_long_execution_notes_are_rejected_before_serial_without_truncation(self):
        self.connect_badge()
        before = len([m for m in self.badge.messages if m.get('type') == 'task'])
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task.update(pause_note='缺料说明'*250, handover_note='交接记录'*500)
            self.store.put(con, 'tasks', task)
        with self.assertRaises(DeviceError) as raised:
            self.bridge.send_task(self.task['id'])
        self.assertEqual(raised.exception.status, 413)
        self.assertEqual(len([m for m in self.badge.messages if m.get('type') == 'task']), before)
        with self.store.connect() as con:
            current = self.store.get(con, 'tasks', self.task['id'])
            self.assertEqual(current['pause_note'], '缺料说明'*250)
            self.assertEqual(current['handover_note'], '交接记录'*500)

    def test_enumeration_does_not_open_or_write(self):
        result = self.bridge.snapshot()
        self.assertEqual(result['ports'][0]['port'], self.badge.port)
        self.assertFalse(result['device']['connected'])
        self.assertEqual(self.badge.messages, [])
        with self.assertRaises(DeviceError):
            self.bridge.connect('/tmp/unknown-port')
        with self.assertRaises(DeviceError):
            self.bridge.connect(self.badge.port, 9600)
        self.assertEqual(self.badge.messages, [])

    def test_only_a_matching_protocol_handshake_marks_ready(self):
        self.badge.reply_hello = False
        self.badge.send(dict(type='hello', protocol=1, request_id='old', device_id='fake', chip='ESP32-C3', firmware='fake'))
        with self.assertRaises(DeviceError) as raised:
            self.bridge.connect(self.badge.port)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.bridge.snapshot()['device']['state'], 'incompatible')
        self.assertFalse(self.bridge.snapshot()['device']['connected'])
        self.assertTrue(all(message['type'] == 'hello' for message in self.badge.messages))
        self.badge.reply_hello = True
        self.connect_badge()

    def test_legacy_ascii_firmware_receives_zero_host_bytes(self):
        self.badge.announce = False
        self.badge.reply_hello = False
        tty.tcflush(self.badge.slave, tty.TCIFLUSH)
        self.badge.send_raw(b'SparkLink ready: c=choice g=handshake s=SOS r=re-pair\n')
        with self.assertRaises(DeviceError) as raised:
            self.bridge.connect(self.badge.port)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.bridge.snapshot()['device']['state'], 'incompatible')
        self.assertIn('未向串口发送任何命令', str(raised.exception))
        self.assertEqual(bytes(self.badge.received_bytes), b'')
        self.assertEqual(self.badge.messages, [])

    def test_unrecognized_or_requested_announcements_do_not_enable_writes(self):
        self.badge.announce = False
        tty.tcflush(self.badge.slave, tty.TCIFLUSH)
        base = dict(type='hello', protocol=1, device_id=self.badge.hello_device_id,
                    chip='ESP32-C3', firmware='cabinet-badge-1')
        for changes in ({'firmware':'SparkLink'}, {'protocol':2}, {'device_id':''},
                        {'request_id':'not-an-unsolicited-announcement'}, {'chip':'ESP32'}):
            self.badge.send(dict(base, **changes))
        with self.assertRaises(DeviceError):
            self.bridge.connect(self.badge.port)
        self.assertEqual(bytes(self.badge.received_bytes), b'')
        self.badge.announce = True
        self.connect_badge()
        self.assertTrue(self.badge.messages)
        self.assertTrue(all(message['type'] == 'hello' for message in self.badge.messages))

    def test_written_is_not_received_and_timeout_persists(self):
        self.connect_badge()
        result = self.bridge.send_task(self.task['id'], True)
        self.assertEqual(result['delivery']['status'], 'sent')
        self.assertIsNone(result['delivery']['received_at'])
        self.wait_for(lambda: self.last_delivery()['status'] == 'timeout')
        self.assertIn('未收到', self.last_delivery()['error'])
        with self.store.connect() as con:
            current = self.store.get(con, 'tasks', self.task['id'])
        self.assertEqual(current, self.task)

    def test_verified_ack_preserves_chinese_and_never_changes_work_status(self):
        self.connect_badge()
        self.badge.reply_task = self.badge.ack
        result = self.bridge.send_task(self.task['id'])
        self.assertTrue(result['delivery']['test_mode'], 'demo cannot be sent as production')
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        frame = next(m for m in self.badge.messages if m['type'] == 'task')
        self.assertEqual(frame['task']['title'], self.task['title'])
        self.assertEqual(frame['task']['trade'], self.task['trade'])
        self.assertEqual(frame['task']['project_name'], self.project['name'])
        self.assertIsInstance(frame['task']['source'], dict)
        self.assertIsInstance(frame['task']['assignee'], str)
        self.assertTrue(self.last_delivery()['received_at'])
        with self.store.connect() as con:
            current = self.store.get(con, 'tasks', self.task['id'])
            events = self.store.all(con, 'events', self.task['project_id'])
        self.assertEqual(current, self.task)
        self.assertEqual(len([e for e in events if e['action'] == 'device_task_received']), 1)
        self.badge.ack(frame)
        time.sleep(.05)
        with self.store.connect() as con:
            events = self.store.all(con, 'events', self.task['project_id'])
        self.assertEqual(len([e for e in events if e['action'] == 'device_task_received']), 1)

    def test_trade_instructions_reach_badge_before_work_without_changing_task(self):
        self.connect_badge()
        self.badge.reply_task = self.badge.ack
        instructions = '木工：按 R3 图纸开料、铣槽与封边；核对板厚和孔位。'
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task['instructions'] = instructions
            self.store.put(con, 'tasks', task)
        self.bridge.send_task(self.task['id'])
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')
        frame = next(m for m in self.badge.messages if m['type'] == 'task')
        self.assertEqual(frame['task']['instructions'], instructions)
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id'])['instructions'], instructions)
            self.assertEqual(self.store.get(con, 'tasks', self.task['id'])['status'], self.task['status'])

    def test_mismatched_receipt_rejected_in_all_identity_fields(self):
        self.bridge.receipt_timeout = 2
        self.connect_badge()
        self.bridge.send_task(self.task['id'])
        self.wait_for(lambda: any(m['type'] == 'task' for m in self.badge.messages))
        frame = next(m for m in self.badge.messages if m['type'] == 'task')
        for key, value in [('device_id','someone-else'), ('revision',999), ('task_id','other'),
                           ('request_id','other'), ('delivery_id','other'), ('received',False), ('protocol',2)]:
            self.badge.ack(frame, **{key: value})
        self.badge.send_raw(b'garbage boot text\n' + b'x' * 20000 + b'\n')
        time.sleep(.15)
        self.assertEqual(self.last_delivery()['status'], 'sent')
        self.badge.ack(frame)
        self.wait_for(lambda: self.last_delivery()['status'] == 'received')

    def test_disconnection_records_unconfirmed_delivery_as_failed(self):
        self.connect_badge()
        self.bridge.send_task(self.task['id'])
        result = self.bridge.disconnect()
        self.assertEqual(result['device']['state'], 'disconnected')
        self.assertEqual(self.last_delivery()['status'], 'failed')
        self.assertIn('断开', self.last_delivery()['error'])

    def test_release_and_revision_guards_also_apply_to_test_mode(self):
        self.connect_badge()
        variants = [('tasks', self.task, {'archived': True}),
                    ('tasks', self.task, {'status':'done'}),
                    ('tasks', self.task, {'status':'invalidated'}),
                    ('tasks', self.task, {'revision':99}),
                    ('projects', self.project, {'revision':99}),
                    ('projects', self.project, {'status':'draft'}),
                    ('projects', self.project, {'released_revision':None})]
        for kind, original, updates in variants:
            with self.subTest(updates=updates):
                changed = dict(original, **updates)
                with self.store.connect() as con:
                    self.store.put(con, kind, changed)
                with self.assertRaises(DeviceError):
                    self.bridge.send_task(self.task['id'], True)
                with self.store.connect() as con:
                    self.store.put(con, kind, original)
        self.assertEqual(self.bridge.deliveries()['deliveries'], [])
        self.assertFalse(any(m['type'] == 'task' for m in self.badge.messages))

    def test_firmware_field_byte_limits_reject_before_serial_write(self):
        self.connect_badge()
        with self.store.connect() as con:
            self.store.put(con, 'projects', dict(self.project, name='柜' * 180))
        with self.assertRaises(DeviceError) as raised:
            self.bridge.send_task(self.task['id'])
        self.assertEqual(raised.exception.status, 413)
        self.assertIn('project_name', str(raised.exception))
        self.assertEqual(self.bridge.deliveries()['deliveries'], [])
        self.assertFalse(any(m['type'] == 'task' for m in self.badge.messages))

    def test_matching_firmware_rejection_is_not_left_as_timeout(self):
        self.connect_badge()
        def reject(frame):
            self.badge.send(dict(type='error', protocol=1, request_id=frame['request_id'],
                delivery_id=frame['delivery_id'], device_id=self.badge.hello_device_id, error='storage_write_failed'))
        self.badge.reply_task = reject
        self.bridge.send_task(self.task['id'])
        self.wait_for(lambda: self.last_delivery()['status'] == 'failed')
        self.assertIn('storage_write_failed', self.last_delivery()['error'])
        self.assertIsNone(self.last_delivery()['received_at'])
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id']), self.task)

    def test_unconnected_and_invalid_test_flag_are_rejected(self):
        with self.assertRaises(DeviceError):
            self.bridge.send_task(self.task['id'])
        with self.assertRaises(DeviceError):
            self.bridge.send_task(self.task['id'], 'true')
        self.assertEqual(self.bridge.deliveries()['deliveries'], [])

    def test_oversized_frame_is_not_partially_written(self):
        self.connect_badge()
        with self.store.connect() as con:
            oversized = dict(self.task, acceptance='验收' * 5000)
            self.store.put(con, 'tasks', oversized)
        with self.assertRaises(DeviceError) as raised:
            self.bridge.send_task(self.task['id'])
        self.assertEqual(raised.exception.status, 413)
        self.assertFalse(any(m['type'] == 'task' for m in self.badge.messages))
        self.assertEqual(self.bridge.deliveries()['deliveries'], [])

    def test_restart_marks_unconfirmed_audit_failed(self):
        self.connect_badge()
        self.bridge.send_task(self.task['id'])
        # Simulate a previous process disappearing before disconnect cleanup.
        self.bridge._pending.clear()
        self.bridge.disconnect()
        restarted = DeviceBridge(self.store, serial_factory=PTYSerial, port_provider=lambda: [])
        self.assertEqual(restarted.deliveries()['deliveries'][0]['status'], 'failed')
        self.assertIn('重启', restarted.deliveries()['deliveries'][0]['error'])
        restarted.disconnect()

    def test_http_device_endpoints_use_same_origin_and_persist_receipt(self):
        server = app.Server(('127.0.0.1', 0), self.store)
        server.device_bridge.disconnect()
        server.device_bridge = self.bridge
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, data=None, origin=None):
            headers = {'Content-Type':'application/json'}
            if origin:
                headers['Origin'] = origin
            body = None if data is None else json.dumps(data).encode()
            try:
                response = urllib.request.urlopen(urllib.request.Request(base+path, body, headers), timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)
        try:
            self.assertEqual(request('/api/device')[0], 200)
            self.assertEqual(request('/api/device/connect', {'port':self.badge.port}, 'https://evil.example')[0], 403)
            self.assertEqual(self.badge.messages, [])
            self.assertEqual(request('/api/device/connect', {'port':self.badge.port})[1]['device']['state'], 'ready')
            self.badge.reply_task = self.badge.ack
            code, result = request('/api/tasks/'+self.task['id']+'/send-device', {'test_mode':True})
            self.assertEqual(code, 200, result)
            self.assertEqual(result['delivery']['status'], 'sent')
            self.wait_for(lambda: self.last_delivery()['status'] == 'received')
            self.assertEqual(request('/api/device/deliveries')[1]['deliveries'][0]['status'], 'received')
            self.assertEqual(request('/api/device/disconnect', {})[1]['device']['state'], 'disconnected')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
