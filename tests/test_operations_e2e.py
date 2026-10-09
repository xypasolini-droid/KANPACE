"""Independent HTTP and USB-PTY acceptance of real (synthetic) production work.

Uses a temporary SQLite database, loopback port 0 and a pseudo-terminal only.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import unittest
from unittest.mock import patch
import production
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app
import operations
import test_device_bridge as device_fixture
from device_bridge import DeviceBridge
from types import SimpleNamespace


class OperationsEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.badge = None

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        if self.badge:
            self.badge.close()
        self.temp.cleanup()

    def request(self, path, data=None, status=200):
        req = urllib.request.Request(self.url + path, None if data is None else json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=10) as response:
                code, payload = response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            code, payload = exc.code, json.load(exc)
        self.assertEqual(code, status, (path, payload))
        return payload

    def row(self, kind, identifier):
        with self.store.connect() as con:
            return self.store.get(con, kind, identifier)

    def rows(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def fixture(self, typ='cabinet', nodes=None, capacity=480):
        factory = self.request('/api/operations/factories', {'name': '隔离验收工厂 ' + typ, 'factory_type': typ})['factory']
        template_data = {'source_template_id': 'builtin_' + typ + '_v1', 'factory_id': factory['id']}
        if nodes is not None:
            template_data['nodes'] = nodes
        draft = self.request('/api/operations/templates', template_data)['template']
        template = self.request('/api/operations/templates/' + draft['id'] + '/publish', {'expected_version': draft['version']})['template']
        project = self.request('/api/projects', {'name': '隔离合成订单 ' + typ, 'factory_type': typ,
                                                'factory_id': factory['id'], 'due_date': '2026-12-31'})['project']
        workflow = self.request('/api/projects/' + project['id'] + '/workflow', {
            'factory_id': factory['id'], 'template_id': template['id'], 'expected_revision': project['revision'],
            'expected_version': 0, 'scope_note': '按人工核对的测试工程要求执行，无真实客户数据',
            'objects': [{'code': 'T01', 'name': '合成对象', 'quantity': 2, 'unit': '台' if typ == 'machinery' else '件',
                         'instructions': '按测试R1图纸施工，尺寸及验收以已核对技术要求为准', 'location': '隔离测试区域'}]})
        self.request('/api/projects/' + project['id'] + '/release', {}, status=409)
        self.request('/api/projects/' + project['id'] + '/workflow/review', {
            'expected_version': workflow['workflow']['version'], 'reviewer': '隔离测试负责人',
            'review_note': '已核对对象范围、工艺和验收要求', 'acknowledge_manual_scope': True})
        released = self.request('/api/projects/' + project['id'] + '/release', {})
        person = self.request('/api/operations/people', {
            'name': '隔离测试工人', 'factory_id': factory['id'], 'skills': list(dict.fromkeys(t['trade'] for t in released['tasks'])),
            'capacity_minutes': capacity})['person']
        tasks = []
        for t in released['tasks']:
            tasks.append(self.request('/api/tasks/' + t['id'] + '/assign', {'person_id': person['id'], 'expected_execution_version': t['execution_version']})['task'])
        return dict(factory=factory, template=template, project=project, person=person, tasks=tasks)

    @staticmethod
    def simple_nodes(quality=False):
        return [operations.node('work', '合成工序', '装配', checks=('图纸和作业条件已确认',), acceptance=('尺寸和外观符合要求',), quality=quality)]

    def confirm_checks(self, task):
        page = self.request('/api/production?project_id=' + task['project_id'])
        sheet = next((c for c in page['checks'] if c['task_id'] == task['id']), None)
        if sheet:
            self.request('/api/production/checks', {'task_id': task['id'], 'expected_task_version': task['execution_version'],
                'expected_version': sheet['version'], 'items': [dict(i, status='ready', note='隔离测试已现场核对') for i in sheet['items']]})

    def status(self, task, value, expected=200):
        return self.request('/api/tasks/' + task['id'] + '/status', {'status': value,
            'expected_execution_version': task['execution_version'], 'note': '隔离验收已核对'}, status=expected)

    def test_all_three_scene_workflows_finish_with_real_gates_and_costs(self):
        for typ in ('cabinet', 'machinery', 'site'):
            with self.subTest(scene=typ):
                f = self.fixture(typ)
                order = operations.dag_order(f['template']['nodes'])
                by_node = {t['template_node_id']: t for t in f['tasks']}
                for node_id in order:
                    t = by_node[node_id]
                    if t['start_checks']:
                        self.status(t, 'in_progress', expected=409)
                    self.confirm_checks(t)
                    t = self.status(t, 'in_progress')['task']
                    if t.get('inspection_required'):
                        self.status(t, 'done', expected=409)
                        self.request('/api/production/inspections', {'task_id': t['id'], 'expected_task_version': t['execution_version'],
                                     'result': 'passed', 'note': '人工测量及功能检查合格', 'measurements': [{'name': '尺寸', 'value': '100', 'unit': 'mm', 'criterion': '100±1'}]})
                    t = self.status(t, 'done')['task']
                    self.assertEqual(t['completed_quantity'], 2)
                self.request('/api/production/costs', {'project_id': f['project']['id'], 'category': 'material', 'amount': 120,
                             'occurred_on': '2026-09-06', 'note': '测试领料凭证'})
                self.request('/api/production/financials', {'project_id': f['project']['id'], 'expected_version': 0,
                             'contract_amount': 300, 'budget_cost': 200, 'remaining_cost': 30, 'received_amount': 100,
                             'approved_change_amount': 20, 'note': '测试合同及费用基准'})
                self.request('/api/production/deliveries', {'project_id': f['project']['id'], 'scope': 'T01 首批', 'quantity': 1,
                             'unit': '件', 'delivered_on': '2026-09-06', 'reference': 'TEST-SHIP-' + typ})
                page = self.request('/api/production?project_id=' + f['project']['id'])
                self.assertEqual(page['economics'][0]['forecast_profit'], 170)
                self.assertEqual(page['economics'][0]['unreceived_amount'], 220)
                self.assertEqual(len(page['deliveries']), 1)
                self.assertTrue(all(s['ended_at'] and s['minutes'] >= 0 for s in page['work_sessions']))
                self.assertEqual(len(page['work_sessions']), len(f['tasks']))
                self.assertEqual(self.row('projects', f['project']['id'])['fulfillment_status'], 'active')

    def test_material_pause_requires_new_check_and_ready_material_before_resume(self):
        f = self.fixture(nodes=self.simple_nodes())
        t = f['tasks'][0]
        material = self.request('/api/production/materials', {'project_id': t['project_id'], 'task_ids': [t['id']],
            'name': '合成专用零件', 'required_quantity': 2, 'accepted_quantity': 1, 'unit': '件'})['material']
        self.confirm_checks(t)
        self.status(t, 'in_progress', expected=409)
        self.request('/api/production/materials', dict(material, expected_version=material['version'], accepted_quantity=2))
        t = self.status(t, 'in_progress')['task']
        t = self.request('/api/tasks/' + t['id'] + '/pause', {'expected_execution_version': t['execution_version'],
            'reason': 'material', 'note': '测试发现追加物料缺少', 'handover_note': '已做1件放在标记处', 'completed_quantity': 1})['task']
        self.assertEqual(t['completed_quantity'], 1)
        self.request('/api/tasks/' + t['id'] + '/resume', {'expected_execution_version': t['execution_version'], 'note': '已到料'}, status=409)
        self.confirm_checks(t)
        t = self.request('/api/tasks/' + t['id'] + '/resume', {'expected_execution_version': t['execution_version'], 'note': '追加物料齐套且已核验'})['task']
        self.assertEqual(t['remaining_quantity'], 1)
        self.status(t, 'done')
        sessions = self.rows('work_sessions')
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(s['ended_at'] for s in sessions))

    def test_quality_rework_requires_completion_and_reinspection(self):
        f = self.fixture(nodes=self.simple_nodes(quality=True))
        t = f['tasks'][0]
        second = self.request('/api/operations/people', {'name': '返工工人', 'factory_id': f['factory']['id'], 'skills': ['装配'], 'capacity_minutes': 480})['person']
        self.confirm_checks(t)
        t = self.status(t, 'in_progress')['task']
        inspection = self.request('/api/production/inspections', {'task_id': t['id'], 'expected_task_version': t['execution_version'],
            'result': 'failed', 'note': '孔位偏差需要返工', 'create_rework': True, 'quantity': 1,
            'rework_note': '修正孔位后重新核对', 'owner_id': second['id']})
        rework = inspection['rework']
        self.assertEqual(rework['status'], 'draft')
        self.status(t, 'done', expected=409)
        self.request('/api/production/inspections', {'task_id': t['id'], 'result': 'passed', 'note': '尚有返工'}, status=409)
        self.status(rework, 'in_progress', expected=409)
        rework = self.request('/api/production/reworks/' + rework['id'] + '/release', {'expected_task_version': rework['execution_version'], 'note': '返工范围及要求核对完成'})['task']
        rework = self.status(rework, 'in_progress')['task']
        self.status(rework, 'done')
        self.request('/api/production/inspections', {'task_id': t['id'], 'result': 'passed', 'note': '返工后重新测量合格'})
        self.status(t, 'done')
        self.assertEqual(len(self.rows('inspections')), 2)

    def test_quality_pause_invalidates_previously_passed_inspection(self):
        f = self.fixture(nodes=self.simple_nodes(quality=True))
        t = f['tasks'][0]
        self.confirm_checks(t)
        t = self.status(t, 'in_progress')['task']
        self.request('/api/production/inspections', {'task_id': t['id'], 'result': 'passed', 'note': '首次检验合格'})
        t = self.request('/api/tasks/' + t['id'] + '/pause', {'expected_execution_version': t['execution_version'],
            'reason': 'quality', 'note': '首次检验后发现外观异常', 'handover_note': '待重新处理并复检'})['task']
        self.confirm_checks(t)
        t = self.request('/api/tasks/' + t['id'] + '/resume', {'expected_execution_version': t['execution_version'], 'note': '外观问题已修复，准备复检'})['task']
        self.status(t, 'done', expected=409)
        self.request('/api/production/inspections', {'task_id': t['id'], 'result': 'passed', 'note': '异常处理后复检合格'})
        self.status(t, 'done')

    def test_failed_reinspection_blocks_successor_and_project_shipping(self):
        nodes = self.simple_nodes(quality=True) + [operations.node('next', '包装', '装配', predecessors=('work',), acceptance=('包装完好',))]
        f = self.fixture(nodes=nodes)
        first, second = f['tasks']
        self.confirm_checks(first)
        first = self.status(first, 'in_progress')['task']
        self.request('/api/production/inspections', {'task_id': first['id'], 'result': 'passed', 'note': '首检合格'})
        first = self.status(first, 'done')['task']
        self.request('/api/production/inspections', {'task_id': first['id'], 'result': 'failed', 'note': '完工后复查发现划伤'})
        self.status(second, 'in_progress', expected=409)
        endpoint = '/api/projects/' + first['project_id'] + '/fulfillment'
        for target in ('completed', 'shipped'):
            for confirm in (False, True):
                self.request(endpoint, {'status': target, 'confirm_unfinished': confirm}, status=409)
        self.assertEqual(self.row('projects', first['project_id'])['fulfillment_status'], 'active')
        self.request('/api/production/inspections', {'task_id': first['id'], 'result': 'passed', 'note': '划伤处理后复检合格'})
        second = self.status(second, 'in_progress')['task']
        self.status(second, 'done')
        self.request(endpoint, {'status': 'shipped'})
        self.assertEqual(self.row('projects', first['project_id'])['fulfillment_status'], 'shipped')

    def test_closed_project_time_is_excluded_on_reopen(self):
        f = self.fixture(nodes=self.simple_nodes())
        t = f['tasks'][0]
        self.confirm_checks(t)
        with patch.object(production, 'stamp', return_value='2026-09-05T08:00:00+00:00'):
            t = self.status(t, 'in_progress')['task']
        endpoint = '/api/projects/' + t['project_id'] + '/fulfillment'
        with patch.object(production, 'stamp', return_value='2026-09-05T08:20:00+00:00'):
            self.request(endpoint, {'status': 'completed', 'confirm_unfinished': True})
        sessions = self.rows('work_sessions')
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['minutes'], 20)
        self.assertEqual(sessions[0]['end_status'], 'project_closed')
        with patch.object(production, 'stamp', return_value='2026-09-05T12:00:00+00:00'):
            self.request(endpoint, {'status': 'active'})
        with patch.object(production, 'stamp', return_value='2026-09-05T12:15:00+00:00'):
            self.status(self.row('tasks', t['id']), 'done')
        sessions = self.rows('work_sessions')
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(s['minutes'] for s in sessions), 35)
        self.assertTrue(all(s['ended_at'] for s in sessions))

    def test_issue_resolution_and_workflow_predecessors_are_enforced(self):
        f = self.fixture('machinery')
        first, second = f['tasks'][:2]
        self.confirm_checks(second)
        self.status(second, 'in_progress', expected=409)
        issue = self.request('/api/production/issues', {'project_id': first['project_id'], 'task_id': first['id'],
            'type': 'drawing', 'title': '尺寸需确认'})['issue']
        self.confirm_checks(first)
        self.status(first, 'in_progress', expected=409)
        self.request('/api/production/issues', dict(issue, expected_version=issue['version'], status='resolved'), status=400)
        self.request('/api/production/issues', dict(issue, expected_version=issue['version'], status='resolved', resolution='技术员已经确认图纸R1'))
        first = self.status(first, 'in_progress')['task']
        self.status(first, 'done')
        self.status(second, 'in_progress')

    def test_unknown_capacity_is_not_used_for_automatic_assignment(self):
        f = self.fixture(nodes=self.simple_nodes(), capacity=None)
        t = f['tasks'][0]
        self.request('/api/tasks/' + t['id'] + '/assign', {'person_id': None, 'expected_execution_version': t['execution_version']})
        result = self.request('/api/projects/' + t['project_id'] + '/auto-assign', {})
        self.assertEqual(result['assignments'], [])
        self.assertTrue(result['skipped'])

    def badge_fixture(self):
        f = self.fixture(nodes=self.simple_nodes())
        t = f['tasks'][0]
        self.confirm_checks(t)
        delivery = {'id': 'delivery_e2e', 'task_id': t['id'], 'device_id': 'badge_e2e', 'revision': t['revision'],
                    'assignee_id': t['assignee'], 'status': 'received', 'test_mode': False, 'project_id': t['project_id']}
        with self.store.connect() as con:
            self.store.put(con, 'device_deliveries', delivery)
        frame = dict(type='execution_event', protocol=1, event_id='event_e2e', device_id='badge_e2e',
                     delivery_id=delivery['id'], task_id=t['id'], revision=t['revision'], execution_version=t['execution_version'], action='start')
        return f, t, delivery, frame

    def test_badge_idempotency_conflict_and_durable_work_sessions(self):
        f, t, _, frame = self.badge_fixture()
        first = self.store.handle_device_execution(frame)
        self.assertTrue(first['accepted'])
        duplicate = self.store.handle_device_execution(frame)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(first['task']['execution_version'], duplicate['task']['execution_version'])
        self.assertEqual(len(self.rows('work_sessions')), 1)
        self.assertEqual(len(self.rows('badge_execution_events')), 1)
        changed = self.store.handle_device_execution(dict(frame, action='finish', completed_quantity=2))
        self.assertFalse(changed['accepted'])
        self.assertEqual(changed['code'], 'event_id_conflict')
        reloaded = app.Store(self.temp.name, seed=False)
        self.assertTrue(reloaded.handle_device_execution(frame)['duplicate'])
        self.assertEqual(len(self.rows('work_sessions')), 1)

    def test_concurrent_badge_retry_is_one_transaction_and_one_work_session(self):
        _, _, _, frame = self.badge_fixture()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.store.handle_device_execution, [frame, copy.deepcopy(frame)]))
        self.assertTrue(all(r['accepted'] for r in results))
        self.assertEqual(sum(bool(r.get('duplicate')) for r in results), 1)
        self.assertEqual(len(self.rows('work_sessions')), 1)
        self.assertEqual(len(self.rows('badge_execution_events')), 1)

    def test_badge_rejects_unreceived_demo_wrong_device_and_stale_version(self):
        _, t, delivery, frame = self.badge_fixture()
        for i, changes in enumerate(({'status': 'sent'}, {'test_mode': True}, {'device_id': 'other_badge'})):
            with self.store.connect() as con:
                self.store.put(con, 'device_deliveries', dict(delivery, **changes))
            self.assertFalse(self.store.handle_device_execution(dict(frame, event_id='bad_' + str(i)))['accepted'])
        with self.store.connect() as con:
            self.store.put(con, 'device_deliveries', delivery)
        self.assertFalse(self.store.handle_device_execution(dict(frame, event_id='stale', execution_version=t['execution_version'] - 1))['accepted'])
        self.assertEqual(self.row('tasks', t['id'])['status'], 'ready')
        self.assertEqual(self.rows('work_sessions'), [])

    def test_badge_old_delivery_cannot_execute_after_reassignment(self):
        f, t, _, frame = self.badge_fixture()
        p2 = self.request('/api/operations/people', {'name': '第二负责人', 'factory_id': f['factory']['id'], 'skills': ['装配'], 'capacity_minutes': 480})['person']
        t = self.request('/api/tasks/' + t['id'] + '/assign', {'person_id': p2['id'], 'expected_execution_version': t['execution_version']})['task']
        result = self.store.handle_device_execution(dict(frame, execution_version=t['execution_version']))
        self.assertFalse(result['accepted'])
        self.assertIn('负责人', result['message'])

    def test_badge_cannot_bypass_inspection_gate_even_after_pass_record(self):
        f = self.fixture(nodes=self.simple_nodes(quality=True))
        t = f['tasks'][0]
        self.confirm_checks(t)
        t = self.status(t, 'in_progress')['task']
        self.request('/api/production/inspections', {'task_id': t['id'], 'result': 'passed', 'note': '检验已记录但仍须Web确认'})
        with self.store.connect() as con:
            self.store.put(con, 'device_deliveries', {'id': 'd_quality', 'task_id': t['id'], 'revision': t['revision'],
                'assignee_id': t['assignee'], 'device_id': 'badge_e2e', 'status': 'received', 'test_mode': False})
        result = self.store.handle_device_execution(dict(type='execution_event', protocol=1, event_id='e_quality',
            device_id='badge_e2e', delivery_id='d_quality', task_id=t['id'], revision=t['revision'], execution_version=t['execution_version'], action='finish', completed_quantity=2))
        self.assertFalse(result['accepted'])
        self.assertEqual(self.row('tasks', t['id'])['status'], 'in_progress')

    @unittest.skipUnless(device_fixture.POSIX_PTY_AVAILABLE, 'POSIX pseudo-terminal required')
    def test_http_workflow_through_usb_delivery_and_real_business_ack(self):
        f = self.fixture(nodes=self.simple_nodes())
        task = f['tasks'][0]
        self.confirm_checks(task)
        self.badge = device_fixture.BadgeEmulator()
        self.server.device_bridge.disconnect()
        bridge = DeviceBridge(self.store, serial_factory=device_fixture.PTYSerial,
            port_provider=lambda: [SimpleNamespace(device=self.badge.port, vid=0x303A)],
            handshake_timeout=.5, receipt_timeout=.5, execution_handler=self.store.handle_device_execution)
        self.server.device_bridge = bridge
        self.badge.reply_task = self.badge.ack
        self.request('/api/device/connect', {'port': self.badge.port})
        sent = self.request('/api/tasks/' + task['id'] + '/send-device', {'test_mode': False})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            deliveries = bridge.deliveries()['deliveries']
            if deliveries and deliveries[0]['status'] == 'received':
                break
            time.sleep(.01)
        self.assertEqual(deliveries[0]['status'], 'received')
        self.assertEqual(self.row('tasks', task['id'])['status'], 'ready')
        self.assertEqual(self.rows('work_sessions'), [])
        frame = dict(type='execution_event', protocol=1, event_id='pty_event_e2e', device_id=self.badge.hello_device_id,
            task_id=task['id'], delivery_id=deliveries[0]['id'], revision=task['revision'], execution_version=task['execution_version'], action='start')
        self.badge.send(frame)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(m.get('type') == 'execution_ack' for m in self.badge.messages):
            time.sleep(.01)
        ack = next(m for m in self.badge.messages if m.get('type') == 'execution_ack')
        self.assertTrue(ack['accepted'], ack)
        self.assertEqual(ack['task']['status'], 'in_progress')
        self.assertEqual(len(self.rows('work_sessions')), 1)


if __name__ == '__main__':
    unittest.main()
