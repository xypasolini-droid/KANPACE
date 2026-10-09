"""WiFi pairing/transport tests use isolated PTY plus loopback HTTP emulator."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from device_bridge import DeviceBridge, DeviceError
from test_device_bridge import BadgeEmulator, PTYSerial, POSIX_PTY_AVAILABLE


@unittest.skipUnless(POSIX_PTY_AVAILABLE, 'WiFi 协议模拟依赖 POSIX pseudo-terminal；Windows 跳过')
class WiFiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name)
        self.badge = BadgeEmulator()
        self.bridge = DeviceBridge(self.store, serial_factory=PTYSerial,
            port_provider=lambda: [SimpleNamespace(device=self.badge.port, vid=0x303A)],
            handshake_timeout=.35, receipt_timeout=.3)
        self.badge.reply_extra = self.usb_reply
        with self.store.connect() as con:
            self.task = next(t for t in self.store.all(con, 'tasks') if t['status'] != 'done')
        self.http_requests = []
        self.http_mode = 'normal'
        self.token = None
        owner = self
        class BadgeHTTP(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                frame = json.loads(body)
                owner.http_requests.append(dict(path=self.path, auth=self.headers.get('Authorization'), body=frame))
                if owner.http_mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', 'https://example.invalid/steal')
                    self.end_headers()
                    return
                if self.headers.get('Authorization') != 'Bearer ' + str(owner.token):
                    self.send_response(401)
                    self.end_headers()
                    return
                reply = owner.response(frame)
                if owner.http_mode == 'wrong_device':
                    reply['device_id'] = 'another-board'
                raw = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), BadgeHTTP)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.original_build = urllib.request.build_opener
        def build_mapped_opener(*handlers):
            real = self.original_build(*handlers)
            class MappedOpener:
                def open(inner, request, timeout):
                    # Preserve production validation and real HTTP behavior; only
                    # route this test's recorded RFC1918 address to the emulator.
                    self.assertTrue(request.full_url.startswith('http://192.168.42.9/cabinet/'))
                    mapped = urllib.request.Request(request.full_url.replace('http://192.168.42.9',
                        'http://127.0.0.1:' + str(self.http.server_port)),
                        data=request.data, headers=dict(request.headers), method=request.method)
                    return real.open(mapped, timeout=timeout)
            return MappedOpener()
        self.mapping = patch('urllib.request.build_opener', build_mapped_opener)
        self.mapping.start()

    def tearDown(self):
        self.mapping.stop()
        self.bridge.disconnect()
        self.badge.close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def response(self, frame):
        result = dict(type=frame['type'], protocol=1, request_id=frame['request_id'], device_id=self.badge.hello_device_id)
        if frame['type'] == 'hello':
            result.update(chip='ESP32-C3', firmware='cabinet-badge-1')
        elif frame['type'] == 'wifi_config':
            self.token = frame['token']
            result.update(configured=True)
        elif frame['type'] == 'wifi_status':
            result.update(connected=True, configured=True, ssid='Test Factory', ip='192.168.42.9', rssi=-49)
        elif frame['type'] == 'wifi_scan':
            result.update(networks=[dict(ssid='Test Factory', rssi=-49, secure=True)], scan_pending=False)
        elif frame['type'] == 'task':
            result.update(type='ack', delivery_id=frame['delivery_id'], task_id=frame['task']['id'],
                          revision=frame['task']['revision'], received=True)
        return result

    def usb_reply(self, frame):
        if frame['type'].startswith('wifi_'):
            self.badge.send(self.response(frame))

    def pair(self):
        self.bridge.connect(self.badge.port)
        self.bridge.wifi_config('Test Factory', 'example-test-pass')
        self.bridge.wifi_status()

    def test_usb_pairing_secrets_are_private_and_not_returned(self):
        self.bridge.connect(self.badge.port)
        scan = self.bridge.wifi_scan()
        self.assertEqual(scan['wifi']['networks'][0]['ssid'], 'Test Factory')
        config = self.bridge.wifi_config('Test Factory', 'example-test-pass')
        self.assertTrue(config['wifi']['configured'])
        self.assertFalse(config['wifi']['connected'], 'config success is not connected proof')
        result = self.bridge.wifi_status()
        self.assertTrue(result['wifi']['connected'])
        self.assertFalse(result['wifi']['cached'])
        self.assertEqual(result['wifi']['ip'], '192.168.42.9')
        secret_file = Path(self.temp.name) / 'device-secrets.json'
        self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600)
        contents = secret_file.read_text()
        self.assertIn(self.token, contents)
        self.assertNotIn('example-test-pass', contents)
        visible = json.dumps([scan, config, result, self.bridge.snapshot(), self.bridge.deliveries()])
        self.assertNotIn(self.token, visible)
        self.assertNotIn('example-test-pass', visible)
        self.assertNotIn('password', visible)

    def test_usb_wifi_scan_error_is_immediate_preserves_results_and_hides_extra_fields(self):
        self.bridge.connect(self.badge.port)
        original_networks = self.bridge.wifi_scan()['wifi']['networks']
        def reject_scan(frame):
            if frame['type'] == 'wifi_scan':
                self.badge.send(dict(type='error', protocol=1, request_id=frame['request_id'],
                    device_id=self.badge.hello_device_id, error='wifi_scan_failed',
                    password='private-test-password', token='private-test-token',
                    networks=[], scan_elapsed_ms=6000, driver_scan_state=-2))
        self.badge.reply_extra = reject_scan
        started = time.monotonic()
        with self.assertRaises(DeviceError) as raised:
            self.bridge.wifi_scan()
        self.assertLess(time.monotonic()-started, 1.0, 'matching error must not wait for the 4-second RPC timeout')
        self.assertEqual(raised.exception.status, 409)
        self.assertIn('无线扫描失败', raised.exception.message)
        self.assertIn('wifi_scan_failed', raised.exception.message)
        self.assertNotIn('未收到', raised.exception.message)
        self.assertIsNone(raised.exception.details, 'raw firmware fields must not be exposed in API errors')
        state = self.bridge.snapshot()['device']
        self.assertEqual(state['wifi']['networks'], original_networks)
        self.assertEqual(state['last_error'], raised.exception.message)
        self.assertEqual(state['state'], 'ready', 'a scan failure does not imply USB transport failure')
        visible = json.dumps([state, raised.exception.message, raised.exception.details])
        for secret in ('private-test-password', 'private-test-token', 'driver_scan_state', 'scan_elapsed_ms'):
            self.assertNotIn(secret, visible)
        self.assertEqual(self.bridge._rpcs, {})
        self.badge.reply_extra = self.usb_reply
        self.assertEqual(self.bridge.wifi_scan()['wifi']['networks'], original_networks)
        self.assertIsNone(self.bridge.snapshot()['device']['last_error'])

    def test_usb_wifi_scan_ignores_error_for_wrong_request_or_device(self):
        self.bridge.connect(self.badge.port)
        def wrong_then_valid(frame):
            if frame['type'] != 'wifi_scan':
                return
            base = dict(type='error', protocol=1, request_id=frame['request_id'],
                        device_id=self.badge.hello_device_id, error='wifi_scan_failed')
            self.badge.send(dict(base, request_id='different-request'))
            self.badge.send(dict(base, device_id='different-device'))
            self.badge.send(self.response(frame))
        self.badge.reply_extra = wrong_then_valid
        result = self.bridge.wifi_scan()
        self.assertEqual(result['wifi']['networks'][0]['ssid'], 'Test Factory')
        self.assertIsNone(result['device']['last_error'])
        self.assertEqual(self.bridge._rpcs, {})

    def test_wifi_http_handshake_task_ack_and_status(self):
        self.pair()
        self.assertEqual(self.bridge.connect(transport='wifi', host='192.168.42.9')['device']['state'], 'ready')
        result = self.bridge.send_task(self.task['id'], True)
        self.assertEqual(result['delivery']['status'], 'received')
        self.assertEqual(result['delivery']['transport'], 'wifi')
        self.assertEqual(result['delivery']['host'], '192.168.42.9')
        self.assertNotIn(self.token, json.dumps(result))
        status = self.bridge.wifi_status()
        self.assertFalse(status['wifi']['cached'])
        self.assertEqual(self.http_requests[-1]['path'], '/cabinet/wifi_status')
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id']), self.task)
            self.assertNotIn(self.token, json.dumps(self.store.all(con, 'events')))
        self.assertTrue(all(req['auth'] == 'Bearer ' + self.token for req in self.http_requests))

    def test_wifi_preserves_recorded_partial_progress_and_pause_context(self):
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', self.task['id'])
            task.update(quantity=18, completed_quantity=7, progress_recorded=True,
                        status='blocked', priority=2, pause_reason='material',
                        pause_note='侧板材料待到', handover_note='已做七件留在A架', execution_version=9)
            self.store.put(con, 'tasks', task)
        self.pair()
        self.bridge.connect(transport='wifi', host='192.168.42.9')
        result = self.bridge.send_task(self.task['id'])
        self.assertEqual(result['delivery']['status'], 'received')
        body = next(req['body']['task'] for req in self.http_requests if req['path'] == '/cabinet/task')
        self.assertEqual((body['completed_quantity'], body['remaining_quantity']), (7, 11))
        self.assertEqual(body['pause_reason'], 'material')
        self.assertEqual(body['priority'], 2)
        self.assertEqual(body['handover_note'], '已做七件留在A架')
        with self.store.connect() as con:
            unchanged = self.store.get(con, 'tasks', self.task['id'])
            self.assertEqual(unchanged['status'], 'blocked')
            self.assertEqual(unchanged['completed_quantity'], 7)

    def test_public_unobserved_and_url_hosts_are_rejected_without_http(self):
        self.pair()
        for host in ('8.8.8.8', '127.0.0.1', '169.254.0.1', 'example.com', 'http://192.168.42.9',
                     '192.168.42.9:80', '192.168.42.10', '::1'):
            with self.subTest(host=host), self.assertRaises(DeviceError):
                self.bridge.connect(transport='wifi', host=host)
        self.assertEqual(self.http_requests, [])
        self.assertEqual(self.bridge.snapshot()['device']['transport'], 'usb')

    def test_wifi_identity_mismatch_does_not_become_connected(self):
        self.pair()
        self.http_mode = 'wrong_device'
        with self.assertRaises(DeviceError):
            self.bridge.connect(transport='wifi', host='192.168.42.9')
        self.assertFalse(self.bridge.snapshot()['device']['connected'])
        self.assertEqual(self.bridge.snapshot()['device']['state'], 'error')

    def test_redirect_is_not_followed(self):
        self.pair()
        self.http_mode = 'redirect'
        with self.assertRaises(DeviceError) as raised:
            self.bridge.connect(transport='wifi', host='192.168.42.9')
        self.assertIn('302', str(raised.exception))
        self.assertEqual(len(self.http_requests), 1)
        self.assertFalse(self.bridge.snapshot()['device']['connected'])

    def test_wifi_credentials_cannot_be_written_over_wifi(self):
        self.pair()
        self.bridge.connect(transport='wifi', host='192.168.42.9')
        with self.assertRaises(DeviceError):
            self.bridge.wifi_config('Another network', 'other-password')
        self.assertEqual(len(self.http_requests), 1)

    def test_wifi_status_failure_clears_online_state(self):
        self.pair()
        self.bridge.connect(transport='wifi', host='192.168.42.9')
        self.token = 'changed-on-device'
        with self.assertRaises(DeviceError):
            self.bridge.wifi_status()
        state = self.bridge.snapshot()['device']
        self.assertEqual(state['state'], 'error')
        self.assertFalse(state['connected'])
        self.assertFalse(state['wifi']['connected'])
        self.assertTrue(state['wifi']['cached'])
        self.assertIn('401', state['last_error'])

    def test_wifi_send_failure_records_unconfirmed_and_clears_online_state(self):
        self.pair()
        self.bridge.connect(transport='wifi', host='192.168.42.9')
        self.token = 'changed-on-device'
        with self.assertRaises(DeviceError):
            self.bridge.send_task(self.task['id'])
        delivery = self.bridge.deliveries()['deliveries'][0]
        self.assertEqual(delivery['status'], 'failed')
        self.assertIsNone(delivery['received_at'])
        self.assertFalse(self.bridge.snapshot()['device']['connected'])
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'tasks', self.task['id']), self.task)

    def test_cached_status_and_token_survive_server_restart_without_password(self):
        self.pair()
        self.bridge.disconnect()
        self.assertTrue(self.bridge.wifi_status()['wifi']['cached'])
        replacement = DeviceBridge(self.store, serial_factory=PTYSerial, port_provider=lambda: [])
        self.bridge = replacement
        self.assertEqual(replacement.snapshot()['device']['wifi']['ip'], '192.168.42.9')
        self.assertTrue(replacement.snapshot()['device']['wifi']['cached'])
        self.assertEqual(replacement.connect(transport='wifi', host='192.168.42.9')['device']['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
