"""Integration tests exercise real HTTP requests against an isolated SQLite DB."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        # The shared business fixture supplies real staff. Production no longer
        # auto-assigns a real order to the application's demonstration workers.
        with self.store.connect() as con:
            for person in self.store.all(con, 'people'):
                person['demo'] = False
                self.store.put(con, 'people', person)
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None, headers=None, raw=False):
        body = None if data is None else json.dumps(data).encode()
        request_headers = {'Content-Type': 'application/json'}
        request_headers.update(headers or {})
        req = urllib.request.Request(self.url + path, data=body, headers=request_headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            result = content if raw else json.loads(content)
            return response.status, result

    def project(self, name='测试展示柜'):
        status, result = self.request('/api/projects', {'name': name, 'client': '测试', 'quantity': 1})
        self.assertEqual(status, 200, result)
        # Execution-focused legacy fixture: staged customer-drawing approval is
        # covered separately and must not obscure task execution assertions.
        project = result['project']
        project['evidence_policy'] = 'legacy_fixture'
        with self.store.connect() as con:
            self.store.put(con, 'projects', project)
        return project

    def imported(self, project=None, filename='parts.csv', content=None):
        project = project or self.project()
        content = content or b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\n'
        status, result = self.request('/api/import', {'project_id': project['id'], 'filename': filename,
                                                    'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(status, 200, result)
        return project, result

    def prepared(self):
        project, imported = self.imported()
        part = imported['parts'][0]
        status, result = self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        self.assertEqual(status, 200, result)
        status, result = self.request('/api/projects/' + project['id'] + '/generate', {})
        self.assertEqual(status, 200, result)
        tasks = result['tasks']
        return project, part, tasks

    def state(self):
        status, state = self.request('/api/state')
        self.assertEqual(status, 200)
        return state

    def execution_prepared(self):
        project, part, tasks = self.prepared()
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/auto-assign', {})[0], 200)
        return project, part, [t for t in self.state()['tasks'] if t['project_id'] == project['id']]

    def task_action(self, task, action, data):
        return self.request('/api/tasks/' + task['id'] + '/' + action, data)

    def test_partial_progress_pause_persists_and_resume_preserves_quantity(self):
        _, _, tasks = self.execution_prepared()
        first = next(t for t in tasks if not t['dependencies'])
        first = self.task_action(first, 'status', {'status': 'in_progress'})[1]['task']
        code, result = self.task_action(first, 'progress', {'completed_quantity': 1, 'note': '第二件开料一半', 'expected_execution_version': first['execution_version']})
        self.assertEqual(code, 200, result)
        first = result['task']
        self.assertEqual((first['quantity'], first['completed_quantity'], first['remaining_quantity'], first['status']), (2, 1, 1, 'in_progress'))
        code, result = self.task_action(first, 'pause', {'reason': 'material', 'note': '缺封边条', 'handover_note': '已完成件放A架，半成品保留夹具', 'expected_execution_version': first['execution_version']})
        self.assertEqual(code, 200, result)
        paused = result['task']
        with app.Store(self.temp.name, seed=False).connect() as con:
            saved = self.store.get(con, 'tasks', first['id'])
        self.assertEqual((saved['completed_quantity'], saved['pause_reason']), (1, 'material'))
        self.assertEqual(self.task_action(paused, 'resume', {'note': ''})[0], 400)
        self.assertEqual(self.task_action(paused, 'progress', {'completed_quantity': 2, 'note': '暂停中'})[0], 409)
        code, result = self.task_action(paused, 'resume', {'note': '封边条到货检验合格', 'expected_execution_version': paused['execution_version']})
        self.assertEqual(code, 200, result)
        resumed = result['task']
        self.assertEqual((resumed['completed_quantity'], resumed['remaining_quantity'], resumed['pause_reason']), (1, 1, None))
        self.assertEqual(resumed['handover_note'], saved['handover_note'])
        self.assertEqual(self.task_action(resumed, 'status', {'status': 'done', 'completed_quantity': 1})[0], 409)
        done = self.task_action(resumed, 'status', {'status': 'done'})[1]['task']
        self.assertEqual((done['status'], done['completed_quantity']), ('done', 2))
        events = [e for e in self.state()['events'] if e['details'].get('task_id') == first['id']]
        self.assertTrue(any(e['action'] == 'task_paused' and e['details']['reason'] == 'material' for e in events))
        self.assertTrue(any(e['action'] == 'task_resumed' and e['details']['previous_pause']['pause_reason'] == 'material' for e in events))

    def test_progress_full_quantity_does_not_release_dependencies(self):
        _, _, tasks = self.execution_prepared()
        first = next(t for t in tasks if not t['dependencies'])
        later = next(t for t in tasks if first['id'] in t['dependencies'])
        self.task_action(first, 'status', {'status': 'in_progress'})
        code, result = self.task_action(first, 'progress', {'completed_quantity': 2, 'note': '两件做好，整项待确认'})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['task']['status'], 'in_progress')
        self.assertEqual(self.task_action(later, 'status', {'status': 'in_progress'})[0], 409)
        self.task_action(first, 'status', {'status': 'done', 'completed_quantity': 2})
        self.assertEqual(self.task_action(later, 'status', {'status': 'in_progress'})[0], 200)

    def test_strict_progress_priority_and_execution_version_validation(self):
        _, _, tasks = self.execution_prepared()
        first = next(t for t in tasks if not t['dependencies'])
        first = self.task_action(first, 'status', {'status': 'in_progress'})[1]['task']
        for value in (-1, .5, 3, True, '1', None, float('nan'), float('inf'), 10 ** 500):
            self.assertEqual(self.task_action(first, 'progress', {'completed_quantity': value, 'note': '核验'})[0], 400, value)
        for value in (-1, 4, .5, True, '1', None):
            self.assertEqual(self.task_action(first, 'priority', {'priority': value, 'reason': '急单'})[0], 400, value)
        changed = self.task_action(first, 'priority', {'priority': 3, 'reason': '客户提前交货', 'expected_execution_version': first['execution_version']})[1]['task']
        self.assertEqual(changed['status'], 'in_progress')
        self.assertEqual(self.task_action(first, 'progress', {'completed_quantity': 1, 'note': '旧页提交', 'expected_execution_version': first['execution_version']})[0], 409)
        self.task_action(changed, 'progress', {'completed_quantity': 1, 'note': '完成一件'})
        self.assertEqual(self.task_action(changed, 'progress', {'completed_quantity': 0, 'note': '清零'})[0], 409)
        self.assertEqual(self.task_action(changed, 'pause', {'reason': 'invalid', 'note': '说明', 'handover_note': '现场'})[0], 400)
        self.assertEqual(self.task_action(changed, 'pause', {'reason': 'equipment', 'note': '故障'})[0], 400)

    def test_atomic_urgent_switch_invalid_target_rolls_back_then_resume(self):
        _, _, tasks_a = self.execution_prepared()
        _, _, tasks_b = self.execution_prepared()
        a, b = [next(t for t in tasks if not t['dependencies']) for tasks in (tasks_a, tasks_b)]
        later = next(t for t in tasks_b if b['id'] in t['dependencies'])
        a = self.task_action(a, 'status', {'status': 'in_progress'})[1]['task']
        data = {'reason': 'urgent', 'note': '客户急单', 'handover_note': '第二件保留夹具', 'completed_quantity': 1, 'expected_execution_version': a['execution_version']}
        before = self.state()
        code, result = self.task_action(a, 'switch', dict(data, target_task_id=later['id']))
        self.assertEqual(code, 409, result)
        after = self.state()
        self.assertEqual(before['tasks'], after['tasks'])
        self.assertEqual(before['events'], after['events'])
        self.assertEqual(self.task_action(b, 'status', {'status': 'in_progress'})[0], 409)
        b = self.task_action(b, 'priority', {'priority': 3, 'reason': '客户急单'})[1]['task']
        self.assertEqual(b['status'], 'ready')
        queue = self.request('/api/tasks/queue?person_id=' + a['assignee'] + '&from_task_id=' + a['id'])[1]['tasks']
        preview = next(t for t in queue if t['id'] == b['id'])
        self.assertFalse(preview['can_start'])
        self.assertTrue(preview['can_switch'], preview['switch_blockers'])
        self.assertEqual(queue[0]['id'], b['id'])
        self.assertEqual(self.task_action(a, 'switch', dict(data, target_task_id=b['id'], target_expected_execution_version=b['execution_version'] - 1))[0], 409)
        code, switched = self.task_action(a, 'switch', dict(data, target_task_id=b['id'], target_expected_execution_version=b['execution_version']))
        self.assertEqual(code, 200, switched)
        self.assertEqual(switched['task']['completed_quantity'], 1)
        self.assertEqual(switched['task']['interrupted_by_task_id'], b['id'])
        self.assertEqual(switched['target_task']['status'], 'in_progress')
        self.assertEqual(self.task_action(a, 'resume', {'note': '急单未结束'})[0], 409)
        self.task_action(b, 'status', {'status': 'done'})
        resumed = self.task_action(a, 'resume', {'note': '急单完成，核对夹具'})[1]['task']
        self.assertEqual((resumed['quantity'], resumed['completed_quantity'], resumed['remaining_quantity']), (2, 1, 1))

    def test_switch_paused_target_requires_resolution_and_valid_skill(self):
        _, _, tasks_a = self.execution_prepared()
        _, _, tasks_b = self.execution_prepared()
        a, b = [next(t for t in tasks if not t['dependencies']) for tasks in (tasks_a, tasks_b)]
        self.task_action(b, 'pause', {'reason': 'equipment', 'note': '设备停机', 'handover_note': '尚未加工'})
        self.task_action(a, 'status', {'status': 'in_progress'})
        data = {'target_task_id': b['id'], 'reason': 'other', 'note': '调整安排', 'handover_note': 'A件加工一半', 'completed_quantity': 0}
        self.assertEqual(self.task_action(a, 'switch', data)[0], 400)
        with self.store.connect() as con:
            person = self.store.get(con, 'people', a['assignee'])
            person['skills'] = ['玻璃']
            self.store.put(con, 'people', person)
        self.assertEqual(self.task_action(a, 'switch', dict(data, target_note='设备已修复'))[0], 409)
        with self.store.connect() as con:
            person['skills'] = ['木工']
            self.store.put(con, 'people', person)
        code, switched = self.task_action(a, 'switch', dict(data, target_note='设备已修复并试切合格'))
        self.assertEqual(code, 200, switched)
        self.assertEqual(switched['task']['completed_quantity'], 0)
        self.assertEqual(switched['task']['handover_note'], 'A件加工一半')
        self.assertIsNone(switched['target_task']['pause_reason'])

    def test_recompile_carries_unaffected_partial_pause_but_resets_changed_work(self):
        project = self.project()
        content = b'id,name,material,category,length,width,thickness,quantity,unit,finish\nA,Left,Plywood,wood,1000,500,18,2,mm,clear\nB,Right,Plywood,wood,1000,500,18,2,mm,clear\n'
        _, imported = self.imported(project, content=content)
        for part in imported['parts']:
            self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        tasks = self.request('/api/projects/' + project['id'] + '/generate', {})[1]['tasks']
        self.request('/api/projects/' + project['id'] + '/release', {})
        self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        roots = [t for t in tasks if not t['dependencies']]
        for task in roots:
            self.task_action(task, 'status', {'status': 'in_progress'})
            self.task_action(task, 'priority', {'priority': 2, 'reason': '已承诺交期'})
            self.task_action(task, 'pause', {'reason': 'material', 'note': '缺料', 'handover_note': '一件完成一件待补料', 'completed_quantity': 1})
        self.request('/api/parts/' + imported['parts'][0]['id'] + '/review', {'approved': True, 'edits': {'length': 1100}})
        self.assertEqual(self.task_action(roots[1], 'resume', {'note': '料到'})[0], 409)
        new_tasks = self.request('/api/projects/' + project['id'] + '/generate', {})[1]['tasks']
        carried = next(t for t in new_tasks if t.get('carried_from_task_id') == roots[1]['id'])
        changed = next(t for t in new_tasks if t.get('part_id') == roots[0]['part_id'] and not t['dependencies'])
        self.assertEqual((carried['status'], carried['completed_quantity'], carried['priority'], carried['pause_reason']), ('blocked', 1, 2, 'material'))
        self.assertEqual((changed['status'], changed['completed_quantity'], changed['priority']), ('draft', 0, 0))
        archived = next(t for t in self.state()['tasks'] if t['id'] == roots[0]['id'])
        self.assertTrue(archived['archived'])
        self.assertEqual(archived['completed_quantity'], 1)
        self.assertEqual(archived['previous_status'], 'blocked')
        self.request('/api/projects/' + project['id'] + '/release', {})
        resumed = self.task_action(carried, 'resume', {'note': '新版本未改此部件，来料复核通过'})[1]['task']
        self.assertEqual(resumed['remaining_quantity'], 1)

    def test_legacy_progress_defaults_and_integral_float_quantity(self):
        _, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        with self.store.connect() as con:
            raw = dict(task, quantity=2.0)
            for key in ('completed_quantity', 'remaining_quantity', 'progress_recorded', 'execution_version', 'priority'):
                raw.pop(key, None)
            con.execute('UPDATE entities SET data=? WHERE id=?', (json.dumps(raw), task['id']))
        before = self.state()
        old = next(t for t in before['tasks'] if t['id'] == task['id'])
        self.assertFalse(old['progress_recorded'])
        self.assertEqual(old['completed_quantity'], 0)
        self.assertEqual(before['events'], self.state()['events'])
        started = self.task_action(old, 'status', {'status': 'in_progress'})[1]['task']
        self.assertFalse(started['progress_recorded'])
        reported = self.task_action(started, 'progress', {'completed_quantity': 0, 'note': '第一件尚未整件完成'})[1]['task']
        self.assertTrue(reported['progress_recorded'])
        self.assertEqual(self.task_action(reported, 'status', {'status': 'done'})[0], 200)

    def test_invalid_fractional_stored_quantity_has_explicit_repair_path(self):
        _, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        self.task_action(task, 'status', {'status': 'in_progress'})
        with self.store.connect() as con:
            saved = self.store.get(con, 'tasks', task['id'])
            saved['quantity'] = 2.5
            self.store.put(con, 'tasks', saved)
        code, result = self.task_action(task, 'status', {'status': 'done'})
        self.assertEqual(code, 409)
        self.assertIn('核对部件数量后重新生成并发布', result['error'])

    def test_health_and_empty_real_project(self):
        self.assertEqual(self.request('/api/health')[1]['ok'], True)
        project = self.project()
        self.assertFalse(project['demo'])
        self.assertEqual(self.state()['parts'], [])
        self.assertEqual(len(self.state()['people']), 8)

    def test_recompile_preserves_unaffected_completed_work(self):
        project = self.project()
        content = b'id,name,material,category,length,width,thickness,quantity,unit,finish\nA,Left,Plywood,wood,1000,500,18,1,mm,clear\nB,Right,Plywood,wood,1000,500,18,1,mm,clear\n'
        project, imported = self.imported(project, content=content)
        for part in imported['parts']:
            self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        tasks = self.request('/api/projects/' + project['id'] + '/generate', {})[1]['tasks']
        self.request('/api/projects/' + project['id'] + '/release', {})
        self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        first_part, unchanged_part = imported['parts']
        unchanged_tasks = [t for t in tasks if t.get('part_id') == unchanged_part['id']]
        first = next(t for t in unchanged_tasks if not t['dependencies'])
        self.request('/api/tasks/' + first['id'] + '/status', {'status': 'in_progress'})
        self.request('/api/tasks/' + first['id'] + '/status', {'status': 'done'})
        next_task = next(t for t in unchanged_tasks if t['dependencies'])
        self.request('/api/tasks/' + next_task['id'] + '/status', {'status': 'in_progress'})
        self.request('/api/parts/' + first_part['id'] + '/review', {'approved': True, 'edits': {'length': 1100}})
        code, generated = self.request('/api/projects/' + project['id'] + '/generate', {})
        self.assertEqual(code, 200, generated)
        carried = {t.get('carried_from_task_id'): t for t in generated['tasks'] if t.get('carried_from_task_id')}
        self.assertEqual(carried[first['id']]['status'], 'done')
        self.assertEqual(carried[next_task['id']]['status'], 'in_progress')
        self.assertTrue(carried[first['id']]['assignee_id'])
        self.assertEqual(self.request('/api/tasks/' + carried[next_task['id']]['id'] + '/status', {'status': 'done'})[0], 409)
        self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(self.request('/api/tasks/' + carried[next_task['id']]['id'] + '/status', {'status': 'done'})[0], 200)

    def test_blocked_resume_requires_resolution_reason(self):
        project, part, tasks = self.prepared()
        self.request('/api/projects/' + project['id'] + '/release', {})
        self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        task = next(t for t in tasks if not t['dependencies'])
        self.request('/api/tasks/' + task['id'] + '/status', {'status': 'blocked', 'note': '设备故障'})
        self.assertEqual(self.request('/api/tasks/' + task['id'] + '/status', {'status': 'in_progress'})[0], 400)
        self.assertEqual(self.request('/api/tasks/' + task['id'] + '/status', {'status': 'in_progress', 'note': '设备已修复并试运行合格'})[0], 200)

    def test_source_id_survives_and_task_csv_contains_work_order(self):
        project, imported = self.imported(content=b'id,name,material,category,length,width,thickness,quantity,unit,finish\nSW-123,Panel,Plywood,wood,1200,600,18,2,mm,clear\n')
        self.assertEqual(imported['parts'][0]['source']['external_id'], 'SW-123')
        self.request('/api/projects/' + project['id'] + '/generate', {})
        self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        code, body = self.request('/api/projects/' + project['id'] + '/export?format=csv', raw=True)
        text = body.decode('utf-8-sig')
        self.assertEqual(code, 200)
        for value in ['任务ID', '负责人', '前置工序', '验收要求', 'SW-123', '木工', '张师傅']:
            self.assertIn(value, text)
        code, body = self.request('/api/projects/' + project['id'] + '/export?format=bom_csv', raw=True)
        self.assertEqual(code, 200)
        self.assertIn('长mm', body.decode('utf-8-sig'))

    def test_unconfirmed_demo_rates_are_disclosed_for_real_projects(self):
        project, part, tasks = self.prepared()
        quote = self.request('/api/projects/' + project['id'] + '/quote')[1]
        self.assertFalse(quote['demo'])
        self.assertFalse(quote['rates_confirmed'])
        self.assertIn('演示参考', quote['rate_provenance'])
        self.assertIn('不能据此对外报价', str(quote['notes']))
        self.request('/api/settings', {'rates_confirmed': True})
        self.assertTrue(self.request('/api/projects/' + project['id'] + '/quote')[1]['rates_confirmed'])

    def test_duplicate_source_conflict_requires_review_basis(self):
        project, imported = self.imported(content=b'id,name,material,category,length,width,thickness,quantity,unit,finish\nSW-1,Panel,Plywood,wood,1200,600,18,2,mm,clear\nSW-1,Panel,Plywood,wood,1300,600,18,2,mm,clear\n')
        part = imported['parts'][0]
        self.assertEqual(self.request('/api/parts/' + part['id'] + '/review', {'approved': True})[0], 409)
        self.assertEqual(self.request('/api/parts/' + part['id'] + '/review', {'approved': True, 'review_note': '已对照图纸，此行为左侧板；另一行为右侧板，确认分别生产'})[0], 200)

    def test_sample_download_and_path_isolation(self):
        code, sample = self.request('/samples/showcase-bom.csv', raw=True)
        self.assertEqual(code, 200)
        self.assertIn(b'material', sample)
        self.assertEqual(self.request('/samples/%2e%2e/app.py')[0], 404)

    def test_import_hash_idempotent_and_source_download(self):
        project, imported = self.imported()
        again = self.imported(project)[1]
        self.assertTrue(again['duplicate'])
        self.assertEqual(imported['document']['id'], again['document']['id'])
        self.assertEqual(len(self.state()['parts']), 1)
        status, data = self.request('/api/documents/' + imported['document']['id'] + '/download', raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b'Panel,Plywood', data)
        self.assertFalse(imported['parts'][0]['approved'])

    def test_native_source_has_no_fabricated_parts_and_blocks_release(self):
        project, result = self.imported(filename='assembly.SLDASM', content=b'native-solidworks-content')
        self.assertEqual(result['document']['status'], 'needs_conversion')
        self.assertEqual(result['parts'], [])
        code, blocked = self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(code, 409)
        self.assertTrue(any('转换' in item for item in blocked['details']))

    def test_review_and_release_gate(self):
        project, imported = self.imported()
        code, generated = self.request('/api/projects/' + project['id'] + '/generate', {})
        self.assertEqual(code, 200, generated)
        self.assertTrue(generated['blockers'])
        code, result = self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(code, 409)
        self.assertIn('尚未审核', str(result))
        part = imported['parts'][0]
        self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        code, result = self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['project']['status'], 'released')

    def test_missing_dimensions_cannot_be_approved(self):
        project, imported = self.imported(content=b'name,material,category,quantity,unit\nPanel,Plywood,wood,2,mm\n')
        part = imported['parts'][0]
        code, error = self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        self.assertEqual(code, 409)
        self.assertIn('长度', str(error))
        code, result = self.request('/api/parts/' + part['id'] + '/review', {'approved': True,
            'edits': {'length_mm': 1200, 'width_mm': 600, 'thickness_mm': 18, 'finish': 'clear'}})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['part']['length'], 1200)
        self.assertTrue(result['part']['approved'])

    def test_skills_dependencies_and_status_transition(self):
        project, part, tasks = self.prepared()
        self.request('/api/projects/' + project['id'] + '/release', {})
        first = next(t for t in tasks if not t['dependencies'])
        later = next(t for t in tasks if t['dependencies'])
        mismatch = next(p for p in self.state()['people'] if first['trade'] not in p['skills'])
        code, _ = self.request('/api/tasks/' + first['id'] + '/assign', {'person_id': mismatch['id']})
        self.assertEqual(code, 409)
        code, result = self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        self.assertEqual(code, 200, result)
        self.assertEqual(len(result['assignments']), len(tasks))
        code, _ = self.request('/api/tasks/' + later['id'] + '/status', {'status': 'in_progress'})
        self.assertEqual(code, 409)
        code, _ = self.request('/api/tasks/' + first['id'] + '/status', {'status': 'done'})
        self.assertEqual(code, 409)
        self.assertEqual(self.request('/api/tasks/' + first['id'] + '/status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.request('/api/tasks/' + first['id'] + '/status', {'status': 'done'})[0], 200)
        self.assertEqual(self.request('/api/tasks/' + first['id'] + '/status', {'status': 'ready', 'note': 'wrong'})[0], 409)

    def test_dimension_change_invalidates_downstream_and_freezes_snapshot(self):
        project, part, tasks = self.prepared()
        self.request('/api/projects/' + project['id'] + '/release', {})
        code, result = self.request('/api/parts/' + part['id'] + '/review', {'approved': False, 'edits': {'length_mm': 1300}})
        self.assertEqual(code, 200, result)
        self.assertEqual(set(result['invalidated_tasks']), {t['id'] for t in tasks})
        current = next(p for p in self.state()['projects'] if p['id'] == project['id'])
        self.assertEqual(current['status'], 'review')
        self.assertGreater(current['revision'], current['released_revision'])
        self.assertEqual(self.request('/api/tasks/' + tasks[0]['id'] + '/status', {'status': 'in_progress'})[0], 409)
        code, snapshots = self.request('/api/projects/' + project['id'] + '/releases')
        self.assertEqual(code, 200)
        self.assertEqual(snapshots['releases'][0]['parts'][0]['length'], 1200)
        self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 200)
        state = self.state()
        self.assertTrue(any(t.get('archived') for t in state['tasks']))
        self.assertTrue(any(e['action'] == 'revision_changed' for e in state['events']))

    def test_same_name_reimport_archives_old_bom(self):
        project, old = self.imported()
        _, new = self.imported(project, content=b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1300,600,18,2,mm,clear\n')
        self.assertFalse(new['duplicate'])
        state = self.state()
        old_doc = next(d for d in state['documents'] if d['id'] == old['document']['id'])
        self.assertTrue(old_doc['superseded'])
        self.assertEqual(len([p for p in state['parts'] if not p.get('archived')]), 1)
        self.assertEqual(len(state['parts']), 2)

    def test_mutation_csrf_and_traversal(self):
        code, _ = self.request('/api/projects', {'name': 'malicious'}, {'Origin': 'https://attacker.example'})
        self.assertEqual(code, 403)
        code, _ = self.request('/api/projects', {'name': 'malicious'}, {'Content-Type': 'text/plain'})
        self.assertEqual(code, 415)
        project = self.project()
        code, _ = self.request('/api/import', {'project_id': project['id'], 'filename': '../../evil.csv', 'content_base64': 'YQ=='})
        self.assertEqual(code, 400)
        code, _ = self.request('/%2e%2e/app.py')
        self.assertEqual(code, 404)
        code, _ = self.request('/api/state', headers={'Host': 'evil.example'})
        self.assertEqual(code, 403)

    def test_csv_formula_injection_is_escaped(self):
        project = self.project('=HYPERLINK("bad")')
        self.imported(project)
        self.request('/api/projects/' + project['id'] + '/generate', {})
        code, body = self.request('/api/projects/' + project['id'] + '/export?format=csv', raw=True)
        self.assertEqual(code, 200)
        self.assertIn("'=HYPERLINK", body.decode('utf-8-sig'))

    def test_settings_and_database_persist(self):
        project, part, tasks = self.prepared()
        code, quote1 = self.request('/api/projects/' + project['id'] + '/quote')
        self.assertEqual(code, 200, quote1)
        self.assertTrue(quote1['complete'], quote1)
        code, result = self.request('/api/settings', {'margin_rate': .4})
        self.assertEqual(code, 200, result)
        quote2 = self.request('/api/projects/' + project['id'] + '/quote')[1]
        self.assertGreater(quote2['total'], quote1['total'])
        self.assertEqual(self.request('/api/settings', {'margin_rate': 1})[0], 400)
        reopened = app.Store(self.temp.name, seed=False)
        with reopened.connect() as con:
            self.assertEqual(reopened.settings(con)['margin_rate'], .4)
            self.assertEqual(reopened.get(con, 'projects', project['id'])['name'], project['name'])

    def test_resolution_requires_verified_replacement(self):
        project, imported = self.imported(filename='native.dwg', content=b'dwgbytes')
        path = '/api/documents/' + imported['document']['id'] + '/resolve'
        self.assertEqual(self.request(path, {'note': 'checked'})[0], 409)
        code, result = self.request('/api/parts', {'project_id': project['id'], 'name': 'manual-panel', 'material': 'Plywood',
            'category': 'wood', 'length': 1000, 'width': 500, 'thickness': 18, 'quantity': 1, 'finish': 'clear',
            'source_document_id': imported['document']['id']})
        self.assertEqual(code, 200, result)
        self.assertEqual(self.request('/api/parts/' + result['part']['id'] + '/review', {'approved': True})[0], 409)
        self.request('/api/parts/' + result['part']['id'] + '/review',
                     {'approved': True, 'review_note': '逐项对照原 DWG 核对尺寸、材质和数量'})
        self.assertEqual(self.request(path, {'note': '逐项对照原DWG，人工部件覆盖本柜结构'})[0], 200)

    def test_people_create_and_preserve_assigned_skills(self):
        project, part, tasks = self.prepared()
        code, result = self.request('/api/people', {'name': '王工', 'skills': ['木工', '装配'], 'capacity_minutes': 420})
        self.assertEqual(code, 200, result)
        person = result['person']
        self.assertFalse(person['demo'])
        task = next(t for t in tasks if t['trade'] == '木工')
        self.assertEqual(self.request('/api/tasks/' + task['id'] + '/assign', {'person_id': person['id']})[0], 200)
        code, updated = self.request('/api/people/' + person['id'], {'skills': ['装配']})
        self.assertEqual(code, 200, updated)
        with self.store.connect() as con:
            changed = self.store.get(con, 'tasks', task['id'])
        self.assertIsNone(changed['assignee'])
        self.assertIn('重新分派', changed['reassignment_reason'])
        self.assertEqual(self.request('/api/people/' + person['id'], {'name': '王木工'})[0], 200)

    def test_finish_and_integer_quantity_are_required(self):
        project, imported = self.imported(content=b'name,material,category,length,width,thickness,quantity,unit\nPanel,Plywood,wood,1200,600,18,1.5,mm\n')
        part = imported['parts'][0]
        code, error = self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        self.assertEqual(code, 409)
        self.assertIn('表面处理', str(error))
        self.assertIn('整件数', str(error))
        code, result = self.request('/api/parts/' + part['id'] + '/review', {'approved': True, 'edits': {'quantity': 2, 'finish': 'clear'}})
        self.assertEqual(code, 200, result)
        self.assertTrue(result['part']['source_issues'])

    def test_inspection_completion_requires_fresh_result_record(self):
        project, imported = self.imported(content=b'id,name,material,category,length,width,thickness,quantity,unit,finish\nLED,Light,LED,electrical,1000,10,5,1,mm,none\nG1,Glass,Glass,glass,1200,600,8,1,mm,polished\n')
        for part in imported['parts']:
            self.request('/api/parts/' + part['id'] + '/review', {'approved': True})
        tasks = self.request('/api/projects/' + project['id'] + '/generate', {})[1]['tasks']
        self.request('/api/projects/' + project['id'] + '/release', {})
        self.request('/api/projects/' + project['id'] + '/auto-assign', {})
        inspection_count = 0
        for task in tasks:
            route = '/api/tasks/' + task['id'] + '/status'
            self.assertEqual(self.request(route, {'status': 'in_progress'})[0], 200)
            needs_record = task['trade'] == '质检' or (task.get('part_id') is None and task['process'] == 'electrical')
            if needs_record:
                inspection_count += 1
                for note in ('', '   '):
                    code, error = self.request(route, {'status': 'done', 'note': note})
                    self.assertEqual(code, 400, error)
                    self.assertIn('检验结果', str(error))
                current = next(t for t in self.state()['tasks'] if t['id'] == task['id'])
                self.assertEqual(current['status'], 'in_progress')
                result_note = '依照验收要求逐项核验：尺寸及外观符合已确认图纸；适用回路功能正常，判定合格。'
                code, result = self.request(route, {'status': 'done', 'note': result_note})
                self.assertEqual(code, 200, result)
                self.assertEqual(result['task']['inspection_result'], result_note)
                self.assertTrue(result['task']['inspection_recorded_at'])
            else:
                self.assertEqual(self.request(route, {'status': 'done'})[0], 200)
        self.assertEqual(inspection_count, 3)

    def test_outsourcing_cost_is_scoped_to_project(self):
        first, _, _ = self.prepared()
        second, _, _ = self.prepared()
        self.request('/api/settings', {'outsourcing_cost': 9999})
        path_a = '/api/projects/' + first['id']
        path_b = '/api/projects/' + second['id']
        quote_b_before = self.request(path_b + '/quote')[1]
        self.assertEqual(quote_b_before['outsourcing_cost'], 0)
        code, result = self.request(path_a + '/costs', {'outsourcing_cost': 1000})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['project']['quote_settings']['outsourcing_cost'], 1000)
        quote_a = self.request(path_a + '/quote')[1]
        quote_b_after = self.request(path_b + '/quote')[1]
        self.assertEqual(quote_a['outsourcing_cost'], 1000)
        self.assertEqual(quote_a['outsourcing_scope'], 'project')
        self.assertEqual(quote_b_after['outsourcing_cost'], 0)
        self.assertEqual(quote_b_after['total'], quote_b_before['total'])
        self.assertEqual(self.request(path_a + '/costs', {'outsourcing_cost': -1})[0], 400)
        self.assertEqual(self.request(path_a + '/quote')[1]['outsourcing_cost'], 1000)
        self.assertTrue(any(e['action'] == 'project_costs_changed' and e['project_id'] == first['id'] for e in self.state()['events']))

    def test_identical_part_numbers_keep_rows_and_need_review_basis(self):
        project, imported = self.imported(content=b'id,name,material,category,length,width,thickness,quantity,unit,finish\nSW-1,Panel,Plywood,wood,1200,600,18,2,mm,clear\nSW-1,Panel,Plywood,wood,1200,600,18,2,mm,clear\n')
        self.assertEqual(len(imported['parts']), 2)
        self.assertEqual(sum(p['quantity'] for p in imported['parts']), 4)
        for part in imported['parts']:
            route = '/api/parts/' + part['id'] + '/review'
            self.assertEqual(self.request(route, {'approved': True})[0], 409)
            self.assertEqual(self.request(route, {'approved': True, 'review_note': '两行来自不同子装配，各需两件；确认总用量四件并保留来源'})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)

    def test_incomplete_quote_has_no_false_total(self):
        project, result = self.imported(content=b'name,material,category,quantity,unit\nPanel,Plywood,wood,1,mm\n')
        code, quote = self.request('/api/projects/' + project['id'] + '/quote')
        self.assertEqual(code, 200, quote)
        self.assertFalse(quote['complete'])
        self.assertIsNone(quote['total'])
        self.assertTrue(quote['missing'])


if __name__ == '__main__':
    unittest.main()
