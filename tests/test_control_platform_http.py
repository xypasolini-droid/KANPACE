"""Two-Web contract through temporary loopback HTTP servers; no launchd or hardware."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access_control as access
import app
import factory_config
import factory_instances as instances
import operations


class ControlPlatformHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-control-http-')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(access.clear_actor)
        self.logs = patch.object(app.Handler, 'log_message', lambda *_args: None)
        self.logs.start()
        self.addCleanup(self.logs.stop)
        self.stores = {'controller': app.Store(Path(self.temp.name) / 'controller', seed=False, empty=True)}
        self.records, self.servers, self.bases = {}, {}, {}
        self.cookie = {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for label in ('A', 'B'):
            self.stores[label], self.records[label] = instances.create_store(self.stores['controller'], {
                'name': label + '独立工厂', 'factory_type': 'cabinet',
                'admin': {'username': 'factory_admin', 'name': label + '管理员', 'password': 'child-test-password-123'}})
        instances._write_json(instances.root_path(self.stores['controller']) / 'registry.json', list(self.records.values()))
        for label, store in self.stores.items():
            server = app.Server(('127.0.0.1', 0), store)
            thread = threading.Thread(target=lambda s=server: s.serve_forever(poll_interval=0.01), daemon=True)
            thread.start()
            self.servers[label] = server
            self.bases[label] = 'http://127.0.0.1:' + str(server.server_port)
            self.addCleanup(self.stop, server, thread)

    @staticmethod
    def stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    def request(self, label, path, data=None, cookie=None, headers=None):
        request_headers = {'Origin': self.bases[label]}
        if cookie:
            request_headers['Cookie'] = cookie
        request_headers.update(headers or {})
        request_headers = {k: v for k, v in request_headers.items() if v is not None}
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.bases[label] + path, data=body, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            content_type = response.headers.get('Content-Type', '')
            return response.status, json.loads(raw) if content_type.startswith('application/json') else raw, dict(response.headers)

    def admin(self):
        code, data, headers = self.request('controller', '/api/access/setup', {
            'username': 'control_admin', 'name': '中台管理员', 'password': 'control-test-password-123'})
        self.assertEqual(code, 200, data)
        self.cookie['controller'] = headers['Set-Cookie'].split(';', 1)[0]
        return self.cookie['controller']

    def child_admin(self, label='A'):
        code, data, headers = self.request(label, '/api/access/login', {'username': 'factory_admin', 'password': 'child-test-password-123'})
        self.assertEqual(code, 200, data)
        self.cookie[label] = headers['Set-Cookie'].split(';', 1)[0]
        return self.cookie[label]

    def path(self, label, action=None, plan_id=None):
        path = '/api/control/factories/' + self.records[label]['id'] + '/config'
        return path + ('/' + action if action else '?factory_id=' + self.records[label]['factory_id']) + ('/' + plan_id if plan_id else '')

    def post(self, label, action, data, plan_id=None):
        return self.request('controller', self.path(label, action, plan_id), data, cookie=self.cookie['controller'])

    def create_plan(self, label='A'):
        code, data, _ = self.post(label, 'plans', {'factory_id': self.records[label]['factory_id'], 'name': label + '企业流程'})
        self.assertEqual(code, 200, data)
        return data['plan']

    def counts(self, label):
        with self.stores[label].connect() as con:
            return {kind: len(self.stores[label].all(con, kind)) for kind in ('projects', 'tasks', 'workflow_templates', factory_config.PLAN_KIND, factory_config.PROFILE_KIND, factory_config.RECEIPT_KIND)}

    def test_control_api_denies_local_disabled_then_unauthenticated_access(self):
        for path, data in [('/api/control', None), (self.path('A'), None), (self.path('A', 'plans'), {})]:
            code, result, _ = self.request('controller', path, data)
            self.assertEqual(code, 409, result)
            self.assertNotIn(self.records['A']['id'], json.dumps(result))
        self.admin()
        for path, data in [('/api/control', None), (self.path('A'), None), (self.path('A', 'plans'), {})]:
            self.assertEqual(self.request('controller', path, data)[0], 401)
        self.assertEqual(self.counts('A')[factory_config.PLAN_KIND], 0)

    def test_only_real_controller_admin_can_manage_factories(self):
        self.admin()
        with self.stores['controller'].connect() as con:
            access._new_user(self.stores['controller'], con, {'username': 'owner_view', 'name': '只读老板', 'role': 'owner', 'password': 'owner-test-password-123'})
        code, data, headers = self.request('controller', '/api/access/login', {'username': 'owner_view', 'password': 'owner-test-password-123'})
        self.assertEqual(code, 200, data)
        owner_cookie = headers['Set-Cookie'].split(';', 1)[0]
        for path, data in [('/api/control', None), (self.path('A'), None), (self.path('A', 'plans'), {'factory_id': self.records['A']['factory_id']})]:
            self.assertEqual(self.request('controller', path, data, owner_cookie)[0], 403)
        self.assertEqual(self.request('controller', '/api/control', cookie=self.cookie['controller'])[0], 200)
        self.assertEqual(self.request('A', '/api/state', cookie=self.cookie['controller'])[0], 401)

    def test_child_admin_cannot_get_control_api_or_control_static(self):
        cookie = self.child_admin()
        for path, data in [('/api/control', None), (self.path('B'), None), (self.path('B', 'plans'), {'factory_id': self.records['B']['factory_id']})]:
            code, result, _ = self.request('A', path, data, cookie)
            self.assertEqual(code, 403, (path, result))
            self.assertNotIn(self.records['B']['id'], json.dumps(result))
        for path in ('/control', '/control/', '/control/index.html', '/control/style.css', '/%63ontrol/index.html', '/factory/../control/index.html'):
            self.assertEqual(self.request('A', path, cookie=cookie)[0], 404, path)
        self.assertEqual(self.request('controller', '/control/index.html')[0], 200)

    def test_factory_alias_loads_on_parent_child_and_cross_port_navigation(self):
        for label in ('controller', 'A'):
            for path in ('/factory', '/factory/', '/factory/index.html'):
                code, html, _ = self.request(label, path)
                self.assertEqual(code, 200, (label, path, html))
                self.assertIn(b'/app.js', html)
        # A real click from control port to child port has this browser metadata.
        headers = {'Origin': None, 'Sec-Fetch-Site': 'same-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
        self.assertEqual(self.request('A', '/factory/index.html', headers=headers)[0], 200)
        # The exception is only navigation to the public shell, not cross-port API use.
        self.assertEqual(self.request('A', '/api/workspace', headers=headers)[0], 403)

    def test_configuration_installs_only_after_review_and_child_exposes_profile(self):
        self.admin()
        plan = self.create_plan()
        code, updated, _ = self.post('A', 'plans', {'expected_version': plan['version'], 'object_label': '本厂柜号'}, plan['id'])
        self.assertEqual(code, 200, updated)
        plan = updated['plan']
        before = self.counts('A')
        body = {'plan_id': plan['id'], 'expected_version': plan['version']}
        code, preview, _ = self.post('A', 'preview', body)
        self.assertEqual(code, 200, preview)
        self.assertEqual(before, self.counts('A'))
        self.assertEqual(preview['summary']['task_count'], 9)
        payload = {**body, 'preview_token': preview['preview_token'], 'objects': preview['objects'], 'reviewed': True,
                   'reviewer': '真实复核人', 'review_note': '已核对工序前后关系和验收要求', 'request_id': 'http-config-install-001'}
        for mutation in ({'reviewed': False}, {'reviewer': ''}, {'review_note': ''}):
            self.assertEqual(self.post('A', 'install', {**payload, **mutation})[0], 400)
        self.assertEqual(before, self.counts('A'))
        with self.stores['A'].connect() as con:
            operations.save_person(self.stores['A'], con, {'factory_id': self.records['A']['factory_id'], 'name': '新增测试技师', 'skills': ['木工']})
        code, stale, _ = self.post('A', 'install', payload)
        self.assertEqual(code, 409, stale)
        self.assertEqual(stale['details']['code'], 'stale_preview')
        code, fresh, _ = self.post('A', 'preview', body)
        self.assertEqual(code, 200, fresh)
        payload['preview_token'] = fresh['preview_token']
        code, installed, _ = self.post('A', 'install', payload)
        self.assertEqual(code, 200, installed)
        self.assertEqual(self.post('A', 'install', payload)[1]['replayed'], True)
        self.assertEqual(self.counts('A')['workflow_templates'], 1)
        self.assertEqual(self.counts('A')[factory_config.RECEIPT_KIND], 1)
        self.assertEqual(self.counts('A')['projects'], 0)
        self.assertEqual(self.counts('A')['tasks'], 0)
        self.assertEqual(self.counts('controller')[factory_config.PLAN_KIND], 0)
        self.assertEqual(self.counts('B')[factory_config.PLAN_KIND], 0)
        child_cookie = self.child_admin()
        code, workspace, _ = self.request('A', '/api/workspace?factory_id=' + self.records['B']['factory_id'], cookie=child_cookie)
        self.assertEqual(code, 200, workspace)
        self.assertTrue(workspace['isolated'])
        self.assertEqual(workspace['profile']['id'], installed['profile']['id'])
        self.assertEqual(workspace['profile']['factory_id'], self.records['A']['factory_id'])
        self.assertEqual(workspace['profile']['object_label'], '本厂柜号')
        self.assertNotIn(self.records['B']['id'], json.dumps(workspace))

    def test_controller_config_cannot_mix_registered_customers_or_invent_target(self):
        self.admin()
        a, b = self.create_plan('A'), self.create_plan('B')
        self.assertEqual(self.post('A', 'preview', {'plan_id': b['id'], 'expected_version': b['version']})[0], 404)
        self.assertEqual(self.post('A', 'plans', {'expected_version': b['version'], 'name': 'wrong'}, b['id'])[0], 404)
        self.assertEqual(self.post('A', 'plans', {'factory_id': self.records['B']['factory_id']})[0], 403)
        wrong_catalog = self.path('A').split('?')[0] + '?factory_id=' + self.records['B']['factory_id']
        self.assertEqual(self.request('controller', wrong_catalog, cookie=self.cookie['controller'])[0], 403)
        unknown = '/api/control/factories/inst_' + '0' * 32 + '/config?factory_id=' + self.records['A']['factory_id']
        self.assertEqual(self.request('controller', unknown, cookie=self.cookie['controller'])[0], 404)
        code, catalog, _ = self.request('controller', self.path('A'), cookie=self.cookie['controller'])
        self.assertEqual(code, 200, catalog)
        self.assertEqual([p['id'] for p in catalog['plans']], [a['id']])
        self.assertNotIn(b['id'], json.dumps(catalog))


if __name__ == '__main__':
    unittest.main()
