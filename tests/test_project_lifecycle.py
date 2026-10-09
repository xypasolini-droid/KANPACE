"""Closed orders leave dispatch queues without rewriting production history.

All HTTP requests use a temporary SQLite database. Device writes are mocked;
these tests never connect to a physical serial port or a Wi-Fi badge.
"""
import base64
import unittest
from unittest.mock import Mock, patch

import test_api


class ProjectLifecycleTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    prepared = test_api.APITests.prepared
    execution_prepared = test_api.APITests.execution_prepared
    task_action = test_api.APITests.task_action

    def fulfillment(self, project, status, **extra):
        return self.request('/api/projects/' + project['id'] + '/fulfillment',
                            {'status': status, **extra})

    def close(self, project, status='completed'):
        code, body = self.fulfillment(project, status, confirm_unfinished=True)
        self.assertEqual(code, 200, body)
        self.assertTrue(body['project']['is_closed'])
        self.assertEqual(body['project']['fulfillment_status'], status)
        return body

    def test_unfinished_confirmation_is_atomic_and_keeps_task_progress(self):
        project, _, tasks = self.execution_prepared()
        first = next(t for t in tasks if not t['dependencies'])
        self.assertEqual(self.task_action(first, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.task_action(first, 'progress', {'completed_quantity': 1, 'note': '仅供隔离测试的半成品'})[0], 200)
        before = self.state()
        code, body = self.fulfillment(project, 'completed')
        self.assertEqual(code, 409, body)
        self.assertEqual(body['details']['code'], 'unfinished_tasks')
        self.assertEqual(body['details']['unfinished_task_count'], len(tasks))
        self.assertEqual(body['details']['in_progress_count'], 1)
        self.assertIn(first['id'], {t['id'] for t in body['details']['unfinished_tasks']})
        after_reject = self.state()
        self.assertEqual(before['projects'], after_reject['projects'])
        self.assertEqual(before['tasks'], after_reject['tasks'])
        self.assertEqual(before['events'], after_reject['events'])
        result = self.close(project)
        self.assertEqual(result['unfinished_task_count'], len(tasks))
        after_close = self.state()
        self.assertEqual(before['tasks'], after_close['tasks'])
        closed = next(p for p in after_close['projects'] if p['id'] == project['id'])
        self.assertTrue(closed['closed_at'])
        self.assertTrue(closed['completed_at'])
        self.assertEqual(closed['revision'], next(p for p in before['projects'] if p['id'] == project['id'])['revision'])
        self.assertEqual(closed['status'], 'released')
        self.assertEqual(self.fulfillment(project, 'active')[0], 200)
        after_reopen = self.state()
        self.assertEqual(before['tasks'], after_reopen['tasks'], 'reopening preserves all quantities, statuses, and execution versions')
        reopened = next(p for p in after_reopen['projects'] if p['id'] == project['id'])
        self.assertEqual(reopened['status'], closed['status'])
        self.assertEqual(reopened['released_revision'], closed['released_revision'])

    def test_draft_tasks_also_require_unfinished_confirmation(self):
        project, _, tasks = self.prepared()
        self.assertTrue(all(t['status'] == 'draft' for t in tasks))
        code, body = self.fulfillment(project, 'shipped')
        self.assertEqual(code, 409, body)
        self.assertEqual(body['details']['unfinished_task_count'], len(tasks))
        self.close(project, 'shipped')
        self.assertTrue(all(t['status'] == 'draft' for t in self.state()['tasks']))

    def test_status_validation_idempotency_and_reopening(self):
        project = self.project()
        for bad in ('done', 'archived', '', None, 1, True):
            with self.subTest(status=bad):
                self.assertEqual(self.fulfillment(project, bad)[0], 400)
        self.assertEqual(self.fulfillment(project, 'completed', confirm_unfinished='true')[0], 400)
        first = self.close(project, 'completed')['project']
        before_events = len(self.state()['events'])
        code, duplicate = self.fulfillment(project, 'completed')
        self.assertEqual(code, 200, duplicate)
        self.assertTrue(duplicate['unchanged'])
        self.assertEqual(len(self.state()['events']), before_events)
        shipped = self.close(project, 'shipped')['project']
        self.assertTrue(shipped['shipped_at'])
        self.assertEqual(shipped['completed_at'], first['completed_at'])
        code, reopened = self.fulfillment(project, 'active')
        self.assertEqual(code, 200, reopened)
        self.assertFalse(reopened['project']['is_closed'])
        self.assertFalse(reopened['project'].get('closed_at'))
        self.assertEqual(reopened['project']['completed_at'], first['completed_at'])
        self.assertEqual(reopened['project']['shipped_at'], shipped['shipped_at'])
        self.assertTrue(reopened['project'].get('reopened_at'))

    def test_both_closed_states_block_all_execution_mutations(self):
        project, _, tasks = self.execution_prepared()
        first = next(t for t in tasks if not t['dependencies'])
        another = next(t for t in tasks if t['id'] != first['id'])
        for status in ('completed', 'shipped'):
            with self.subTest(fulfillment=status):
                self.close(project, status)
                before = self.state()['tasks']
                calls = [
                    ('assign', {'person_id': first['assignee']}),
                    ('priority', {'priority': 3, 'reason': '插单测试'}),
                    ('progress', {'completed_quantity': 1, 'note': '报工测试'}),
                    ('pause', {'reason': 'material', 'note': '缺料', 'handover_note': '保留半成品'}),
                    ('resume', {'note': '材料齐套'}),
                    ('switch', {'target_task_id': another['id'], 'reason': 'urgent', 'note': '切换', 'handover_note': '已交接'}),
                ] + [('status', {'status': target, 'note': '状态测试', 'completed_quantity': 2})
                     for target in ('ready', 'in_progress', 'blocked', 'done')]
                for action, data in calls:
                    with self.subTest(action=action, data=data):
                        code, body = self.task_action(first, action, data)
                        self.assertEqual(code, 409, body)
                for action in ('generate', 'release', 'auto-assign'):
                    code, body = self.request('/api/projects/' + project['id'] + '/' + action, {})
                    self.assertEqual(code, 409, body)
                before_costs = self.state()
                code, body = self.request('/api/projects/' + project['id'] + '/costs', {'outsourcing_cost': 1234})
                self.assertEqual(code, 409, body)
                self.assertEqual(body['details']['code'], 'project_closed')
                self.assertEqual(self.state()['projects'], before_costs['projects'])
                self.assertEqual(self.state()['events'], before_costs['events'])
                self.assertEqual(self.state()['tasks'], before)

    def test_closed_targets_disappear_from_global_person_and_project_queues(self):
        closed, _, old_tasks = self.execution_prepared()
        active, _, new_tasks = self.execution_prepared()
        self.close(closed, 'shipped')
        old_ids, new_ids = {t['id'] for t in old_tasks}, {t['id'] for t in new_tasks}
        for query in ('', '?project_id=' + closed['id'], '?person_id=' + old_tasks[0]['assignee']):
            code, body = self.request('/api/tasks/queue' + query)
            self.assertEqual(code, 200, body)
            ids = {t['id'] for t in body['tasks']}
            self.assertFalse(ids & old_ids)
            if not query:
                self.assertEqual(ids, new_ids)
        self.assertEqual(self.fulfillment(closed, 'active')[0], 200)
        ids = {t['id'] for t in self.request('/api/tasks/queue')[1]['tasks']}
        self.assertTrue(old_ids <= ids)

    def test_old_in_progress_task_does_not_block_an_active_order_for_same_worker(self):
        closed, _, old_tasks = self.execution_prepared()
        old = next(t for t in old_tasks if not t['dependencies'])
        self.assertEqual(self.task_action(old, 'status', {'status': 'in_progress'})[0], 200)
        self.close(closed)
        active, _, new_tasks = self.execution_prepared()
        new = next(t for t in new_tasks if not t['dependencies'] and t['trade'] == old['trade'])
        self.assertEqual(new['assignee'], old['assignee'])
        code, result = self.task_action(new, 'status', {'status': 'in_progress'})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['task']['status'], 'in_progress')
        self.assertEqual(next(t for t in self.state()['tasks'] if t['id'] == old['id'])['status'], 'in_progress')

    def test_switch_to_closed_order_is_atomic(self):
        closed, _, old_tasks = self.execution_prepared()
        target = next(t for t in old_tasks if not t['dependencies'])
        self.close(closed)
        _, _, new_tasks = self.execution_prepared()
        source = next(t for t in new_tasks if not t['dependencies'] and t['trade'] == target['trade'])
        self.assertEqual(self.task_action(source, 'status', {'status': 'in_progress'})[0], 200)
        before = self.state()['tasks']
        code, body = self.task_action(source, 'switch', {'target_task_id': target['id'], 'reason': 'urgent',
                                                        'note': '切换到历史项目', 'handover_note': '保持现场'})
        self.assertEqual(code, 409, body)
        self.assertEqual(self.state()['tasks'], before)

    def test_reopening_preserved_work_cannot_double_book_a_worker(self):
        closed, _, old_tasks = self.execution_prepared()
        old = next(t for t in old_tasks if not t['dependencies'])
        self.assertEqual(self.task_action(old, 'status', {'status': 'in_progress'})[0], 200)
        self.close(closed)
        _, _, new_tasks = self.execution_prepared()
        current = next(t for t in new_tasks if not t['dependencies'] and t['trade'] == old['trade'])
        self.assertEqual(self.task_action(current, 'status', {'status': 'in_progress'})[0], 200)
        before = self.state()
        code, body = self.fulfillment(closed, 'active')
        self.assertEqual(code, 409, body)
        self.assertEqual(body['details']['code'], 'reopen_conflicts')
        self.assertIn(current['id'], {t['id'] for t in body['details']['conflicting_tasks']})
        self.assertEqual(self.state()['projects'], before['projects'])
        self.assertEqual(self.state()['tasks'], before['tasks'])
        self.assertEqual(self.task_action(current, 'pause', {'reason': 'other', 'note': '现场交接', 'handover_note': '可返回原项目'})[0], 200)
        self.assertEqual(self.fulfillment(closed, 'active')[0], 200)

    def test_closed_engineering_sources_cannot_implicitly_restart_production(self):
        project, part, _ = self.execution_prepared()
        code, unresolved = self.request('/api/import', {'project_id': project['id'], 'filename': 'reference.dwg',
                                                         'content_base64': base64.b64encode(b'AC1027 drawing-reference').decode()})
        self.assertEqual(code, 200, unresolved)
        self.close(project, 'shipped')
        before = self.state()
        calls = [
            ('/api/import', {'project_id': project['id'], 'filename': 'new.csv',
                             'content_base64': base64.b64encode(b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\n').decode()}),
            ('/api/parts', {'project_id': project['id'], 'name': 'New panel', 'material': 'Plywood', 'category': 'wood',
                            'length': 1200, 'width': 600, 'thickness': 18, 'quantity': 1, 'unit': 'mm', 'finish': 'clear'}),
            ('/api/parts/' + part['id'] + '/review', {'approved': False, 'edits': {'length': 1400}}),
            ('/api/documents/' + unresolved['document']['id'] + '/resolve', {'reason': '核对完成'}),
        ]
        for path, data in calls:
            with self.subTest(path=path):
                code, body = self.request(path, data)
                self.assertEqual(code, 409, body)
        after = self.state()
        for key in ('projects', 'parts', 'tasks', 'documents', 'events'):
            self.assertEqual(after[key], before[key], key)

    def test_closed_workload_does_not_bias_automatic_assignment(self):
        code, person = self.request('/api/people', {'name': '第二木工', 'skills': ['木工'], 'capacity_minutes': 480})
        self.assertEqual(code, 200, person)
        candidates = sorted(p['id'] for p in self.state()['people'] if '木工' in p['skills'])
        self.assertEqual(len(candidates), 2)
        closed, _, old_tasks = self.prepared()
        for task in old_tasks:
            if task['trade'] == '木工':
                self.assertEqual(self.task_action(task, 'assign', {'person_id': candidates[0]})[0], 200)
        self.close(closed)
        active, _, new_tasks = self.prepared()
        code, assigned = self.request('/api/projects/' + active['id'] + '/auto-assign', {})
        self.assertEqual(code, 200, assigned)
        wood_ids = {t['id'] for t in new_tasks if t['trade'] == '木工'}
        first_wood = next(row for row in assigned['assignments'] if row['task_id'] in wood_ids)
        self.assertEqual(first_wood['person_id'], candidates[0])

    def test_closed_device_send_rejects_before_any_usb_or_wifi_write(self):
        project, _, tasks = self.execution_prepared()
        target = next(t for t in tasks if not t['dependencies'])
        bridge = self.server.device_bridge
        # Ready-shaped fake transport: an implementation that only checks the
        # handshake would attempt a write, which the mocks record as a failure.
        bridge._serial = Mock()
        bridge._wifi_session = Mock()
        bridge._state.update(state='ready', connected=True, device_id='isolated-badge', transport='usb', port='MOCK')
        for fulfillment in ('completed', 'shipped'):
            self.close(project, fulfillment)
            before = self.state()
            with patch.object(bridge, '_write') as usb, patch.object(bridge, '_http_frame') as wifi:
                for transport in ('usb', 'wifi'):
                    bridge._state['transport'] = transport
                    for test_mode in (False, True):
                        code, result = self.request('/api/tasks/' + target['id'] + '/send-device', {'test_mode': test_mode})
                        self.assertEqual(code, 409, result)
                usb.assert_not_called()
                wifi.assert_not_called()
            after = self.state()
            self.assertEqual(before['tasks'], after['tasks'])
            self.assertEqual(before['events'], after['events'])
            with self.store.connect() as con:
                self.assertEqual(self.store.all(con, 'device_deliveries'), [])

    def test_closed_model_bindings_and_units_are_readable_but_not_writable(self):
        project, source = self.imported()
        _, model = self.imported(project, 'triangle.stl',
                                 b'solid triangle\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid triangle')
        path = '/api/documents/' + model['document']['id'] + '/model-links'
        code, original = self.request(path, {'mesh_key': 'mesh-0', 'part_id': source['parts'][0]['id'], 'unit': 'mm'})
        self.assertEqual(code, 200, original)
        for fulfillment in ('completed', 'shipped'):
            self.close(project, fulfillment)
            for body in ({'unit': 'cm'}, {'mesh_key': 'mesh-0', 'part_id': None},
                         {'mesh_key': 'mesh-0', 'part_id': source['parts'][0]['id']}):
                code, response = self.request(path, body)
                self.assertEqual(code, 409, response)
            code, after = self.request(path)
            self.assertEqual(code, 200, after)
            self.assertEqual(after, original)
        self.assertEqual(self.fulfillment(project, 'active')[0], 200)
        code, updated = self.request(path, {'unit': 'cm'})
        self.assertEqual(code, 200, updated)
        self.assertEqual(updated['unit'], 'cm')
        self.assertEqual(updated['links'], original['links'])

    def test_closed_records_remain_readable_but_leave_current_bi_workload(self):
        closed, _, old_tasks = self.execution_prepared()
        done = next(t for t in old_tasks if not t['dependencies'])
        self.assertEqual(self.task_action(done, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.task_action(done, 'status', {'status': 'done', 'completed_quantity': 2, 'note': '实际完工记录测试'})[0], 200)
        self.close(closed, 'shipped')
        active, _, new_tasks = self.execution_prepared()
        code, bi = self.request('/api/analytics')
        self.assertEqual(code, 200, bi)
        self.assertEqual(bi['summary']['task_total'], len(new_tasks))
        self.assertEqual({p['id'] for p in bi['projects']}, {active['id']})
        self.assertEqual(bi['completion_trend']['total'], 1)
        self.assertTrue(bi['task_index'][done['id']]['historical'])
        old_ids = {t['id'] for t in old_tasks}
        for row in bi['people']:
            self.assertFalse(old_ids & set(row['task_ids']))
        for key in ('paused', 'dependencies', 'unassigned', 'skill_mismatch'):
            self.assertFalse(old_ids & {row['task_id'] for row in bi['blockers'][key]})
        code, scoped = self.request('/api/analytics?project_id=' + closed['id'])
        self.assertEqual(code, 200, scoped)
        self.assertEqual(scoped['summary']['task_total'], 0)
        self.assertEqual(scoped['summary']['known_remaining_planned_hours'], 0)
        self.assertEqual(scoped['completion_trend']['total'], 1)
        for status in ('closed', 'shipped'):
            code, filtered = self.request('/api/analytics?fulfillment_status=' + status)
            self.assertEqual(code, 200, filtered)
            self.assertEqual(filtered['summary']['task_total'], 0)
            self.assertEqual(filtered['summary']['known_remaining_planned_hours'], 0)
            self.assertEqual({p['id'] for p in filtered['closed_projects']}, {closed['id']})
            self.assertEqual(filtered['completion_trend']['total'], 1)
        code, active_only = self.request('/api/analytics?fulfillment_status=active')
        self.assertEqual(code, 200, active_only)
        self.assertEqual(active_only['summary']['task_total'], len(new_tasks))
        self.assertEqual(active_only['closed_projects'], [])
        self.assertEqual(active_only['completion_trend']['total'], 0)
        self.assertEqual(self.request('/api/analytics?fulfillment_status=finished')[0], 400)
        saved = self.state()
        self.assertTrue(old_ids <= {t['id'] for t in saved['tasks']})
        self.assertTrue(any(e['project_id'] == closed['id'] for e in saved['events']))
        for suffix in ('export?format=json', 'quote', 'releases'):
            code, body = self.request('/api/projects/' + closed['id'] + '/' + suffix)
            self.assertEqual(code, 200, body)


if __name__ == '__main__':
    unittest.main()
