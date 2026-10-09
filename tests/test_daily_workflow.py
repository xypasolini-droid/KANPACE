"""Isolated HTTP + device-event acceptance tests; never access a real badge."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import access_control
from device_bridge import DELIVERY_KIND


DAY = '2026-09-14'


class DailyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            for person_id in ('person_a', 'person_b'):
                self.store.put(con, 'people', {'id': person_id, 'name': person_id, 'skills': ['木工'],
                    'role': '木工', 'capacity_minutes': 480, 'demo': False})
            self.project = self.store.new_project(con, {'name': '隔离标签测试订单', 'factory_type': 'cabinet'})
            self.project.update(status='released', released_revision=1)
            self.store.put(con, 'projects', self.project)
            for task_id, person_id, day in (('task_a', 'person_a', DAY), ('task_b', 'person_b', DAY),
                                             ('task_tomorrow', 'person_a', '2026-09-15')):
                task = {'id': task_id, 'project_id': self.project['id'], 'revision': 1, 'title': '侧板开料 ' + task_id,
                    'trade': '木工', 'process': 'cut', 'status': 'ready', 'assignee': person_id, 'quantity': 2,
                    'completed_quantity': 0, 'hours': 1, 'dependencies': [], 'execution_version': 0, 'demo': False, 'archived': False}
                self.store.put(con, 'tasks', task)
                self.store.put(con, 'plans', {'id': 'plan_' + task_id, 'project_id': self.project['id'], 'task_id': task_id,
                    'task_revision': 1, 'person_id': person_id, 'status': 'scheduled', 'start_date': day, 'end_date': day,
                    'allocations': [{'date': day, 'minutes': 60}], 'material_status': 'ready', 'version': 1})
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        access_control.clear_actor()
        self.temp.cleanup()

    def request(self, path, data=None, cookie=None, origin=None):
        headers = {'Accept': 'application/json', 'Origin': origin or self.base}
        if cookie:
            headers['Cookie'] = cookie.split(';', 1)[0]
        content = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        if content is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + path, data=content, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read()), dict(response.headers)

    def prepare(self, ids=None, **extra):
        return self.request('/api/daily-workflow/labels/prepare', {'date': DAY, 'task_ids': ids or ['task_a'], **extra})

    def finish(self, identifier='task_a'):
        status, started, _ = self.request('/api/tasks/' + identifier + '/status', {'status': 'in_progress', 'expected_execution_version': 0})
        self.assertEqual(status, 200, started)
        status, finished, _ = self.request('/api/tasks/' + identifier + '/status',
            {'status': 'done', 'completed_quantity': 2, 'expected_execution_version': 1})
        self.assertEqual(status, 200, finished)

    def issue(self):
        return self.request('/api/daily-workflow/handovers/issue',
            {'date': DAY, 'device_id': 'badge_test', 'person_id': 'person_a', 'task_ids': ['task_a']})

    def add_shared_piece(self):
        with self.store.connect() as con:
            self.store.put(con, 'parts', {'id': 'part_panel', 'project_id': self.project['id'], 'revision': 1,
                'name': '左侧板', 'cabinet_name': '高柜 01', 'material': '多层板', 'length': 1900, 'width': 300,
                'thickness': 18, 'unit': 'mm', 'quantity': 2})
            task = self.store.get(con, 'tasks', 'task_a')
            task['part_id'] = 'part_panel'
            self.store.put(con, 'tasks', task)
            edge = dict(task, id='task_edge', title='左侧板封边', process='edge', assignee='person_b', dependencies=['task_a'])
            self.store.put(con, 'tasks', edge)
            plan = self.store.get(con, 'plans', 'plan_task_a')
            self.store.put(con, 'plans', dict(plan, id='plan_edge', task_id='task_edge', person_id='person_b'))

    def test_same_piece_reuses_one_label_across_stages_but_confirmation_is_per_stage(self):
        self.add_shared_piece()
        status, prepared, _ = self.prepare(['task_a', 'task_edge'])
        self.assertEqual(status, 200, prepared)
        self.assertEqual((prepared['created_count'], prepared['physical_label_count']), (2, 2))
        cut = [label for label in prepared['labels'] if label['task_id'] == 'task_a']
        edge = [label for label in prepared['labels'] if label['task_id'] == 'task_edge']
        self.assertEqual([label['id'] for label in cut], [label['id'] for label in edge])
        self.assertEqual(cut[0]['dimensions_mm'], {'length': 1900, 'width': 300, 'thickness': 18})
        self.assertEqual((cut[0]['unit'], cut[0]['dimension_unit'], cut[0]['cabinet_name']), ('件', 'mm', '高柜 01'))
        self.finish()
        for label in cut:
            self.assertEqual(self.request('/api/daily-workflow/labels/' + label['id'] + '/confirm', {'task_id': 'task_a', 'revision': 1})[0], 200)
        board = self.request('/api/daily-workflow?date=' + DAY)[1]
        self.assertEqual(board['summary']['label_count'], 2)
        self.assertEqual(next(task for task in board['tasks'] if task['id'] == 'task_edge')['labels']['confirmed'], 0)
        self.assertEqual(self.request('/api/daily-workflow/labels/' + cut[0]['id'] + '/confirm', {'task_id': 'task_edge', 'revision': 1})[0], 409)
        self.finish('task_edge')
        for label in edge:
            status, result, _ = self.request('/api/daily-workflow/labels/' + label['id'] + '/confirm', {'task_id': 'task_edge', 'revision': 1})
            self.assertEqual(status, 200, result)
            self.assertEqual(result['label']['task_id'], 'task_edge')
        with self.store.read_transaction() as con:
            self.assertEqual(len(self.store.all(con, 'daily_labels')), 2)
            self.assertEqual(len(self.store.all(con, 'label_confirmations')), 4)
            self.assertEqual(self.store.get(con, 'tasks', 'task_edge')['completed_quantity'], 2)

    def test_physical_label_rejects_stage_quantity_mismatch(self):
        self.add_shared_piece()
        self.prepare(['task_a'])
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', 'task_edge')
            task['quantity'] = 3
            self.store.put(con, 'tasks', task)
        self.assertEqual(self.prepare(['task_edge'])[0], 409)
        with self.store.read_transaction() as con:
            self.assertEqual(len(self.store.all(con, 'daily_labels')), 2)

    def test_preparation_does_not_create_more_pieces_than_engineering_part(self):
        self.add_shared_piece()
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', 'task_a')
            task['quantity'] = 3
            self.store.put(con, 'tasks', task)
        self.assertEqual(self.prepare()[0], 409)
        with self.store.read_transaction() as con:
            self.assertEqual(self.store.all(con, 'daily_labels'), [])

    def test_legacy_printed_labels_keep_ids_and_stage_confirmations_when_deduplicated(self):
        self.add_shared_piece()
        prepared = self.prepare()[1]['labels']
        with self.store.connect() as con:
            old = self.store.get(con, 'daily_labels', prepared[0]['id'])
            old.pop('physical_identity')
            old.update(status='confirmed', confirmed_at='2026-09-14T10:00:00Z', part_name='')
            self.store.put(con, 'daily_labels', old)
            self.store.put(con, 'daily_labels', dict(old, id='label_legacy_edge', task_id='task_edge'))
        status, again, _ = self.prepare(['task_a', 'task_edge'])
        self.assertEqual(status, 200, again)
        self.assertEqual(again['created_count'], 0)
        self.assertEqual(again['physical_label_count'], 2)
        same_piece = [label for label in again['labels'] if label['sequence'] == 1]
        self.assertTrue(all(label['id'] == prepared[0]['id'] and label['status'] == 'confirmed' for label in same_piece))
        self.assertTrue(all(label['part_name'] == '左侧板' for label in same_piece))
        with self.store.read_transaction() as con:
            self.assertEqual(len(self.store.all(con, 'daily_labels')), 3)
        rack = self.request('/api/daily-workflow/locations', {'code': '01-007'})[1]['location']
        self.assertEqual(self.request('/api/daily-workflow/labels/label_legacy_edge/location',
            {'location_id': rack['id'], 'expected_location_version': 0})[0], 200)
        lookup = self.request('/api/daily-workflow/labels/' + prepared[0]['id'])[1]['label']
        self.assertEqual(lookup['current_location']['code'], '01-007')
        self.assertEqual(len(self.request('/api/daily-workflow/locations/' + rack['id'])[1]['labels']), 1)

    def test_persistent_rack_labels_and_optimistic_piece_location_binding(self):
        self.add_shared_piece()
        label = self.prepare()[1]['labels'][0]
        status, created, _ = self.request('/api/daily-workflow/locations', {'code': '01-007', 'name': '木工架'})
        self.assertEqual(status, 200, created)
        location = created['location']
        self.assertEqual(location['qr_payload'], 'KANPACE:LOCATION:' + location['id'])
        self.assertTrue(self.request('/api/daily-workflow/locations', {'code': '01-007', 'name': '木工架'})[1]['duplicate'])
        self.assertEqual(self.request('/api/daily-workflow/locations', {'code': '01-007', 'name': '不同货架'})[0], 409)
        self.assertEqual(self.request('/api/daily-workflow/locations', {'code': '../invalid'})[0], 400)
        second = self.request('/api/daily-workflow/locations', {'code': '02-003'})[1]['location']
        path = '/api/daily-workflow/labels/' + label['id'] + '/location'
        payload = {'location_id': location['id'], 'expected_location_version': 0}
        status, placed, _ = self.request(path, payload)
        self.assertEqual(status, 200, placed)
        self.assertEqual(placed['label']['location_version'], 1)
        self.assertTrue(self.request(path, payload)[1]['duplicate'])
        self.assertEqual(self.request(path, dict(payload, location_id=second['id']))[0], 409)
        self.assertEqual(self.request(path, dict(payload, location_id=second['id'], expected_location_version=1))[0], 200)
        self.assertEqual(len(self.request('/api/daily-workflow/locations/' + location['id'])[1]['labels']), 0)
        self.assertEqual(len(self.request('/api/daily-workflow/locations/' + second['id'])[1]['labels']), 1)
        edge_view = self.request('/api/daily-workflow/labels/' + label['id'] + '?task_id=task_edge')[1]['label']
        self.assertEqual(edge_view['current_location']['code'], '02-003')
        self.assertEqual(edge_view['status'], 'prepared')
        with self.store.read_transaction() as con:
            self.assertEqual(self.store.get(con, 'tasks', 'task_a')['completed_quantity'], 0)
            self.assertEqual(self.store.get(con, 'tasks', 'task_a')['execution_version'], 0)

    def test_day_reads_saved_plans_only_filters_scene_and_survives_restart(self):
        status, board, _ = self.request('/api/daily-workflow?date=' + DAY)
        self.assertEqual(status, 200, board)
        self.assertEqual({task['id'] for task in board['tasks']}, {'task_a', 'task_b'})
        self.assertEqual(board['summary']['labels_pending'], 4)
        self.assertEqual(board['tasks'][0]['plan_minutes'], 60)
        self.assertEqual(self.request('/api/daily-workflow?date=2026-09-15')[1]['summary']['task_count'], 1)
        self.assertEqual(self.request('/api/daily-workflow?date=' + DAY + '&factory_type=machinery')[1]['tasks'], [])
        self.assertEqual(self.request('/api/daily-workflow?date=2026-02-30')[0], 400)
        self.assertEqual(self.request('/api/daily-workflow?date=2026-9-14')[0], 400)
        self.assertEqual(self.request('/api/daily-workflow?date=' + DAY + '&factory_type=invalid')[0], 400)
        self.prepare()
        other = app.Store(self.temp.name, seed=False)
        with other.read_transaction() as con:
            self.assertEqual(other.daily_workflow.build(con, DAY)['summary']['label_count'], 2)

    def test_labels_reuse_unit_identity_across_retry_and_days_without_changing_quantities(self):
        status, first, _ = self.prepare()
        self.assertEqual(status, 200, first)
        self.assertEqual(first['created_count'], 2)
        self.assertEqual({item['sequence'] for item in first['labels']}, {1, 2})
        self.assertTrue(all(item['quantity'] == 1 and item['qr_payload'].endswith(item['id']) for item in first['labels']))
        second = self.prepare()[1]
        self.assertEqual(second['created_count'], 0)
        self.assertEqual([item['id'] for item in first['labels']], [item['id'] for item in second['labels']])
        with self.store.connect() as con:
            plan = self.store.get(con, 'plans', 'plan_task_a')
            plan['allocations'].append({'date': '2026-09-15', 'minutes': 60})
            self.store.put(con, 'plans', plan)
        third = self.prepare(date='2026-09-15')[1]
        self.assertEqual(third['created_count'], 0)
        self.assertEqual(third['labels'][0]['id'], first['labels'][0]['id'])
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', 'task_a')
            self.assertEqual((task['status'], task['completed_quantity'], task['execution_version']), ('ready', 0, 0))
        self.assertEqual(self.prepare(['task_a', 'task_a'])[0], 400)
        self.assertEqual(self.prepare(['task_b'], date='2026-09-15')[0], 409)

    def test_concurrent_prepare_has_one_unit_set_and_invalid_batch_rolls_back(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.prepare(), range(2)))
        self.assertTrue(all(result[0] == 200 for result in results), results)
        self.assertEqual(sorted(result[1]['created_count'] for result in results), [0, 2])
        self.assertEqual({item['id'] for item in results[0][1]['labels']}, {item['id'] for item in results[1][1]['labels']})
        status, rejected, _ = self.prepare(['task_b', 'task_tomorrow'])
        self.assertEqual(status, 409, rejected)
        with self.store.read_transaction() as con:
            self.assertEqual(len(self.store.all(con, 'daily_labels')), 2)

    def test_confirmation_requires_matching_finished_task_and_is_idempotent(self):
        label = self.prepare()[1]['labels'][0]
        path = '/api/daily-workflow/labels/' + label['id'] + '/confirm'
        payload = {'task_id': 'task_a', 'revision': 1}
        self.assertEqual(self.request(path, payload)[0], 409)
        self.finish()
        self.assertEqual(self.request(path, dict(payload, task_id='task_b'))[0], 409)
        self.assertEqual(self.request(path, dict(payload, revision=True))[0], 409)
        self.assertEqual(self.request(path, dict(payload, revision=2))[0], 409)
        status, result, _ = self.request(path, payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['task_labels']['confirmed'], 1)
        self.assertTrue(self.request(path, payload)[1]['duplicate'])
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', 'task_a')
            self.assertEqual((task['status'], task['completed_quantity'], task['execution_version']), ('done', 2, 3))
        self.assertEqual(self.request('/api/daily-workflow/labels/' + label['id'])[1]['label']['status'], 'confirmed')

    def test_stale_label_and_foreign_factory_id_are_rejected(self):
        label = self.prepare()[1]['labels'][0]
        self.finish()
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', self.project['id'])
            project.update(revision=2, released_revision=2)
            self.store.put(con, 'projects', project)
        self.assertFalse(self.request('/api/daily-workflow/labels/' + label['id'])[1]['label']['current'])
        self.assertEqual(self.request('/api/daily-workflow/labels/' + label['id'] + '/confirm', {'task_id': 'task_a', 'revision': 1})[0], 409)
        with tempfile.TemporaryDirectory() as other_dir:
            other = app.Store(other_dir, seed=False)
            with other.read_transaction() as con:
                with self.assertRaises(app.APIError) as error:
                    other.daily_workflow.label(con, label['id'])
                self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.request('/api/daily-workflow?date=' + DAY)[1]['tasks'], [])

    def test_return_requires_tasks_and_all_unit_labels_and_retries_dont_duplicate(self):
        status, issued, _ = self.issue()
        self.assertEqual(status, 200, issued)
        identifier = issued['handover']['id']
        self.assertTrue(self.issue()[1]['duplicate'])
        self.assertFalse(issued['handover']['can_return'])
        path = '/api/daily-workflow/handovers/' + identifier + '/return'
        status, result, _ = self.request(path, {'expected_version': 1})
        self.assertEqual(status, 409, result)
        self.assertEqual(result['details']['unresolved_tasks'][0]['task_id'], 'task_a')
        self.finish()
        self.assertEqual(self.request(path, {'expected_version': 1})[0], 409)
        labels = self.prepare()[1]['labels']
        for label in labels:
            self.assertEqual(self.request('/api/daily-workflow/labels/' + label['id'] + '/confirm', {'task_id': 'task_a', 'revision': 1})[0], 200)
        self.assertEqual(self.request(path, {'expected_version': True})[0], 400)
        status, returned, _ = self.request(path, {'expected_version': 1})
        self.assertEqual(status, 200, returned)
        self.assertEqual(returned['handover']['status'], 'returned')
        self.assertTrue(self.request(path, {'expected_version': 1})[1]['duplicate'])
        self.assertTrue(self.request(path, {'expected_version': 2})[1]['duplicate'])
        board = self.request('/api/daily-workflow?date=' + DAY)[1]
        self.assertEqual(board['summary']['returned_badges'], 1)
        self.assertEqual(len(board['handovers']), 1)

    def test_issue_rejects_other_person_unscheduled_tasks_and_double_custody(self):
        base = {'date': DAY, 'device_id': 'badge_test', 'person_id': 'person_a', 'task_ids': ['task_b']}
        self.assertEqual(self.request('/api/daily-workflow/handovers/issue', base)[0], 409)
        self.assertEqual(self.request('/api/daily-workflow/handovers/issue', dict(base, task_ids=['task_tomorrow']))[0], 409)
        self.assertEqual(self.issue()[0], 200)
        self.assertEqual(self.request('/api/daily-workflow/handovers/issue', dict(base, person_id='person_b'))[0], 409)
        self.assertEqual(self.request('/api/daily-workflow/handovers/issue', dict(base, device_id='another_badge', task_ids=['task_a']))[0], 409)

    def test_worker_role_is_scoped_and_cross_origin_mutations_rejected(self):
        self.add_shared_piece()
        labels_a = self.prepare()[1]['labels']
        labels_b = self.prepare(['task_b'])[1]['labels']
        self.finish()
        self.finish('task_edge')
        status, _, headers = self.request('/api/access/setup', {'username': 'test_admin', 'name': '管理员', 'password': 'isolated-admin-password'})
        self.assertEqual(status, 200)
        admin = headers['Set-Cookie']
        self.assertEqual(self.request('/api/daily-workflow?date=' + DAY)[0], 401)
        status, created, _ = self.request('/api/access/users', {'username': 'test_worker', 'name': '工人', 'role': 'worker',
            'person_id': 'person_a', 'password': 'isolated-worker-password'}, admin)
        self.assertEqual(status, 200, created)
        status, _, headers = self.request('/api/access/login', {'username': 'test_worker', 'password': 'isolated-worker-password'})
        self.assertEqual(status, 200)
        worker = headers['Set-Cookie']
        status, board, _ = self.request('/api/daily-workflow?date=' + DAY, cookie=worker)
        self.assertEqual(status, 200, board)
        self.assertEqual([task['id'] for task in board['tasks']], ['task_a'])
        self.assertEqual(self.request('/api/daily-workflow?date=' + DAY + '&person_id=person_b', cookie=worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/labels/' + labels_b[0]['id'], cookie=worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/labels/' + labels_b[0]['id'] + '/confirm', {'task_id': 'task_b', 'revision': 1}, worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/labels/' + labels_a[0]['id'] + '/confirm', {'task_id': 'task_a', 'revision': 1}, worker)[0], 200)
        self.assertEqual(self.request('/api/daily-workflow/labels/prepare', {'date': DAY, 'task_ids': ['task_a']}, worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/handovers/issue', {'date': DAY}, worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/locations', {'code': '01-007'}, worker)[0], 403)
        self.assertEqual(self.request('/api/daily-workflow/labels/prepare', {'date': DAY, 'task_ids': ['task_a']}, admin, origin='http://other.invalid')[0], 403)
        status, _, _ = self.request('/api/access/users', {'username': 'test_worker_b', 'name': '封边工', 'role': 'worker',
            'person_id': 'person_b', 'password': 'isolated-worker-password'}, admin)
        self.assertEqual(status, 200)
        _, _, headers = self.request('/api/access/login', {'username': 'test_worker_b', 'password': 'isolated-worker-password'})
        second_worker = headers['Set-Cookie']
        self.assertEqual(self.request('/api/daily-workflow/labels/' + labels_a[0]['id'] + '?task_id=task_edge', cookie=second_worker)[0], 200)
        status, confirmed, _ = self.request('/api/daily-workflow/labels/' + labels_a[0]['id'] + '/confirm',
            {'task_id': 'task_edge', 'revision': 1}, second_worker)
        self.assertEqual(status, 200, confirmed)
        self.assertEqual(confirmed['label']['task_id'], 'task_edge')
        self.assertEqual(self.request('/api/daily-workflow/labels/' + labels_a[0]['id'] + '/confirm',
            {'task_id': 'task_a', 'revision': 1}, second_worker)[0], 403)

    def test_badge_confirm_validates_received_delivery_and_advances_only_label_version(self):
        label = self.prepare()[1]['labels'][0]
        self.finish()
        with self.store.connect() as con:
            self.store.put(con, DELIVERY_KIND, {'id': 'delivery_a', 'project_id': self.project['id'], 'status': 'received',
                'test_mode': False, 'device_id': 'badge_test', 'task_id': 'task_a', 'revision': 1, 'assignee_id': 'person_a'})
        event = {'type': 'execution_event', 'protocol': 1, 'event_id': 'label_event_a', 'device_id': 'badge_test',
                 'delivery_id': 'delivery_a', 'task_id': 'task_a', 'revision': 1, 'execution_version': 2,
                 'action': 'label_confirm', 'label_id': label['id']}
        wrong = self.store.handle_device_execution(dict(event, device_id='badge_other', event_id='wrong_device'))
        self.assertFalse(wrong['accepted'])
        result = self.store.handle_device_execution(event)
        self.assertTrue(result['accepted'], result)
        self.assertEqual(result['task']['execution_version'], 3)
        duplicate = self.store.handle_device_execution(event)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['task']['completed_quantity'], 2)
        conflict = self.store.handle_device_execution(dict(event, label_id='label_other'))
        self.assertEqual(conflict['code'], 'event_id_conflict')
        with self.store.connect() as con:
            labels = self.store.daily_workflow.label_summary(con, self.store.get(con, 'tasks', 'task_a'))
            self.assertEqual((labels['confirmed'], labels['pending']), (1, 1))


if __name__ == '__main__':
    unittest.main()
