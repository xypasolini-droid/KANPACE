"""Image transfer fault injection and one real PTY RPC integration path.

All files, serial peers, and projects are temporary. No physical board is used.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw
import app
import badge_media
from badge_image_transfer import BadgeImageTransfers, CHUNK_BYTES, KIND
from device_bridge import DeviceBridge, DeviceError
import test_device_bridge as serial_fixture


class ImagePeer:
    """Controllable decoder/storage peer with ordered and idempotent chunks."""
    def __init__(self, bridge, task):
        self.bridge, self.task = bridge, task
        self.calls, self.images = [], {}
        self.after = None
        self.mutate = None
        self.fail_once = None
        self.failed_once = False

    def rpc(self, frame_type, fields=None, **options):
        payload = copy.deepcopy(fields or {})
        self.calls.append((frame_type, payload, options))
        if options.get('expected_device_id') != 'test-badge':
            raise AssertionError('every image RPC must bind the expected badge')
        if frame_type == 'get_task':
            return {'type': 'status', 'task': copy.deepcopy(self.task)}
        action = frame_type.removeprefix('image_')
        if action == 'begin':
            self.images.setdefault(payload['image_id'], {'meta': payload, 'raw': bytearray(), 'committed': False})
        image = self.images[payload['image_id']]
        if action == 'chunk':
            raw = base64.b64decode(payload['data'], validate=True)
            offset = payload['offset']
            if offset == len(image['raw']):
                image['raw'].extend(raw)
            elif image['raw'][offset:offset + len(raw)] != raw:
                raise DeviceError(409, 'image_chunk_mismatch')
        reply = {'type': 'image_ack', 'action': action, 'image_id': payload['image_id'],
                 'offset': len(image['raw'])}
        if action == 'commit':
            self.assert_complete(image)
            image['committed'] = True
            reply.update(sha256=hashlib.sha256(image['raw']).hexdigest(), bytes=len(image['raw']),
                         context_id=image['meta']['context_id'])
        if self.after:
            self.after(action, payload, image)
        if self.mutate:
            reply = self.mutate(action, payload, reply)
        # Simulates the bytes already stored but an acknowledgement lost.
        if self.fail_once == action and not self.failed_once:
            self.failed_once = True
            raise DeviceError(504, 'lost ACK')
        return reply

    @staticmethod
    def assert_complete(image):
        if len(image['raw']) != image['meta']['bytes'] or hashlib.sha256(image['raw']).hexdigest() != image['meta']['sha256']:
            raise AssertionError('commit attempted with incomplete image bytes')


class BadgeImageTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = app.Store(self.root, seed=False)
        self.project = {'id': 'p', 'name': '工牌图片测试项目', 'revision': 1, 'released_revision': 1,
                        'status': 'released', 'fulfillment_status': 'active', 'demo': False}
        self.task = {'id': 't', 'project_id': 'p', 'revision': 1, 'status': 'ready', 'title': '开料',
                     'part_id': 'part', 'quantity': 1, 'trade': '木工', 'hours': 1, 'source': {}, 'execution_version': 0}
        with self.store.connect() as con:
            self.store.put(con, 'projects', self.project)
            self.store.put(con, 'tasks', self.task)
            self.store.put(con, 'parts', {'id': 'part', 'project_id': 'p', 'source': {'external_id': 'part-key'}})
        self.assets = self.root / 'drawing-previews' / 'assets'; self.assets.mkdir(parents=True)
        self.entry_paths = []
        self.drawing = self.make_image(1, '施工图')
        self.render = self.make_image(2, '效果图')
        self.write_manifest()
        self.bridge = DeviceBridge(self.store, serial_factory=lambda **_: None, port_provider=lambda: [])
        self.bridge._serial = object()
        self.bridge._state.update(state='ready', transport='usb', device_id='test-badge', image_support=True)
        self.peer = ImagePeer(self.bridge, self.task)
        self.bridge._usb_rpc = self.peer.rpc
        self.finished = threading.Event()
        original = self.bridge.images._run
        def completed(*args):
            try:
                original(*args)
            finally:
                self.finished.set()
        self.bridge.images._run = completed
        with self.store.connect() as con:
            self.items = badge_media.catalog(self.store, con, 'p')['items']
        self.ids = [item['id'] for item in self.items]
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.bridge.images.busy():
            self.finished.wait(3)
        self.temp.cleanup()

    def make_image(self, number, kind):
        image = Image.new('RGB', (300, 200), 'white')
        draw = ImageDraw.Draw(image)
        for y in range(10, 191, 20):
            draw.line((10, y, 290, 200-y), fill=('navy' if number == 1 else 'red'), width=2)
        name = hashlib.sha256(str(number).encode()).hexdigest() + '.png'
        path = self.assets / name; image.save(path); self.entry_paths.append(path)
        return {'url': '/api/drawing-media/assets/' + name, 'kind': kind, 'title': kind,
                'source_file': kind + '.png', 'page': 1}

    def write_manifest(self, *, include_drawing=True, linked=True):
        project = {'parts': {'part-key': [self.drawing]} if include_drawing and linked else {},
                   'sources': [self.drawing] if include_drawing else [], 'renders': [self.render]}
        (self.root / 'drawing-previews' / 'manifest.json').write_text(json.dumps({'projects': {'p': project}}))

    def launch(self, *, ids=None, mode='preview', automatic=False, **extra):
        self.finished.clear()
        data = {'project_id': 'p', 'mode': mode, 'asset_ids': self.ids if ids is None else ids, **extra}
        if mode == 'task':
            data.setdefault('task_id', 't')
        return self.bridge.images.start(data, automatic=automatic)

    def result(self):
        self.assertTrue(self.finished.wait(4), 'image worker did not finish')
        result = self.bridge.images.snapshot()['transfer']
        with self.store.connect() as con:
            saved = self.store.get(con, KIND, result['id'])
        self.assertEqual(saved['status'], result['status'])
        return result

    def assert_error(self, contains=None):
        result = self.result()
        self.assertEqual(result['status'], 'error', result)
        self.assertLess(result['progress'], 100)
        if contains:
            self.assertIn(contains, result['error'])
        with self.store.connect() as con:
            self.assertFalse([e for e in self.store.all(con, 'events') if e['action'] == 'device_images_received'])
        return result

    def test_six_slot_gallery_uses_distinct_slots_and_shared_storage_budget(self):
        drawings = [self.drawing]
        for number in range(3, 8):
            item = self.make_image(number, '施工图')
            path = self.entry_paths[-1]
            with Image.open(path) as image:
                canvas = image.copy()
            ImageDraw.Draw(canvas).text((15, 15), str(number), fill='black')
            canvas.save(path)
            item['title'] = '部件施工图 ' + str(number)
            drawings.append(item)
        unrelated = self.make_image(9, '另一部件工程图')
        manifest = {'projects': {'p': {'parts': {'part-key': drawings}, 'sources': drawings + [unrelated], 'renders': [self.render]}}}
        (self.root / 'drawing-previews' / 'manifest.json').write_text(json.dumps(manifest))
        self.bridge._state.update(image_slots=6, max_gallery_bytes=660000)
        self.launch(mode='task', automatic=True)
        result = self.result()
        self.assertEqual(result['status'], 'received', result)
        begins = [payload for action, payload, _ in self.peer.calls if action == 'image_begin']
        self.assertEqual([row['gallery_slot'] for row in begins], list(range(6)))
        self.assertEqual(len({row['sha256'] for row in begins}), 6)
        self.assertLessEqual(sum(row['bytes'] for row in begins), 660000)
        self.assertNotIn('另一部件工程图', [row['title'] for row in begins])
        self.assertEqual(result['completed_images'], 6)
        self.assertEqual(result['omitted_images'], 1)
        self.assertTrue(result['warnings'])

    def test_two_images_require_complete_bytes_and_sha_commits_before_received(self):
        before = copy.deepcopy(self.task)
        self.launch()
        result = self.result()
        self.assertEqual((result['status'], result['completed_images'], result['progress']), ('received', 2, 100))
        self.assertEqual([r['kind'] for r in result['receipts']], ['drawing', 'render'])
        self.assertGreater(sum(action == 'image_chunk' for action, _, _ in self.peer.calls), 2)
        self.assertTrue(all(image['committed'] for image in self.peer.images.values()))
        self.assertEqual([p['show'] for action, p, _ in self.peer.calls if action == 'image_commit'], [False, True])
        self.assertFalse(any('bytes' in image and isinstance(image['bytes'], (bytes, bytearray)) for image in result['images']))
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', 't')
            self.assertEqual(task['status'], before['status'])
            self.assertEqual(len(self.store.all(con, 'tasks')), 1)
            self.assertEqual(len([e for e in self.store.all(con, 'events') if e['action'] == 'device_images_received']), 1)

    def test_wrong_chunk_offset_cannot_complete(self):
        self.peer.mutate = lambda action, payload, reply: dict(reply, offset=0) if action == 'chunk' else reply
        self.launch(ids=self.ids[:1]); self.assert_error('位置不一致')
        self.assertFalse(any(action == 'image_commit' for action, _, _ in self.peer.calls))

    def test_commit_wrong_sha_rejected(self):
        self.peer.mutate = lambda action, payload, reply: dict(reply, sha256='f' * 64) if action == 'commit' else reply
        self.launch(ids=self.ids[:1]); self.assert_error('校验')

    def test_commit_wrong_size_rejected(self):
        self.peer.mutate = lambda action, payload, reply: dict(reply, bytes=1) if action == 'commit' else reply
        self.launch(ids=self.ids[:1]); self.assert_error('校验')

    def test_commit_wrong_context_rejected(self):
        self.peer.mutate = lambda action, payload, reply: dict(reply, context_id='another-project') if action == 'commit' else reply
        self.launch(ids=self.ids[:1]); self.assert_error('校验')

    def test_wrong_ack_image_id_rejected(self):
        self.peer.mutate = lambda action, payload, reply: dict(reply, image_id='stale-image')
        self.launch(ids=self.ids[:1]); self.assert_error('不匹配')

    def test_device_identity_switch_mid_stream_rejected(self):
        def switch(action, payload, image):
            if action == 'chunk':
                self.bridge._state['device_id'] = 'different-board'
        self.peer.after = switch
        self.launch(ids=self.ids[:1]); self.assert_error('USB 连接已变化')

    def test_same_device_reconnect_mid_stream_rejected(self):
        def reconnect(action, payload, image):
            if action == 'chunk':
                self.bridge._serial = object()
        self.peer.after = reconnect
        self.launch(ids=self.ids[:1]); self.assert_error('USB 连接已变化')

    def test_source_removed_before_commit_never_reports_received(self):
        def remove(action, payload, image):
            if action == 'chunk' and self.entry_paths[0].exists():
                self.entry_paths[0].unlink()
        self.peer.after = remove
        self.launch(ids=self.ids[:1]); self.assert_error('来源已更新')
        self.assertFalse(any(action == 'image_commit' for action, _, _ in self.peer.calls))

    def test_engineering_revision_changed_mid_stream_rejected(self):
        def update(action, payload, image):
            if action == 'chunk':
                with self.store.connect() as con:
                    project = self.store.get(con, 'projects', 'p'); project['revision'] = 2
                    self.store.put(con, 'projects', project)
        self.peer.after = update
        self.launch(ids=self.ids[:1]); self.assert_error('工程版本已变化')

    def test_timeout_after_storing_chunk_retries_identical_chunk_without_duplicates(self):
        self.peer.fail_once = 'chunk'
        self.launch(ids=self.ids[:1]); result = self.result()
        self.assertEqual(result['status'], 'received', result)
        chunks = [payload for action, payload, _ in self.peer.calls if action == 'image_chunk']
        self.assertEqual(chunks[0], chunks[1])
        image = next(iter(self.peer.images.values()))
        self.assertEqual(len(image['raw']), image['meta']['bytes'])

    def test_timeout_after_commit_retries_same_image_id(self):
        self.peer.fail_once = 'commit'
        self.launch(ids=self.ids[:1]); result = self.result()
        self.assertEqual(result['status'], 'received', result)
        commits = [payload for action, payload, _ in self.peer.calls if action == 'image_commit']
        self.assertEqual(len(commits), 2); self.assertEqual(commits[0], commits[1])

    def test_exhausted_timeout_does_not_report_completed(self):
        def unavailable(*args, **kwargs):
            raise DeviceError(504, '工牌断开')
        self.bridge._usb_rpc = unavailable
        self.launch(ids=self.ids[:1]); self.assert_error('工牌断开')

    def test_concurrent_start_and_task_send_are_rejected(self):
        entered, release = threading.Event(), threading.Event()
        actual = self.peer.rpc
        def blocked(*args, **kwargs):
            entered.set(); release.wait(3)
            return actual(*args, **kwargs)
        self.bridge._usb_rpc = blocked
        self.launch(ids=self.ids[:1]); self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(DeviceError) as raised:
                self.launch(ids=self.ids[:1])
            self.assertEqual(raised.exception.status, 409)
            with self.assertRaisesRegex(DeviceError, '接收图片'):
                self.bridge.send_task('t')
        finally:
            release.set()
        self.assertEqual(self.result()['status'], 'received')

    def test_task_mode_checks_device_current_task_before_any_image_bytes(self):
        self.peer.task = dict(self.task, id='other-task')
        self.launch(ids=self.ids[:1], mode='task'); self.assert_error('当前任务已变化')
        self.assertEqual([action for action, _, _ in self.peer.calls], ['get_task'])

    def test_task_mode_accepts_only_current_released_active_revision(self):
        for changes in ({'status': 'draft'}, {'released_revision': 0}, {'fulfillment_status': 'shipped'}):
            with self.store.connect() as con:
                self.store.put(con, 'projects', dict(self.project, **changes))
            with self.subTest(changes=changes), self.assertRaises(DeviceError):
                self.launch(mode='task')
        self.assertEqual(self.peer.calls, [])
        with self.store.connect() as con:
            self.store.put(con, 'projects', self.project)
            self.store.put(con, 'tasks', dict(self.task, status='done'))
        with self.assertRaises(DeviceError):
            self.launch(mode='task')

    def test_ready_running_and_paused_tasks_can_receive_images_without_changing_progress(self):
        for status in ('ready', 'in_progress', 'blocked'):
            current = dict(self.task, status=status, quantity=5, completed_quantity=2,
                           remaining_quantity=3, progress_recorded=True,
                           pause_reason='material' if status == 'blocked' else None)
            self.peer.task = current
            with self.store.connect() as con:
                self.store.put(con, 'tasks', current)
            with self.subTest(status=status):
                self.launch(ids=self.ids[:1], mode='task')
                self.assertEqual(self.result()['status'], 'received')
                with self.store.connect() as con:
                    saved = self.store.get(con, 'tasks', 't')
                self.assertEqual((saved['status'], saved['completed_quantity']), (status, 2))

    def test_second_image_bad_commit_leaves_partial_count_and_failure(self):
        def corrupt_second(action, payload, reply):
            return dict(reply, sha256='0' * 64) if action == 'commit' and payload['image_id'].endswith('-1') else reply
        self.peer.mutate = corrupt_second
        self.launch()
        result = self.assert_error('校验')
        self.assertEqual(result['completed_images'], 1)

    def test_unreleased_draft_rework_cannot_be_used_as_formal_image_task(self):
        with self.store.connect() as con:
            self.store.put(con, 'tasks', dict(self.task, status='draft', rework_of_task_id='original'))
        with self.assertRaises(DeviceError):
            self.launch(mode='task')
        self.assertFalse(self.peer.calls)

    def test_unreleased_draft_rework_cannot_be_sent_by_device_bridge(self):
        with self.store.connect() as con:
            self.store.put(con, 'tasks', dict(self.task, status='draft', rework_of_task_id='original'))
        with patch.object(self.bridge, '_write') as written:
            with self.assertRaises(DeviceError):
                self.bridge.send_task('t')
            written.assert_not_called()

    def test_automatic_images_include_only_task_matching_drawing_and_project_render(self):
        self.launch(mode='task', automatic=True)
        result = self.result()
        self.assertEqual(result['status'], 'received', result)
        self.assertEqual([item['kind'] for item in result['images']], ['drawing', 'render'])
        self.assertEqual(self.peer.calls[0][0], 'get_task')
        self.write_manifest(linked=False)
        self.peer.task = dict(self.task, part_id=None)
        with self.store.connect() as con:
            self.store.put(con, 'tasks', self.peer.task)
        self.launch(mode='task', automatic=True)
        result = self.result()
        self.assertEqual(result['status'], 'received', result)
        self.assertEqual([item['kind'] for item in result['images']], ['render'])

    def test_restart_marks_incomplete_job_error_and_never_replays_it(self):
        with self.store.connect() as con:
            self.store.put(con, KIND, {'id': 'interrupted', 'project_id': 'p', 'status': 'sending', 'progress': 70})
        transfers = BadgeImageTransfers(self.bridge)
        row = transfers.snapshot()['transfer']
        self.assertEqual(row['status'], 'error'); self.assertIn('重启', row['error'])
        self.assertFalse(self.peer.calls)
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, KIND, 'interrupted')['status'], 'error')

    def test_unsupported_firmware_or_wifi_mode_rejected_before_start(self):
        self.bridge._state['image_support'] = False
        with self.assertRaisesRegex(DeviceError, '固件不支持'):
            self.launch()
        self.bridge._state.update(image_support=True, transport='wifi')
        with self.assertRaisesRegex(DeviceError, 'USB'):
            self.launch()
        self.assertEqual(self.peer.calls, [])


@unittest.skipUnless(serial_fixture.POSIX_PTY_AVAILABLE, 'POSIX pseudo-terminal required')
class BadgeImagePTYTests(unittest.TestCase):
    setUp = serial_fixture.DeviceBridgeTests.setUp
    tearDown = serial_fixture.DeviceBridgeTests.tearDown
    wait_for = serial_fixture.DeviceBridgeTests.wait_for
    connect_badge = serial_fixture.DeviceBridgeTests.connect_badge
    last_delivery = serial_fixture.DeviceBridgeTests.last_delivery

    def test_real_pty_rpc_matches_request_type_and_device_and_autostarts_after_task_ack(self):
        self.connect_badge()
        self.bridge._state['image_support'] = True
        observed = []
        def extra(message):
            if message['type'] != 'image_status':
                return
            base = dict(type='image_ack', protocol=1, request_id=message['request_id'], action='status')
            self.badge.send(dict(base, device_id='foreign', context_id='wrong'))
            self.badge.send(dict(base, type='wifi_status', device_id=self.badge.hello_device_id, context_id='wrong'))
            self.badge.send(dict(base, device_id=self.badge.hello_device_id, context_id='correct'))
        self.badge.reply_extra = extra
        frame = self.bridge._usb_rpc('image_status', expected_device_id=self.badge.hello_device_id,
                                     reply_type='image_ack', timeout=1)
        self.assertEqual(frame['context_id'], 'correct')
        self.badge.reply_task = self.badge.ack
        with patch.object(self.bridge.images, 'start', side_effect=lambda *args, **kwargs: observed.append((args, kwargs))):
            self.bridge.send_task(self.task['id'], test_mode=True)
            self.wait_for(lambda: self.last_delivery()['status'] == 'received' and bool(observed))
        self.assertEqual(len(observed), 1)
        args, options = observed[0]
        self.assertEqual(args[0]['task_id'], self.task['id'])
        self.assertEqual(args[0]['mode'], 'task')
        self.assertTrue(options['automatic'])


if __name__ == '__main__':
    unittest.main()
