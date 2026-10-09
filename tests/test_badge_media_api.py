"""Actual local HTTP routing/permissions for badge media; no physical serial port."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
import app
import test_access_http


class BadgeMediaAPITests(unittest.TestCase):
    setUp = test_access_http.AccessHTTPTests.setUp
    tearDown = test_access_http.AccessHTTPTests.tearDown
    request = test_access_http.AccessHTTPTests.request
    setup_admin = test_access_http.AccessHTTPTests.setup_admin
    account = test_access_http.AccessHTTPTests.account

    def image_bytes(self, format='PNG', color='teal'):
        out = io.BytesIO(); Image.new('RGB', (80, 60), color).save(out, format=format)
        return out.getvalue()

    def upload(self, purpose='drawing', filename='施工图.png', *, project_id=None, color='teal'):
        content = self.image_bytes('JPEG' if filename.lower().endswith(('.jpg', '.jpeg')) else 'PNG', color)
        status, result, _ = self.request('/api/import', {'project_id': project_id or self.project['id'],
            'filename': filename, 'purpose': purpose, 'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(status, 200, result)
        return result['document'], content

    def catalog(self, project_id=None, *, task_id=None, cookie=None):
        path = '/api/projects/' + (project_id or self.project['id']) + '/badge-media'
        if task_id is not None:
            path += '?task_id=' + urllib.parse.quote(task_id, safe='')
        return self.request(path, cookie=cookie)

    def raw(self, path, cookie=None):
        headers = {'Origin': self.base}
        if cookie:
            headers['Cookie'] = cookie.split(';', 1)[0]
        req = urllib.request.Request(self.base + path, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), dict(response.headers)

    def business_state(self):
        with self.store.connect() as con:
            return {kind: self.store.all(con, kind) for kind in ('projects', 'tasks', 'parts')}

    def ready_bridge(self, *, supported=True):
        bridge = self.server.device_bridge
        bridge._serial = SimpleNamespace(close=lambda: None)
        bridge._state.update(state='ready', connected=True, transport='usb', device_id='http-isolated-badge',
                             image_support=supported)
        return bridge

    def test_catalog_returns_actual_uploaded_drawing_and_render_without_business_mutation(self):
        drawing, _ = self.upload()
        render, _ = self.upload('render', '项目效果图.jpg', color='red')
        before = self.business_state()
        status, result, _ = self.catalog()
        self.assertEqual(status, 200, result)
        self.assertEqual(result['project_id'], self.project['id'])
        self.assertEqual({item['kind'] for item in result['items']}, {'drawing', 'render'})
        self.assertEqual({item['document_id'] for item in result['items']}, {drawing['id'], render['id']})
        self.assertEqual(result['warnings'], [])
        self.assertEqual(self.business_state(), before)
        self.assertNotIn(str(Path(self.temp.name)), json.dumps(result))
        self.assertFalse(any(key.startswith('_') for item in result['items'] for key in item))

    def test_inline_images_use_actual_mime_and_original_bytes(self):
        for purpose, filename in [('drawing', '扫描图.png'), ('render', '整体效果图.jpg')]:
            doc, content = self.upload(purpose, filename)
            status, result, _ = self.catalog()
            self.assertEqual(status, 200)
            item = next(item for item in result['items'] if item['document_id'] == doc['id'])
            code, served, headers = self.raw(item['url'])
            self.assertEqual(code, 200)
            self.assertEqual(served, content)
            self.assertEqual(headers['Content-Type'], 'image/png' if filename.endswith('.png') else 'image/jpeg')
            self.assertNotIn('attachment', headers.get('Content-Disposition', ''))
            self.assertEqual(headers.get('X-Content-Type-Options'), 'nosniff')

    def test_badge_image_rejects_unknown_document_traversal_external_symlink_and_invalid_content(self):
        doc, _ = self.upload()
        self.assertEqual(self.raw('/api/documents/not-registered/badge-image')[0], 404)
        with self.store.connect() as con:
            changed = self.store.get(con, 'documents', doc['id'])
            changed['storage_name'] = '../outside.png'
            self.store.put(con, 'documents', changed)
        self.assertEqual(self.raw('/api/documents/' + doc['id'] + '/badge-image')[0], 404)
        external = Path(self.temp.name) / 'outside.png'; external.write_bytes(self.image_bytes())
        link = self.store.uploads / 'outside-link.source'; link.symlink_to(external)
        with self.store.connect() as con:
            changed['storage_name'] = link.name; self.store.put(con, 'documents', changed)
        self.assertEqual(self.raw('/api/documents/' + doc['id'] + '/badge-image')[0], 404)
        link.unlink(); link.write_bytes(b'not an image')
        self.assertEqual(self.raw('/api/documents/' + doc['id'] + '/badge-image')[0], 422)

    def test_cross_project_task_catalog_is_rejected_and_unknown_ids_are_not_resolved(self):
        with self.store.connect() as con:
            other = self.store.new_project(con, {'name': '另一订单'})
        before = self.business_state()
        status, result, _ = self.catalog(other['id'], task_id='qa_task_own')
        self.assertEqual(status, 409, result)
        self.assertIn('不属于', result['error'])
        self.assertEqual(self.catalog('unknown-project')[0], 404)
        self.assertEqual(self.catalog(task_id='unknown-task')[0], 404)
        self.assertEqual(self.business_state(), before)

    def test_image_transfer_status_is_available_without_connection_and_does_not_change_business(self):
        before = self.business_state()
        status, result, _ = self.request('/api/device/images')
        self.assertEqual(status, 200)
        self.assertEqual(result, {'transfer': None})
        status, result, _ = self.request('/api/device/image-status')
        self.assertEqual(status, 409, result)
        self.assertEqual(self.business_state(), before)

    def test_disconnected_and_old_firmware_image_submission_fail_without_serial_or_business_changes(self):
        doc, _ = self.upload()
        selected = self.catalog()[1]['items'][0]['id']
        data = {'project_id': self.project['id'], 'asset_ids': [selected], 'mode': 'preview'}
        before = self.business_state()
        with patch.object(self.server.device_bridge, '_write') as write:
            status, result, _ = self.request('/api/device/images', data)
            self.assertEqual(status, 409, result)
            self.assertIn('USB', result['error'])
            self.ready_bridge(supported=False)
            status, result, _ = self.request('/api/device/images', data)
            self.assertEqual(status, 409, result)
            self.assertIn('固件不支持', result['error'])
            write.assert_not_called()
        self.assertEqual(self.request('/api/device/images')[1]['transfer'], None)
        self.assertEqual(self.business_state(), before)

    def test_malformed_submission_gets_400_and_cross_project_task_409(self):
        with self.store.connect() as con:
            other = self.store.new_project(con, {'name': '另一订单'})
        self.ready_bridge()
        for payload in ({}, {'project_id': self.project['id'], 'asset_ids': []},
                        {'project_id': self.project['id'], 'mode': 'task', 'asset_ids': ['a']},
                        {'project_id': self.project['id'], 'asset_ids': ['a'], 'task_id': 5}):
            self.assertEqual(self.request('/api/device/images', payload)[0], 400, payload)
        status, result, _ = self.request('/api/device/images',
            {'project_id': other['id'], 'task_id': 'qa_task_own', 'asset_ids': ['a'], 'mode': 'preview'})
        self.assertEqual(status, 409, result)
        self.assertIn('不一致', result['error'])

    def test_image_status_returns_live_protocol_observation_not_transfer_job(self):
        bridge = self.ready_bridge()
        observation = {'type': 'image_ack', 'protocol': 1, 'device_id': 'http-isolated-badge', 'action': 'status',
                       'context_id': 'preview:' + self.project['id'] + ':r1', 'available': True, 'displaying': True,
                       'visible_kind': 'drawing', 'scale': 8, 'pan_x': 0, 'pan_y': 0,
                       'images': [{'kind': 'drawing', 'sha256': 'a'*64, 'bytes': 8000}], 'free_bytes': 200000}
        with patch.object(bridge, '_usb_rpc', return_value=copy.deepcopy(observation)) as rpc:
            status, result, _ = self.request('/api/device/image-status')
        self.assertEqual(status, 200, result)
        self.assertEqual(result, observation)
        rpc.assert_called_once_with('image_status', reply_type='image_ack')
        self.assertEqual(self.request('/api/device/images')[1], {'transfer': None})

    def test_anonymous_blocked_after_accounts_enabled_but_worker_can_read_shared_images(self):
        doc, content = self.upload()
        path = '/api/documents/' + doc['id'] + '/badge-image'
        _, worker = self.account('worker', 'media_worker', 'qa_worker_a')
        self.assertEqual(self.catalog()[0], 401)
        self.assertEqual(self.raw(path)[0], 401)
        self.assertEqual(self.request('/api/device/images')[0], 401)
        self.assertEqual(self.catalog(cookie=worker)[0], 200)
        self.assertEqual(self.raw(path, worker)[:2], (200, content))
        self.assertEqual(self.request('/api/device/images', cookie=worker)[0], 200)
        status, result, _ = self.request('/api/device/images',
            {'project_id': self.project['id'], 'asset_ids': ['not-a-real-asset'], 'mode': 'preview'}, worker)
        self.assertEqual(status, 403, result)

    def test_only_device_authorized_roles_can_submit_images(self):
        before = self.business_state()
        self.setup_admin()
        for role in ('technical', 'warehouse', 'owner'):
            _, cookie = self.account(role, 'media_' + role)
            status, result, _ = self.request('/api/device/images',
                {'project_id': self.project['id'], 'asset_ids': ['test-only'], 'mode': 'preview'}, cookie)
            self.assertEqual(status, 403, result)
        _, supervisor = self.account('supervisor', 'media_supervisor')
        for cookie in (supervisor, self.admin_cookie):
            status, result, _ = self.request('/api/device/images',
                {'project_id': self.project['id'], 'asset_ids': ['test-only'], 'mode': 'preview'}, cookie)
            self.assertEqual(status, 409, result)
            self.assertIn('USB', result['error'])
        self.assertEqual(self.business_state(), before)


if __name__ == '__main__':
    unittest.main()
