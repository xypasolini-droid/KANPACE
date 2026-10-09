"""Finite-capacity scheduling regression; isolated real-resource fixtures only."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import operations
import planning
import production
import scheduling


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        self.count = 0
        with self.store.connect() as con:
            self.factory = operations.save_factory(self.store, con, {'name': '排程实测厂', 'factory_type': 'cabinet'})['factory']
        self.person = self.worker('真实木工')
        self.project = self.project_create()

    def tearDown(self):
        self.temp.cleanup()

    def worker(self, name, capacity=480):
        with self.store.connect() as con:
            return operations.save_person(self.store, con, {'name': name, 'skills': ['木工'], 'capacity_minutes': capacity,
                                           'factory_id': self.factory['id']})['person']

    def project_create(self, due='2026-09-20', typ='cabinet'):
        with self.store.connect() as con:
            project = self.store.new_project(con, {'name': '排程订单', 'factory_type': typ, 'due_date': due})
            project.update(status='released', released_revision=1, factory_id=self.factory['id'])
            self.store.put(con, 'projects', project)
        return project

    def center(self, capacity=480):
        with self.store.connect() as con:
            return operations.save_workcenter(self.store, con, {'name': '封边工位', 'factory_id': self.factory['id'],
                                               'kind': 'station', 'capacity_minutes': capacity})['workcenter']

    def task(self, minutes=60, person=None, project=None, deps=None, wc=None, **extra):
        self.count += 1
        project = project or self.project
        task = {'id': 'task_sched_' + str(self.count), 'project_id': project['id'], 'factory_id': self.factory['id'], 'revision': 1,
                'title': '工序' + str(self.count), 'trade': '木工', 'process': 'cut', 'status': 'ready',
                'assignee': (person or self.person)['id'], 'quantity': 1, 'completed_quantity': 0, 'execution_version': 0,
                'hours': minutes / 60 if minutes is not None else None, 'dependencies': [t['id'] for t in (deps or [])],
                'workcenter_id': wc['id'] if wc else None, 'priority': 0, 'start_checks': [], **extra}
        self.put('tasks', task)
        return task

    def put(self, kind, item):
        with self.store.connect() as con:
            self.store.put(con, kind, item)

    def all(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def preview(self, tasks=None, **extra):
        with self.store.connect() as con:
            return scheduling.preview(self.store, con, {'start_date': '2026-09-07', 'horizon_days': 14,
                                      'task_ids': [t['id'] for t in (tasks or [])], **extra})['scenario']

    def apply(self, scenario):
        with self.store.connect() as con:
            return scheduling.apply(self.store, con, scenario['id'], {'expected_version': scenario['version'], 'note': '厂长核对产能与交期'})

    def test_parallel_people_serial_same_person_and_workcenter_shared(self):
        a = self.task(60)
        b = self.task(60)
        c = self.task(60, person=self.worker('另一个木工'))
        result = self.preview()
        rows = {r['task_id']: r for r in result['rows']}
        self.assertEqual(rows[a['id']]['start_at'], '2026-09-07T08:00')
        self.assertEqual(rows[b['id']]['start_at'], '2026-09-07T09:00')
        self.assertEqual(rows[c['id']]['start_at'], '2026-09-07T08:00')
        wc = self.center()
        a['workcenter_id'] = wc['id']; b['workcenter_id'] = wc['id']; c['workcenter_id'] = wc['id']
        for task in (a, b, c): self.put('tasks', task)
        rows = self.preview()['rows']
        self.assertEqual(sorted(r['start_at'] for r in rows), ['2026-09-07T08:00', '2026-09-07T09:00', '2026-09-07T10:00'])

    def test_predecessors_join_after_longest_parallel_branch(self):
        a = self.task(60)
        b = self.task(120, person=self.worker('并行分支'))
        final = self.task(30, person=self.worker('总装'), deps=[a, b])
        rows = {r['task_id']: r for r in self.preview()['rows']}
        self.assertEqual(rows[final['id']]['start_at'], '2026-09-07T10:00')
        self.assertEqual(rows[final['id']]['end_at'], '2026-09-07T10:30')

    def test_setup_occupies_resources_wait_releases_them_and_gates_next(self):
        wc = self.center()
        a = self.task(60, wc=wc)
        successor = self.task(30, deps=[a], wc=wc)
        independent = self.task(60, person=self.worker('共享工位人员'), wc=wc)
        scenario = self.preview(overrides=[{'task_id': a['id'], 'minutes': 60, 'setup_minutes': 30, 'wait_hours': 2}])
        rows = {r['task_id']: r for r in scenario['rows']}
        self.assertEqual(rows[a['id']]['planned_minutes'], 90)
        self.assertEqual(rows[a['id']]['end_at'], '2026-09-07T09:30')
        self.assertEqual(rows[a['id']]['ready_at'], '2026-09-07T11:30')
        self.assertEqual(rows[independent['id']]['start_at'], '2026-09-07T09:30')
        self.assertEqual(rows[successor['id']]['start_at'], '2026-09-07T11:30')

    def test_unknown_duration_manual_override_and_missing_resource(self):
        a = self.task(None)
        b = self.task(30, deps=[a])
        result = self.preview()
        self.assertEqual(result['summary']['scheduled'], 0)
        self.assertIn('加工时间待确认', result['unplaced'][0]['blockers'])
        resolved = self.preview(overrides=[{'task_id': a['id'], 'minutes': 75}])
        self.assertEqual(resolved['summary']['scheduled'], 2)
        self.assertEqual(resolved['rows'][0]['minutes_source'], 'manual')
        self.assertEqual(resolved['rows'][1]['minutes_source'], 'task_estimate')
        b['assignee'] = None; self.put('tasks', b)
        invalid = self.preview(overrides=[{'task_id': a['id'], 'minutes': 75}])
        self.assertEqual(invalid['summary']['unplaced'], 1)

    def test_missing_material_blocks_or_expected_day_shifts_without_faking_ready(self):
        a = self.task(60)
        material = {'id': 'mat_test', 'project_id': self.project['id'], 'task_ids': [a['id']], 'name': '板材', 'unit': '张',
                    'required_quantity': 3, 'accepted_quantity': 0, 'version': 1, 'expected_date': None}
        self.put('materials', material)
        result = self.preview()
        self.assertEqual(result['summary']['unplaced'], 1)
        material['expected_date'] = '2026-09-09'; self.put('materials', material)
        result = self.preview()
        self.assertEqual(result['rows'][0]['start_at'], '2026-09-09T08:00')
        self.assertTrue(result['rows'][0]['warnings'])
        applied = self.apply(result)
        self.assertEqual(applied['plans'][0]['material_status'], 'pending')
        self.assertEqual(self.all('materials')[0]['accepted_quantity'], 0)

    def test_scope_demo_closed_unreleased_and_invalid_dependencies_rejected(self):
        a = self.task()
        invalid = self.task(deps=[a]); invalid['dependencies'] = ['missing']; self.put('tasks', invalid)
        result = self.preview()
        self.assertEqual(result['summary']['unplaced'], 1)
        self.project['demo'] = True; self.put('projects', self.project)
        with self.assertRaises(production.ProductionError):
            self.preview(tasks=[a])
        self.project['demo'] = False; self.project['fulfillment_status'] = 'shipped'; self.put('projects', self.project)
        with self.assertRaises(production.ProductionError): self.preview(tasks=[a])
        self.project['fulfillment_status'] = 'active'; self.project['status'] = 'review'; self.put('projects', self.project)
        with self.assertRaises(production.ProductionError): self.preview(tasks=[a])

    def test_demo_or_foreign_factory_person_cannot_reserve(self):
        a = self.task()
        a['assignee'] = 'person_1'; self.put('tasks', a)
        result = self.preview()
        self.assertEqual(result['summary']['scheduled'], 0)
        self.assertTrue(any('真实' in b or '本项目' in b or '工厂' in b for b in result['unplaced'][0]['blockers']))
        person = dict(self.person, factory_id='different_factory'); self.put('people', person)
        a['assignee'] = person['id']; self.put('tasks', a)
        self.assertEqual(self.preview()['summary']['scheduled'], 0)

    def test_freezes_existing_daily_plan_and_cross_project_capacity(self):
        a = self.task(120)
        other = self.project_create()
        b = self.task(300, project=other)
        with self.store.connect() as con:
            fixed = planning.save(self.store, con, {'task_id': a['id'], 'start_date': '2026-09-07', 'end_date': '2026-09-07',
                'planned_minutes': 240, 'minutes_source': 'manual', 'material_status': 'ready', 'expected_task_version': 0, 'note': '原排程'})['plan']
        before = deepcopy(self.all('plans'))
        result = self.preview(tasks=[b])
        self.assertEqual(result['frozen_plan_ids'], [fixed['id']])
        row = result['rows'][0]
        self.assertEqual(row['start_at'], '2026-09-07T12:00')
        self.assertEqual(row['end_at'], '2026-09-08T09:00')
        self.assertEqual(row['allocations'], [{'date': '2026-09-07', 'minutes': 240}, {'date': '2026-09-08', 'minutes': 60}])
        self.assertEqual(self.all('plans'), before)

    def test_applied_minute_slots_and_long_wait_survive_next_simulation(self):
        a = self.task(60)
        first = self.preview(tasks=[a], overrides=[{'task_id': a['id'], 'minutes': 60, 'wait_hours': 50}])
        self.apply(first)
        b = self.task(30, deps=[a])
        independent = self.task(60)
        next_scenario = self.preview(tasks=[b, independent])
        rows = {r['task_id']: r for r in next_scenario['rows']}
        self.assertEqual(rows[b['id']]['start_at'], '2026-09-09T11:00')
        self.assertEqual(rows[independent['id']]['start_at'], '2026-09-07T09:00')
        self.apply(next_scenario)
        c = self.task(45)
        third = self.preview(tasks=[c])
        self.assertEqual(third['rows'][0]['start_at'], '2026-09-07T10:00')
        # Prior Wednesday reservations are not falsely moved to Monday morning.
        self.assertEqual(third['rows'][0]['minute_segments'], [{'date': '2026-09-07', 'start_minute': 120, 'end_minute': 165}])

    def test_fragments_exact_slots_around_frozen_waiting_gaps(self):
        a = self.task(60)
        b = self.task(60, deps=[a])
        baseline = self.preview(tasks=[a, b], overrides=[{'task_id': a['id'], 'minutes': 60, 'wait_hours': 2}])
        self.apply(baseline)
        c = self.task(150)
        result = self.preview(tasks=[c])
        row = result['rows'][0]
        self.assertEqual(row['minute_segments'], [
            {'date': '2026-09-07', 'start_minute': 60, 'end_minute': 180},
            {'date': '2026-09-07', 'start_minute': 240, 'end_minute': 270}])
        self.assertEqual(row['start_at'], '2026-09-07T09:00')
        self.assertEqual(row['end_at'], '2026-09-07T12:30')

    def test_rush_impact_and_frozen_reservations_remain_unchanged(self):
        a = self.task(120)
        b = self.task(60)
        result = self.preview(rush_task_ids=[b['id']])
        self.assertEqual(result['rows'][0]['task_id'], b['id'])
        impact = {r['task_id']: r for r in result['impact']}
        self.assertEqual(impact[a['id']]['shift_minutes'], 60)
        self.assertEqual(impact[b['id']]['shift_minutes'], -120)
        self.assertFalse(self.all('plans'))

    def test_rush_impact_reports_tasks_displaced_beyond_horizon(self):
        a = self.task(480)
        b = self.task(480)
        result = self.preview(horizon_days=1, rush_task_ids=[b['id']])
        changes = {r['task_id']: r for r in result['impact']}
        self.assertEqual(changes[a['id']]['change'], 'unplaced')
        self.assertIsNone(changes[a['id']]['after_end'])
        self.assertEqual(changes[b['id']]['change'], 'scheduled')
        self.assertIsNone(changes[b['id']]['before_end'])

    def test_stale_scenario_rejected_before_any_write_and_apply_idempotent(self):
        a = self.task()
        result = self.preview()
        before = deepcopy(self.all('tasks'))
        self.person['capacity_minutes'] = 420; self.put('people', self.person)
        with self.assertRaises(production.ProductionError) as failure:
            self.apply(result)
        self.assertEqual(failure.exception.details['code'], 'scenario_stale')
        self.assertEqual(self.all('plans'), [])
        self.assertEqual(self.all('tasks'), before)
        fresh = self.preview()
        applied = self.apply(fresh)
        repeated = self.apply(fresh)
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(applied['plans'], repeated['plans'])
        self.assertEqual(len(self.all('plans')), 1)
        self.assertEqual(self.all('tasks'), before)

    def test_short_horizon_rejects_capacity_overrun_without_partial_reservation(self):
        a = self.task(481)
        result = self.preview(horizon_days=1)
        self.assertEqual(result['summary']['scheduled'], 0)
        self.assertEqual(result['summary']['unplaced'], 1)
        self.assertFalse(self.all('plans'))
        wc = self.center(60)
        a['workcenter_id'] = wc['id']; a['hours'] = 2; self.put('tasks', a)
        result = self.preview(horizon_days=2)
        self.assertEqual(result['rows'][0]['allocations'], [{'date': '2026-09-07', 'minutes': 60}, {'date': '2026-09-08', 'minutes': 60}])

    def test_fractional_wait_rounds_forward_to_minute_boundary(self):
        a = self.task(10)
        b = self.task(10, deps=[a])
        result = self.preview(overrides=[{'task_id': a['id'], 'minutes': 10, 'wait_hours': .001}])
        rows = {r['task_id']: r for r in result['rows']}
        self.assertEqual(rows[a['id']]['ready_at'], '2026-09-07T08:11')
        self.assertEqual(rows[b['id']]['start_at'], '2026-09-07T08:11')


if __name__ == '__main__':
    unittest.main()
