"""Representative account enforcement tests through the real local HTTP server.

Separate test class; synthetic accounts/resources only, no shared API test
inheritance and no calls to access_control functions to bypass routing.
"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class AccessHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            for identifier, name in [('qa_worker_a', '甲工人'), ('qa_worker_b', '乙工人')]:
                self.store.put(con, 'people', {'id': identifier, 'name': name, 'skills': ['木工'],
                    'role': '木工', 'capacity_minutes': 480, 'demo': False})
            self.project = self.store.new_project(con, {'name': '权限隔离测试项目', 'factory_type': 'cabinet'})
            self.project.update(status='released', released_revision=1)
            self.store.put(con, 'projects', self.project)
            for identifier, assignee in [('qa_task_own', 'qa_worker_a'), ('qa_task_other', 'qa_worker_b')]:
                self.store.put(con, 'tasks', {'id': identifier, 'project_id': self.project['id'], 'revision': 1,
                    'title': identifier, 'trade': '木工', 'process': 'cut', 'status': 'ready', 'assignee': assignee,
                    'quantity': 3, 'completed_quantity': 0, 'hours': 1, 'dependencies': [], 'execution_version': 0,
                    'demo': False, 'archived': False})
            self.part = {'id': 'qa_priced_part', 'project_id': self.project['id'], 'revision': 1, 'name': '实木面板',
                         'category': 'wood', 'material': '橡木', 'length': 600, 'width': 400, 'thickness': 18,
                         'quantity': 3, 'unit': 'mm', 'finish': '免漆', 'unit_price': 987.65, 'pricing_unit': 'piece',
                         'review_status': 'pending', 'source': {'file': '隔离测试.csv'}, 'issues': [], 'notes': ''}
            self.store.put(con, 'parts', self.part)
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.admin_cookie = None
        self.admin_user = None

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None, cookie=None):
        headers = {'Accept': 'application/json', 'Origin': self.base}
        if cookie: headers['Cookie'] = cookie.split(';', 1)[0]
        content = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        if content is not None: headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=content, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            body = json.loads(raw) if raw else None
            return response.status, body, dict(response.headers)

    def setup_admin(self):
        if self.admin_cookie: return
        status, result, headers = self.request('/api/access/setup',
            {'username': 'qa_admin', 'name': '权限测试管理员', 'password': 'isolated-admin-password'})
        self.assertEqual(status, 200, result)
        self.admin_cookie = headers.get('Set-Cookie')
        self.assertTrue(self.admin_cookie)
        self.admin_user = result['user']

    def account(self, role, username, person_id=None):
        self.setup_admin()
        payload = {'username': username, 'name': '测试' + role, 'role': role, 'password': 'isolated-user-password'}
        if person_id: payload['person_id'] = person_id
        status, created, _ = self.request('/api/access/users', payload, self.admin_cookie)
        self.assertEqual(status, 200, created)
        status, signed, headers = self.request('/api/access/login', {'username': username, 'password': 'isolated-user-password'})
        self.assertEqual(status, 200, signed)
        self.assertNotIn('password_hash', signed['user'])
        return created['user'], headers['Set-Cookie']

    def test_setup_login_logout_and_revoked_cookie_cannot_read_state(self):
        status, first, _ = self.request('/api/access')
        self.assertEqual(status, 200, first)
        self.assertFalse(first['enabled'])
        self.setup_admin()
        self.assertIn('HttpOnly', self.admin_cookie)
        self.assertIn('SameSite=Strict', self.admin_cookie)
        self.assertEqual(self.request('/api/state')[0], 401)
        status, own, _ = self.request('/api/access', cookie=self.admin_cookie)
        self.assertEqual(own['user']['id'], self.admin_user['id'])
        self.assertEqual(self.request('/api/state', cookie=self.admin_cookie)[0], 200)
        status, logged_out, headers = self.request('/api/access/logout', {}, self.admin_cookie)
        self.assertEqual(status, 200, logged_out)
        self.assertTrue(logged_out['logged_out'])
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/state', cookie=self.admin_cookie)[0], 401)
        self.assertEqual(self.request('/api/access/login', {'username': 'qa_admin', 'password': 'invalid-password'})[0], 401)
        status, login, headers = self.request('/api/access/login', {'username': 'qa_admin', 'password': 'isolated-admin-password'})
        self.assertEqual(status, 200, login)
        self.assertEqual(self.request('/api/state', cookie=headers['Set-Cookie'])[0], 200)

    def test_worker_can_start_and_report_own_task_but_not_others(self):
        _, cookie = self.account('worker', 'qa_worker', 'qa_worker_a')
        status, started, _ = self.request('/api/tasks/qa_task_own/status', {'status': 'in_progress', 'expected_execution_version': 0}, cookie)
        self.assertEqual(status, 200, started)
        task = started.get('task', started)
        status, progress, _ = self.request('/api/tasks/qa_task_own/progress',
            {'completed_quantity': 1, 'note': '本人完成一件', 'expected_execution_version': task['execution_version']}, cookie)
        self.assertEqual(status, 200, progress)
        for action, data in [('status', {'status': 'in_progress'}), ('progress', {'completed_quantity': 1, 'note': '越权报工'})]:
            status, denied, _ = self.request('/api/tasks/qa_task_other/' + action, data, cookie)
            self.assertEqual(status, 403, denied)
        self.assertEqual(self.request('/api/tasks/qa_task_own/assign', {'person_id': 'qa_worker_b'}, cookie)[0], 403)
        with self.store.connect() as con:
            other = self.store.get(con, 'tasks', 'qa_task_other')
            self.assertEqual((other['status'], other['completed_quantity']), ('ready', 0))

    def test_technical_state_hides_prices_nonprice_edit_keeps_price_explicit_price_denied(self):
        _, cookie = self.account('technical', 'qa_technical')
        status, state, _ = self.request('/api/state', cookie=cookie)
        self.assertEqual(status, 200, state)
        public_part = next(p for p in state['parts'] if p['id'] == self.part['id'])
        self.assertNotIn('unit_price', public_part)
        self.assertEqual(state['settings'], {})
        self.assertFalse(state['financial_access'])
        self.assertNotIn('987.65', json.dumps(state))
        status, updated, _ = self.request('/api/parts/' + self.part['id'] + '/review',
            {'approved': True, 'edits': {'name': '核对后的实木面板'}, 'review_note': '技术核验尺寸材质'}, cookie)
        self.assertEqual(status, 200, updated)
        with self.store.connect() as con:
            saved = self.store.get(con, 'parts', self.part['id'])
            self.assertEqual(saved['unit_price'], 987.65)
            self.assertEqual(saved['name'], '核对后的实木面板')
        status, denied, _ = self.request('/api/parts/' + self.part['id'] + '/review',
            {'approved': True, 'edits': {'unit_price': 1}, 'review_note': '试图修改价格'}, cookie)
        self.assertEqual(status, 403, denied)
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'parts', self.part['id'])['unit_price'], 987.65)
        status, admin_state, _ = self.request('/api/state', cookie=self.admin_cookie)
        self.assertEqual(next(p for p in admin_state['parts'] if p['id'] == self.part['id'])['unit_price'], 987.65)

    def test_technical_financial_routes_denied_and_aggregate_filtered(self):
        _, cookie = self.account('technical', 'qa_financial_restricted')
        pid = self.project['id']
        for path in ('/api/projects/' + pid + '/quote', '/api/projects/' + pid + '/export?format=json'):
            status, result, _ = self.request(path, cookie=cookie)
            self.assertEqual(status, 403, result)
        for path, payload in [('/api/production/costs', {'project_id': pid, 'category': 'labor', 'amount': 2, 'note': '费用'}),
                              ('/api/production/financials', {'project_id': pid, 'expected_version': 0, 'contract_amount': 1, 'note': '合同'}),
                              ('/api/settings', {'markup': 1.2})]:
            status, result, _ = self.request(path, payload, cookie)
            self.assertEqual(status, 403, result)
        status, production, _ = self.request('/api/production?project_id=' + pid, cookie=cookie)
        self.assertEqual(status, 200, production)
        self.assertEqual(production['costs'], [])
        self.assertEqual(production['financials'], [])
        self.assertEqual(production['economics'], [])
        self.assertFalse(production['financial_access'])

    def test_audit_records_actual_authenticated_actor_not_previous_request(self):
        user, worker_cookie = self.account('worker', 'qa_audited_worker', 'qa_worker_a')
        status, started, _ = self.request('/api/tasks/qa_task_own/status', {'status': 'in_progress', 'expected_execution_version': 0}, worker_cookie)
        self.assertEqual(status, 200, started)
        # A subsequent request from a different role must not inherit thread-local identity.
        status, created, _ = self.request('/api/projects', {'name': '管理员创建的隔离项目'}, self.admin_cookie)
        self.assertEqual(status, 200, created)
        status, state, _ = self.request('/api/state', cookie=self.admin_cookie)
        self.assertEqual(status, 200, state)
        task_event = next(e for e in reversed(state['events']) if e.get('details', {}).get('task_id') == 'qa_task_own' and e['action'] == 'task_status')
        project_event = next(e for e in reversed(state['events']) if e['action'] == 'project_created' and e['project_id'] == created['project']['id'])
        self.assertEqual(task_event['actor'], user['name'])
        self.assertEqual(project_event['actor'], self.admin_user['name'])
        self.assertEqual(task_event['actor_id'], user['id'])
        self.assertEqual(task_event['actor_role'], 'worker')
        self.assertEqual(task_event['actor_person_id'], 'qa_worker_a')
        self.assertNotIn('isolated-user-password', json.dumps(state))
        self.assertNotIn('password_hash', json.dumps(state))


if __name__ == '__main__':
    unittest.main()
