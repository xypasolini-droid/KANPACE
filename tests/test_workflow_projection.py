"""Actual Store and HTTP projections; no engine/model or customer data required."""
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
import app
import access_control
import workflow_projection
import scheduling


class WorkflowProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        access_control.clear_actor()
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '合成流程项目'})
            self.project['evidence_policy'] = 'legacy_fixture'
            self.store.put(con, 'projects', self.project)

    def tearDown(self):
        access_control.clear_actor()
        self.temp.cleanup()

    def put(self, kind, row):
        with self.store.connect() as con:
            self.store.put(con, kind, row)

    def document(self, **changes):
        row = {'id': 'doc_flow', 'project_id': self.project['id'], 'revision': 1,
               'filename': '明确BOM.csv', 'storage_name': 'fixture.csv', 'sha256': 'a' * 64,
               'purpose': 'drawing', 'status': 'parsed', 'part_count': 1, **changes}
        self.put('documents', row)
        return row

    def part(self, **changes):
        row = {'id': 'part_flow', 'project_id': self.project['id'], 'revision': 1,
               'document_id': 'doc_flow', 'name': '侧板', 'category': 'wood', 'material': '多层板',
               'quantity': 1, 'length': 600, 'width': 400, 'thickness': 18, 'unit': 'mm',
               'finish': '免漆', 'review_status': 'approved', 'source': {'sha256': 'a' * 64}, **changes}
        self.put('parts', row)
        return row

    def task(self, **changes):
        row = {'id': 'task_flow', 'project_id': self.project['id'], 'revision': 1,
               'title': '侧板开料', 'trade': '木工', 'process': 'cut', 'status': 'ready',
               'quantity': 1, 'completed_quantity': 0, 'hours': 1, 'dependencies': [],
               'assignee': None, 'execution_version': 0, **changes}
        self.put('tasks', row)
        return row

    def result(self):
        with self.store.read_transaction() as con:
            before = [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')]
            with patch('optimization_engines.status', side_effect=AssertionError('No probes during GET')):
                result = workflow_projection.get(self.store, con, self.project['id'])
            self.assertEqual(before, [tuple(row) for row in con.execute('SELECT * FROM entities ORDER BY id')])
        return result, {step['id']: step for step in result['steps']}

    def test_empty_project_has_ten_truthful_stages_and_no_files_created(self):
        result, steps = self.result()
        self.assertEqual(list(steps), [item[0] for item in workflow_projection.STEPS])
        self.assertEqual(steps['upload']['state'], 'available')
        self.assertEqual(steps['recognition']['state'], 'blocked')
        self.assertEqual(steps['geometry']['state'], 'optional')
        self.assertEqual(steps['material']['state'], 'needs_review')
        self.assertFalse(any(step['state'] == 'complete' for step in steps.values()))
        self.assertEqual(result['next_action']['project_id'], self.project['id'])
        self.assertFalse((self.store.data_dir / 'engineering-jobs').exists())
        self.assertFalse((self.store.data_dir / 'recognition-jobs').exists())
        self.assertNotIn('quote_settings', json.dumps(result))

    def test_pending_dimensions_and_unknown_hours_block_downstream(self):
        self.document()
        self.part(thickness=None, review_status='pending')
        self.task(hours=None)
        _, steps = self.result()
        self.assertEqual(steps['recognition']['state'], 'needs_review')
        for key in ('attribution', 'process', 'material', 'cycle', 'schedule', 'adopt'):
            self.assertEqual(steps[key]['state'], 'blocked', key)
        self.assertEqual(steps['process']['counts']['unknown_duration'], 1)
        self.assertEqual(steps['execution']['state'], 'blocked')

    def test_registered_sources_stale_parts_and_jobs_do_not_complete_review(self):
        self.document(sha256='b' * 64)
        self.part()
        root = self.store.data_dir / 'engineering-jobs' / ('eng_' + '1' * 32)
        root.mkdir(parents=True)
        (root / 'job.json').write_text(json.dumps({'id': root.name, 'kind': 'cad', 'status': 'completed',
            'metadata': {'project_id': self.project['id'], 'revision': '1', 'document_id': 'doc_flow'},
            'source': {'sha256': 'a' * 64}}))
        _, steps = self.result()
        self.assertEqual(steps['recognition']['counts']['stale_jobs'], 1)
        self.assertEqual(steps['attribution']['state'], 'blocked')
        self.assertTrue(any('校验值' in reason for reason in steps['attribution']['blockers']))
        self.project.update(revision=2, status='review')
        self.put('projects', self.project)
        _, newer = self.result()
        self.assertEqual(newer['attribution']['counts']['parts'], 0)
        self.assertEqual(newer['attribution']['counts']['stale_parts'], 1)

    def test_release_does_not_claim_start_with_no_assignee_and_shortage(self):
        self.document(); self.part(); self.task(status='blocked')
        self.project.update(status='released', released_revision=1)
        self.put('projects', self.project)
        self.put('materials', {'id': 'material_flow', 'project_id': self.project['id'], 'task_ids': ['task_flow'],
                              'name': '板材', 'required_quantity': 2, 'accepted_quantity': 0,
                              'unit': '张', 'expected_date': '2026-10-05'})
        _, steps = self.result()
        self.assertEqual(steps['adopt']['state'], 'complete')
        self.assertEqual(steps['material']['state'], 'blocked')
        self.assertEqual(steps['execution']['state'], 'blocked')
        self.assertEqual(steps['execution']['counts']['startable'], 0)
        self.assertEqual(steps['execution']['counts']['paused'], 1)

    def test_read_other_store_does_not_find_project(self):
        with tempfile.TemporaryDirectory() as other:
            store = app.Store(other, seed=False)
            with store.read_transaction() as con:
                with self.assertRaises(Exception) as caught:
                    workflow_projection.get(store, con, self.project['id'])
                self.assertEqual(caught.exception.status, 404)

    def test_fresh_preview_is_reviewable_but_resource_change_makes_it_stale(self):
        self.document(); self.part(); self.task()
        with self.store.connect() as con:
            fingerprint = scheduling.fingerprint(scheduling.context(self.store, con))
        self.put('scheduling_scenarios', {'id': 'scenario_flow', 'status': 'preview', 'fingerprint': fingerprint,
            'config': {'task_ids': ['task_flow']}, 'rows': [{'project_id': self.project['id'], 'task_id': 'task_flow'}]})
        _, fresh = self.result()
        self.assertEqual(fresh['schedule']['counts']['current_previews'], 1)
        self.assertEqual(fresh['schedule']['state'], 'needs_review')
        self.task(hours=2)
        _, stale = self.result()
        self.assertEqual(stale['schedule']['counts']['current_previews'], 0)
        self.assertEqual(stale['schedule']['counts']['stale_or_applied_previews'], 1)
        self.assertNotEqual(stale['schedule']['state'], 'complete')


class WorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': 'HTTP流程权限合成项目'})
            self.store.put(con, 'people', {'id': 'person_flow', 'name': '测试工人', 'skills': ['木工'], 'demo': False})
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None, cookie=None):
        headers = {'Content-Type': 'application/json'}
        if cookie: headers['Cookie'] = cookie.split(';', 1)[0]
        req = urllib.request.Request(self.url + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try: response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error: response = error
        with response:
            return response.status, json.loads(response.read()), response.headers.get('Set-Cookie')

    def test_route_authenticated_admin_worker_denied_unknown_project_404(self):
        path = '/api/projects/' + self.project['id'] + '/workflow'
        self.assertEqual(self.request(path)[0], 200)
        code, _, admin = self.request('/api/access/setup', {'username': 'flowadmin', 'name': '管理员', 'password': 'workflow-admin-secret'})
        self.assertEqual(code, 200)
        self.assertEqual(self.request(path)[0], 401)
        code, body, _ = self.request(path, cookie=admin)
        self.assertEqual(code, 200, body)
        self.assertEqual(len(body['steps']), 10)
        self.assertEqual(self.request('/api/projects/prj_missing/workflow', cookie=admin)[0], 404)
        code, body, _ = self.request('/api/access/users', {'username': 'flowworker', 'name': '工人', 'role': 'worker',
              'person_id': 'person_flow', 'password': 'workflow-worker-secret'}, admin)
        self.assertEqual(code, 200, body)
        code, _, worker = self.request('/api/access/login', {'username': 'flowworker', 'password': 'workflow-worker-secret'})
        self.assertEqual(code, 200)
        self.assertEqual(self.request(path, cookie=worker)[0], 403)


if __name__ == '__main__':
    unittest.main()
