"""Calibration never uses configured task hours as observations."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import calibration


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        self.index = 0
        self.put('people', {'id': 'real_person', 'name': '实测人员', 'demo': False})

    def tearDown(self):
        self.temp.cleanup()

    def put(self, kind, item):
        with self.store.connect() as con:
            self.store.put(con, kind, item)

    def build(self):
        with self.store.connect() as con:
            return calibration.build(self.store, con)

    def fixture(self, minutes=60, quantity=2, demo=False, factory='factory_A', hours=999, split=False):
        self.index += 1
        idx = self.index
        project = {'id': 'project_' + str(idx), 'name': '实测项目', 'factory_type': 'machinery', 'factory_id': factory, 'revision': 1, 'demo': demo}
        start = datetime(2026, 9, idx, 9, tzinfo=timezone.utc)
        finish = start + timedelta(minutes=minutes + (120 if split else 0))
        task = {'id': 'task_' + str(idx), 'project_id': project['id'], 'factory_id': factory, 'revision': 1, 'title': '装配工作', 'trade': '装配',
                'process': 'mechanical', 'unit': '台', 'quantity': quantity, 'completed_quantity': quantity, 'status': 'done', 'hours': hours,
                'started_at': start.isoformat(), 'completed_at': finish.isoformat(), 'acceptance': '按R1要求验收'}
        self.put('projects', project); self.put('tasks', task)
        if split:
            periods = [(start, start + timedelta(minutes=minutes / 2)), (start + timedelta(minutes=minutes / 2 + 120), finish)]
        else:
            periods = [(start, finish)]
        for index, (a, b) in enumerate(periods):
            self.put('work_sessions', {'id': f'session_{idx}_{index}', 'project_id': project['id'], 'task_id': task['id'], 'revision': 1,
                    'person_id': 'real_person', 'started_at': a.isoformat(), 'ended_at': b.isoformat(), 'minutes': (b - a).total_seconds() / 60})
        return project, task

    def test_empty_no_forecast_and_unknown_samples_not_zero(self):
        result = self.build()
        self.assertEqual(result['summary']['status'], 'no_actual_samples')
        self.assertFalse(result['groups'])
        self.assertFalse(result['automatic_application'])

    def test_true_active_minutes_exclude_pause_and_ignore_estimated_hours(self):
        self.fixture(minutes=60, split=True, hours=9999)
        self.fixture(minutes=120, hours=0.01)
        self.fixture(minutes=90, hours=None)
        result = self.build()
        group = result['groups'][0]
        self.assertEqual(group['sample_count'], 3)
        self.assertEqual(group['p50_minutes_per_unit'], 45)
        self.assertEqual(group['p80_minutes_per_unit'], 54)
        self.assertEqual(group['confidence'], 'limited')
        self.assertEqual(sorted(s['active_minutes'] for s in group['samples']), [60, 90, 120])

    def test_demo_and_incomplete_and_legacy_time_never_leak(self):
        self.fixture(demo=True)
        _, task = self.fixture()
        task['status'] = 'in_progress'; self.put('tasks', task)
        _, historical = self.fixture()
        with self.store.connect() as con:
            con.execute("DELETE FROM entities WHERE kind='work_sessions' AND project_id=?", (historical['project_id'],))
        result = self.build()
        self.assertEqual(result['summary']['sample_count'], 0)
        self.assertEqual(result['excluded'], {'demo': 1, 'not_complete': 1, 'no_actual_sessions': 1})

    def test_factory_unit_and_acceptance_keep_different_work_separate(self):
        self.fixture()
        self.fixture(factory='factory_B')
        _, task = self.fixture()
        task['unit'] = '区域'; self.put('tasks', task)
        _, other = self.fixture()
        other['acceptance'] = '不同精度要求'; self.put('tasks', other)
        groups = self.build()['groups']
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(g['sample_count'] == 1 for g in groups))

    def test_rework_duration_is_not_mixed_into_normal_operation_samples(self):
        _, original = self.fixture(minutes=90)
        _, rework = self.fixture(minutes=20)
        rework['rework_of'] = original['id']; self.put('tasks', rework)
        result = self.build()
        self.assertEqual(len(result['groups']), 2)
        groups = {g['work_kind']: g for g in result['groups']}
        self.assertEqual(groups['production']['p50_minutes_per_unit'], 45)
        self.assertEqual(groups['rework']['p50_minutes_per_unit'], 10)

    def test_open_overlapping_and_partial_session_history_rejected(self):
        _, open_task = self.fixture()
        with self.store.connect() as con:
            session = self.store.all(con, 'work_sessions', open_task['project_id'])[0]
        session['ended_at'] = None; self.put('work_sessions', session)
        _, overlap_task = self.fixture()
        with self.store.connect() as con:
            duplicate = self.store.all(con, 'work_sessions', overlap_task['project_id'])[0]
        duplicate['id'] = 'duplicate_session'; self.put('work_sessions', duplicate)
        _, partial = self.fixture()
        partial['started_at'] = '2026-09-03T08:00:00+00:00'; self.put('tasks', partial)
        result = self.build()
        self.assertEqual(result['summary']['sample_count'], 0)
        self.assertIn('open_or_invalid_session', result['excluded'])
        self.assertIn('overlapping_sessions', result['excluded'])
        self.assertIn('incomplete_start_record', result['excluded'])

    def test_costs_are_task_linked_recorded_amount_not_full_quote(self):
        p, task = self.fixture(minutes=80)
        self.put('actual_costs', {'id': 'labor1', 'project_id': p['id'], 'task_id': task['id'], 'category': 'labor', 'amount': 120})
        self.put('actual_costs', {'id': 'labor2', 'project_id': p['id'], 'task_id': task['id'], 'category': 'labor', 'amount': 80})
        self.put('actual_costs', {'id': 'wholeorder', 'project_id': p['id'], 'task_id': None, 'category': 'material', 'amount': 9000})
        group = self.build()['groups'][0]
        self.assertEqual(group['recorded_costs'][0]['p50_per_unit'], 100)
        self.assertEqual(group['recorded_costs'][0]['sample_count'], 1)
        self.assertEqual(len(group['recorded_costs']), 1)
        self.assertIn('不代表完整成本', group['recorded_costs'][0]['basis'])

    def test_estimate_does_not_mutate_task_and_no_same_scope_returns_null(self):
        _, task = self.fixture(minutes=80)
        with self.store.connect() as con:
            self.store.put(con, 'factories', {'id': 'factory_A', 'name': '工厂A', 'factory_type': 'machinery'})
            before = self.store.all(con, 'tasks')
            result = calibration.estimate(self.store, con, {'task_id': task['id'], 'quantity': 3, 'percentile': 'p80'})
            after = self.store.all(con, 'tasks')
        self.assertEqual(result['estimated_minutes'], 120)
        self.assertFalse(result['applied'])
        self.assertEqual(before, after)
        task['status'] = 'ready'; task['acceptance'] = '全新精度'; self.put('tasks', task)
        with self.store.connect() as con:
            empty = calibration.estimate(self.store, con, {'task_id': task['id'], 'quantity': 2})
        self.assertIsNone(empty['estimated_minutes'])
        self.assertEqual(empty['sample_count'], 0)

    def test_temporal_holdout_whole_project_and_independent_error_calculation(self):
        for minutes in (40, 60, 80):
            self.fixture(minutes=minutes, quantity=2)
        p, held = self.fixture(minutes=100, quantity=2)
        result = self.build()
        validation = result['groups'][0]['validation']
        self.assertEqual(validation['status'], 'available')
        self.assertEqual(validation['training_project_count'], 3)
        self.assertEqual(validation['holdout_project_ids'], [p['id']])
        self.assertFalse(set(validation['training_project_ids']) & set(validation['holdout_project_ids']))
        prediction = validation['predictions'][0]
        self.assertEqual(prediction['predicted_minutes'], 60)
        self.assertEqual(prediction['actual_minutes'], 100)
        self.assertEqual(prediction['absolute_error_minutes'], 40)
        self.assertEqual(prediction['relative_error_percent'], 40)
        self.assertEqual(prediction['p80_predicted_minutes'], 72)
        self.assertFalse(prediction['p80_covered'])
        self.assertEqual(result['validation_summary']['mape_percent'], 40)
        # Whole-data P50 is 70, proving holdout was not included in training.
        self.assertEqual(result['groups'][0]['p50_minutes_per_unit'], 35)

    def test_many_rows_from_one_project_do_not_create_fake_validation(self):
        first_project = None
        for _ in range(5):
            p, task = self.fixture()
            if first_project is None:
                first_project = p['id']
            else:
                task['project_id'] = first_project
                self.put('tasks', task)
                with self.store.connect() as con:
                    for session in self.store.all(con, 'work_sessions', p['id']):
                        session['project_id'] = first_project
                        self.store.put(con, 'work_sessions', session)
        result = self.build()
        validation = result['groups'][0]['validation']
        self.assertEqual(result['groups'][0]['sample_count'], 5)
        self.assertEqual(validation['status'], 'insufficient_projects')
        self.assertIsNone(validation['mae_minutes'])
        self.assertIsNone(result['validation_summary']['p80_coverage'])

    def test_holdout_earlier_rows_never_leak_and_future_training_excluded(self):
        for minutes in (40, 60, 80, 100):
            self.fixture(minutes=minutes)
        group = self.build()['groups'][0]
        samples = list(group['samples'])
        latest = next(s for s in samples if s['project_id'] == 'project_4')
        early_same_project = dict(latest, task_id='early_holdout_task', completed_at='2026-09-01T07:00:00+00:00',
                                  active_minutes=30, minutes_per_unit=15)
        result = calibration.holdout_validation(samples + [early_same_project])
        self.assertEqual(result['holdout_sample_count'], 2)
        self.assertEqual(result['training_sample_count'], 0)
        self.assertEqual(result['excluded_future_samples'], 3)
        self.assertEqual(result['status'], 'insufficient_history')
        self.assertIsNone(result['mape_percent'])
        self.assertEqual(result['predictions'], [])

    def test_holdout_p80_coverage_actual_value_can_be_covered(self):
        for minutes in (60, 80, 100, 70):
            self.fixture(minutes=minutes)
        validation = self.build()['groups'][0]['validation']
        self.assertEqual(validation['p80_coverage'], 1)
        self.assertEqual(validation['predictions'][0]['p80_predicted_minutes'], 92)
        self.assertEqual(validation['predictions'][0]['absolute_error_minutes'], 10)

    def test_archived_completed_source_counted_once_not_migration_copy(self):
        p, original = self.fixture()
        original.update(archived=True, previous_status='done', status='invalidated'); self.put('tasks', original)
        copy = dict(original, id='new_version_copy', status='done', archived=False, previous_status=None, carried_from_task_id=original['id'], revision=2)
        self.put('tasks', copy)
        result = self.build()
        self.assertEqual(result['summary']['sample_count'], 1)
        self.assertEqual(result['groups'][0]['samples'][0]['task_id'], original['id'])


if __name__ == '__main__':
    unittest.main()
