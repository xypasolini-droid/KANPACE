"""Deterministic project dispatch tests with a simulated bridge, never USB IO."""
import copy
from datetime import date
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import access_control
import operations
from device_bridge import DeviceError, DELIVERY_KIND
from kanpace.application.project_dispatch import ProjectDispatchCoordinator


class FakeImages:
    def __init__(self):
        self.current = None
        self.starts = []

    def snapshot(self):
        return {'transfer': copy.deepcopy(self.current)}

    def busy(self):
        return bool(self.current and self.current['status'] in ('preparing', 'sending'))

    def start(self, data, actor=None, *, automatic=False):
        self.starts.append((dict(data), automatic))
        self.current = dict(data, id='images_' + str(len(self.starts)), status='preparing', completed_images=0, warnings=[])
        return self.snapshot()


class FakeBridge:
    def __init__(self, store):
        self.store = store
        self._state = {'state': 'ready', 'device_id': 'badge_a', 'transport': 'usb', 'image_support': True, 'image_slots': 6, 'safe_ready_replacement': True}
        self._secrets = {'badge_a': {}, 'badge_b': {}}
        self._lock = threading.RLock()
        self._pending = {}
        self.images = FakeImages()
        self.sent = []
        self.current = {}
        self.execution_pending = 0

    def snapshot(self):
        return {'device': dict(self._state)}

    def _usb_rpc(self, action, **options):
        assert action == 'get_task'
        if options['expected_device_id'] != self._state['device_id']:
            raise DeviceError(409, 'device_changed')
        return {'task': dict(self.current), 'execution_pending': self.execution_pending}

    def send_task(self, task_id, *, dispatch_context=None):
        if self._pending:
            raise AssertionError('must not overwrite while receipt is pending')
        with self.store.connect() as con:
            task = self.store.get(con, 'tasks', task_id)
            assert task['assignee'] == dispatch_context['expected_assignee']
            self.current = dict(task)
            record = {'id': 'delivery_' + str(len(self.sent)), 'project_id': task['project_id'], 'task_id': task_id,
                'device_id': self._state['device_id'], 'status': 'sent', 'revision': task['revision'],
                'dispatch_id': dispatch_context['dispatch_id'], 'dispatch_attempt': dispatch_context.get('attempt', 0)}
            self.store.put(con, DELIVERY_KIND, record)
        self.sent.append(task_id)
        self._pending[record['id']] = record
        return {'delivery': record, 'device': self._state}

    def receipt(self, status='received'):
        with self.store.connect() as con:
            record = self.store.get(con, DELIVERY_KIND, next(iter(self._pending)))
            record.update(status=status, error='simulated lost receipt' if status == 'failed' else None)
            self.store.put(con, DELIVERY_KIND, record)
        self._pending.clear()


class ProjectDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        self.day = date.today().isoformat()
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '隔离项目派工', 'factory_type': 'cabinet'})
            self.project.update(status='released', released_revision=1)
            self.store.put(con, 'projects', self.project)
            self.store.put(con, 'parts', {'id': 'part', 'project_id': self.project['id'], 'revision': 1,
                'name': '左侧板', 'quantity': 1, 'length': 1900, 'width': 300, 'thickness': 18, 'unit': 'mm'})
            for identifier in ('person_a', 'person_b'):
                self.store.put(con, 'people', {'id': identifier, 'name': identifier, 'skills': ['木工'], 'demo': False, 'capacity_minutes': 480})
            for identifier, dependencies, position in (('cut', [], 0), ('edge', ['cut'], 1)):
                self.store.put(con, 'tasks', {'id': identifier, 'title': identifier, 'project_id': self.project['id'], 'part_id': 'part',
                    'revision': 1, 'quantity': 1, 'status': 'ready', 'assignee': 'person_a', 'trade': '木工', 'hours': 1,
                    'dependencies': dependencies, 'execution_version': 0, 'schedule_position': position, 'demo': False})
                self.store.put(con, 'plans', {'id': 'plan_' + identifier, 'project_id': self.project['id'], 'task_id': identifier,
                    'task_revision': 1, 'person_id': 'person_a', 'status': 'scheduled', 'allocations': [{'date': self.day, 'minutes': 60}],
                    'start_date': self.day, 'end_date': self.day, 'material_status': 'ready'})
            self.store.daily_workflow.prepare_labels(con, {'date': self.day, 'task_ids': ['cut', 'edge']})
        self.bridge = FakeBridge(self.store)
        self.coordinator = ProjectDispatchCoordinator(self.store, self.bridge, background=False)
        self.catalog = patch('kanpace.application.project_dispatch.badge_media.catalog', return_value={
            'items': [{'id': 'drawing', 'kind': 'drawing', 'task_match': True}, {'id': 'render', 'kind': 'render', 'task_match': False}], 'warnings': []})
        self.catalog.start()

    def tearDown(self):
        self.catalog.stop()
        self.coordinator.close()
        access_control.clear_actor()
        self.temp.cleanup()

    def bind(self, person='person_a', device='badge_a'):
        with self.store.write_transaction() as con:
            return self.coordinator.bind(con, {'person_id': person, 'device_id': device, 'expected_version': 0})

    def create(self):
        with self.store.write_transaction() as con:
            return self.coordinator.create(con, self.project['id'], {'request_id': 'dispatch_request', 'expected_revision': 1})['dispatch']

    def saved(self, identifier):
        with self.store.read_transaction() as con:
            return self.coordinator.get(con, identifier)['dispatch']

    def complete(self, task_id):
        with self.store.write_transaction() as con:
            task = self.store.get(con, 'tasks', task_id)
            started = self.store.set_status(con, task_id, {'status': 'in_progress', 'expected_execution_version': task['execution_version']})
            self.store.set_status(con, task_id, {'status': 'done', 'completed_quantity': 1, 'expected_execution_version': started['execution_version']})

    def confirm_label(self, task_id):
        with self.store.write_transaction() as con:
            task = self.store.get(con, 'tasks', task_id)
            label = self.store.daily_workflow.task_labels(con, task)[0]
            self.store.daily_workflow.confirm_label(con, label['id'], {'task_id': task_id, 'revision': 1})

    def test_one_to_one_binding_known_connections_and_exact_project_counts(self):
        self.bind()
        with self.store.write_transaction() as con:
            with self.assertRaises(app.APIError):
                self.coordinator.bind(con, {'person_id': 'person_b', 'device_id': 'badge_a', 'expected_version': 0})
            with self.assertRaises(app.APIError):
                self.coordinator.bind(con, {'person_id': 'person_b', 'device_id': 'invented_device', 'expected_version': 0})
            result = self.coordinator.preview(con, self.project['id'])
        self.assertEqual((result['summary']['connected_count'], result['summary']['worker_count'], result['summary']['task_count']), (1, 1, 2))
        self.assertEqual([task['id'] for task in result['workers'][0]['tasks']], ['cut', 'edge'])
        self.assertEqual(result['workers'][0]['tasks'][0]['media']['selected_count'], 2)
        self.assertFalse(next(device for device in result['devices'] if device['id'] == 'badge_b')['connected'])

    def test_receipt_images_completion_and_labels_are_separate_no_rapid_overwrite(self):
        self.bind()
        job = self.create()
        self.assertEqual(self.bridge.sent, [])
        self.coordinator.tick()
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][0]['status'], 'awaiting_receipt')
        self.bridge.receipt()
        self.coordinator.tick()
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][0]['status'], 'images_pending')
        self.assertTrue(self.bridge.images.starts[0][1])
        self.bridge.images.current.update(status='received', completed_images=2)
        self.coordinator.tick()
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][0]['status'], 'active')
        self.complete('cut')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][0]['status'], 'awaiting_labels')
        self.confirm_label('cut')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'edge'])

    def test_failed_receipt_requires_explicit_retry_and_preserves_same_task(self):
        self.bind()
        job = self.create()
        self.coordinator.tick()
        self.bridge.receipt('failed')
        self.coordinator.tick()
        self.assertEqual(self.saved(job['id'])['status'], 'partial_failure')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        with self.store.write_transaction() as con:
            self.coordinator.retry(con, job['id'])
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'cut'])
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][1]['status'], 'queued')

    def test_durable_delivery_recovery_does_not_resend_after_job_snapshot_loss(self):
        self.bind()
        job = self.create()
        self.coordinator.tick()
        with self.store.write_transaction() as con:
            stored = self.store.get(con, 'project_dispatches', job['id'])
            stored['workers'][0]['entries'][0].update(status='queued', delivery_id=None)
            self.store.put(con, 'project_dispatches', stored)
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])

    def test_current_unfinished_task_on_badge_is_never_overwritten(self):
        self.bind()
        self.bind('person_b', 'badge_b')
        with self.store.write_transaction() as con:
            original = self.store.get(con, 'tasks', 'cut')
            other = dict(original, id='other_task', title='另一件未完工任务', status='in_progress', assignee='person_b')
            self.store.put(con, 'tasks', other)
        self.bridge.current = other
        job = self.create()
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, [])
        self.assertEqual(self.saved(job['id'])['workers'][0]['status'], 'waiting_current_task')

    def test_offline_second_worker_waits_without_claiming_connection(self):
        with self.store.write_transaction() as con:
            edge = self.store.get(con, 'tasks', 'edge')
            edge['assignee'] = 'person_b'
            self.store.put(con, 'tasks', edge)
        self.bind()
        self.bind('person_b', 'badge_b')
        job = self.create()
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.assertEqual(self.saved(job['id'])['workers'][1]['status'], 'waiting_device')
        with self.store.read_transaction() as con:
            summary = self.coordinator.preview(con, self.project['id'])['summary']
        self.assertEqual((summary['worker_count'], summary['connected_count'], summary['missing_connection_count']), (2, 1, 1))

    def test_revision_or_owner_changes_fail_without_hardware_write(self):
        self.bind()
        job = self.create()
        with self.store.write_transaction() as con:
            task = self.store.get(con, 'tasks', 'cut')
            task['assignee'] = 'person_b'
            self.store.put(con, 'tasks', task)
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, [])
        self.assertEqual(self.saved(job['id'])['status'], 'partial_failure')

    def test_departure_invalidates_queue_and_releases_badge_for_replacement(self):
        self.bind()
        job = self.create()
        with self.store.write_transaction() as con:
            person = self.store.get(con, 'people', 'person_a')
            operations.save_person(self.store, con,
                {'expected_version': person.get('version', 0), 'employment_status': 'left'}, person['id'])
            bindings = self.store.all(con, 'device_bindings')
            self.assertEqual(len(bindings), 1)
            self.assertTrue(bindings[0]['archived'])
            self.assertEqual(self.coordinator.devices(con)[0]['bound_person_id'], None)
            with self.assertRaises(app.APIError):
                self.coordinator.bind(con, {'person_id': 'person_a', 'device_id': 'badge_a', 'expected_version': 0})
            self.coordinator.bind(con, {'person_id': 'person_b', 'device_id': 'badge_a', 'expected_version': 0})
            for task_id in ('cut', 'edge'):
                self.assertIsNone(self.store.get(con, 'tasks', task_id)['assignee'])
        saved = self.saved(job['id'])
        self.assertEqual(saved['status'], 'partial_failure')
        self.assertEqual([row['status'] for row in saved['workers'][0]['entries']], ['failed', 'failed'])
        self.assertTrue(all('重新分派' in row['error'] for row in saved['workers'][0]['entries']))
        self.assertEqual(self.bridge.sent, [])

    def another_project(self, identifier='rush', priority=0, position=3):
        with self.store.write_transaction() as con:
            project = self.store.new_project(con, {'name': '跨项目急单', 'factory_type': 'cabinet'})
            project.update(status='released', released_revision=1)
            self.store.put(con, 'projects', project)
            task = dict(self.store.get(con, 'tasks', 'cut'), id=identifier, project_id=project['id'],
                        part_id=None, dependencies=[], schedule_dependencies=[], priority=priority, schedule_position=position)
            self.store.put(con, 'tasks', task)
            plan = dict(self.store.get(con, 'plans', 'plan_cut'), id='plan_' + identifier, task_id=identifier, project_id=project['id'])
            self.store.put(con, 'plans', plan)
            self.store.daily_workflow.prepare_labels(con, {'date': self.day, 'task_ids': [identifier]})
            return self.coordinator.create(con, project['id'], {'request_id': 'request_' + identifier, 'expected_revision': 1})['dispatch']

    def receive_images(self):
        self.bridge.receipt()
        self.coordinator.tick()
        self.bridge.images.current.update(status='received', completed_images=2)
        self.coordinator.tick()

    def test_multiple_projects_reorder_next_task_without_interrupting_current_work(self):
        self.bind()
        self.create()
        self.coordinator.tick()
        self.receive_images()
        with self.store.write_transaction() as con:
            task = self.store.get(con, 'tasks', 'cut')
            self.store.set_status(con, 'cut', {'status': 'in_progress', 'expected_execution_version': task['execution_version']})
        other = self.another_project(priority=3)
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.assertNotEqual(self.saved(other['id'])['status'], 'completed')
        with self.store.write_transaction() as con:
            task = self.store.get(con, 'tasks', 'cut')
            self.store.set_status(con, 'cut', {'status': 'done', 'completed_quantity': 1, 'expected_execution_version': task['execution_version']})
        self.confirm_label('cut')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'rush'])
        self.receive_images()
        self.complete('rush')
        self.confirm_label('rush')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'rush', 'edge'])

    def test_ready_task_can_be_reordered_but_pending_badge_execution_cannot(self):
        self.bind()
        self.create()
        self.coordinator.tick()
        self.receive_images()
        self.another_project(priority=3)
        self.bridge.execution_pending = 1
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.bridge.execution_pending = 0
        self.bridge._state['safe_ready_replacement'] = False
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.bridge._state['safe_ready_replacement'] = True
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'rush'])
        self.receive_images()
        with self.store.read_transaction() as con:
            self.assertEqual(self.store.get(con, 'tasks', 'cut')['status'], 'ready')

    def test_latest_same_project_table_order_is_applied_before_send(self):
        self.bind()
        with self.store.write_transaction() as con:
            edge = self.store.get(con, 'tasks', 'edge')
            edge['dependencies'] = []
            self.store.put(con, 'tasks', edge)
        job = self.create()
        with self.store.write_transaction() as con:
            edge = self.store.get(con, 'tasks', 'edge')
            cut = self.store.get(con, 'tasks', 'cut')
            edge['schedule_position'], cut['schedule_position'] = 0, 9
            self.store.put(con, 'tasks', edge)
            self.store.put(con, 'tasks', cut)
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['edge'])
        self.assertEqual(self.saved(job['id'])['workers'][0]['entries'][0]['task_id'], 'edge')

    def test_pause_switch_then_resume_reacquires_real_delivery_and_images(self):
        self.bind()
        self.create()
        self.coordinator.tick()
        self.receive_images()
        self.another_project()
        with self.store.write_transaction() as con:
            a = self.store.get(con, 'tasks', 'cut')
            a = self.store.set_status(con, 'cut', {'status': 'in_progress', 'expected_execution_version': a['execution_version']})
            b = self.store.get(con, 'tasks', 'rush')
            self.store.switch_task(con, 'cut', {'target_task_id': 'rush', 'reason': 'urgent', 'note': '先处理加急项目',
                'handover_note': '已开料，夹具保留', 'completed_quantity': 0, 'expected_execution_version': a['execution_version'],
                'target_expected_execution_version': b['execution_version']})
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'rush'])
        self.receive_images()
        with self.store.write_transaction() as con:
            b = self.store.get(con, 'tasks', 'rush')
            self.store.set_status(con, 'rush', {'status': 'done', 'completed_quantity': 1, 'expected_execution_version': b['execution_version']})
        self.confirm_label('rush')
        with self.store.write_transaction() as con:
            a = self.store.get(con, 'tasks', 'cut')
            self.store.resume_task(con, 'cut', {'note': '急单完成，继续原工件', 'expected_execution_version': a['execution_version']})
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'rush', 'cut'])
        self.receive_images()
        self.assertEqual(len(self.bridge.images.starts), 3)
        with self.store.read_transaction() as con:
            a = self.store.get(con, 'tasks', 'cut')
            self.assertEqual((a['status'], a['completed_quantity']), ('in_progress', 0))
            received = [row for row in self.store.all(con, DELIVERY_KIND) if row['task_id'] == 'cut']
            self.assertEqual(len(received), 2)
            self.assertEqual(sorted(row['dispatch_attempt'] for row in received), [0, 1])

    def test_stop_stale_queue_preserves_task_and_allows_new_revision_queue(self):
        self.bind()
        job = self.create()
        self.coordinator.tick()
        self.receive_images()
        with self.store.write_transaction() as con:
            project = self.store.get(con, 'projects', self.project['id'])
            project.update(status='draft', revision=2)
            self.store.put(con, 'projects', project)
        self.coordinator.tick()
        with self.store.write_transaction() as con:
            preview = self.coordinator.preview(con, self.project['id'])
            self.assertTrue(preview['blockers'])
            self.assertEqual(preview['active_dispatch']['id'], job['id'])
            latest = self.store.get(con, 'project_dispatches', job['id'])
            with self.assertRaises(app.APIError):
                self.coordinator.cancel(con, job['id'], {'expected_version': latest['version'] - 1})
            result = self.coordinator.cancel(con, job['id'], {'expected_version': latest['version']})
            self.assertEqual(result['dispatch']['status'], 'cancelled')
            self.assertTrue(self.coordinator.cancel(con, job['id'], {'expected_version': latest['version']})['duplicate'])
            self.assertEqual(self.store.get(con, 'tasks', 'cut')['status'], 'ready')
            project.update(status='released', released_revision=2)
            self.store.put(con, 'projects', project)
            for identifier in ('cut', 'edge'):
                task = self.store.get(con, 'tasks', identifier)
                task['revision'] = 2
                self.store.put(con, 'tasks', task)
            next_job = self.coordinator.create(con, project['id'], {'request_id': 'revised_request', 'expected_revision': 2})['dispatch']
            self.assertNotEqual(next_job['id'], job['id'])
        self.assertEqual(self.bridge.sent, ['cut'])

    def test_schedule_predecessor_blocks_priority_inversion_until_stage_label_confirmed(self):
        self.bind()
        with self.store.write_transaction() as con:
            edge = self.store.get(con, 'tasks', 'edge')
            edge.update(dependencies=[], schedule_dependencies=['cut'], priority=3)
            self.store.put(con, 'tasks', edge)
        self.create()
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.receive_images()
        self.complete('cut')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut'])
        self.confirm_label('cut')
        self.coordinator.tick()
        self.assertEqual(self.bridge.sent, ['cut', 'edge'])

    def test_create_idempotency_and_cross_factory_dispatch_identity(self):
        self.bind()
        first, second = self.create(), self.create()
        self.assertEqual(first['id'], second['id'])
        with self.store.write_transaction() as con:
            with self.assertRaises(app.APIError):
                self.coordinator.create(con, self.project['id'], {'request_id': 'dispatch_request', 'expected_revision': 2})
        with tempfile.TemporaryDirectory() as other_dir:
            other = app.Store(other_dir, seed=False)
            with other.read_transaction() as con:
                with self.assertRaises(app.APIError):
                    ProjectDispatchCoordinator(other, FakeBridge(other), background=False).get(con, first['id'])


if __name__ == '__main__':
    unittest.main()
