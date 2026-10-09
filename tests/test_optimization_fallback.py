"""Heuristic fallback certificates against real prepared Store constraints."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimization_engines as engines
import production
import test_scheduling as fixtures


class FallbackValidationTests(unittest.TestCase):
    setUp = fixtures.SchedulingTests.setUp
    tearDown = fixtures.SchedulingTests.tearDown
    worker = fixtures.SchedulingTests.worker
    project_create = fixtures.SchedulingTests.project_create
    center = fixtures.SchedulingTests.center
    task = fixtures.SchedulingTests.task
    put = fixtures.SchedulingTests.put
    all = fixtures.SchedulingTests.all

    def prepare(self):
        with self.store.connect() as con:
            return engines.prepare_schedule(self.store, con, {'start_date': '2026-09-07', 'horizon_days': 7,
                'time_limit_seconds': 1, 'allow_fallback': True})

    def test_valid_fallback_passes_current_certificate_without_native_solver(self):
        a = self.task(30)
        self.task(45, deps=[a])
        prepared = self.prepare()
        before = deepcopy(self.all('tasks'))
        with patch.object(engines, '_worker', side_effect=OSError('fixture missing solver')):
            result = engines.solve_prepared(prepared)
        self.assertEqual(result['engine']['used'], 'KANPACE heuristic')
        self.assertEqual(result['engine']['status'], 'UNAVAILABLE')
        self.assertTrue(result['validation']['valid'])
        self.assertEqual(result['validation']['checked_tasks'], 2)
        self.assertEqual(before, self.all('tasks'))
        self.assertFalse(self.all('plans'))

    def test_invalid_old_fallback_is_rejected_rather_than_claimed_valid(self):
        self.task(30)
        prepared = self.prepare()
        prepared['baseline']['rows'][0]['minute_segments'][0]['start_minute'] = -10
        with patch.object(engines, '_worker', side_effect=OSError('fixture missing solver')):
            with self.assertRaises(production.ProductionError) as caught:
                engines.solve_prepared(prepared)
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(self.all('plans'))

    def test_malformed_optimal_certificate_does_not_keep_optimal_fallback_label(self):
        self.task(30)
        prepared = self.prepare()
        bad = {'status': 'OPTIMAL', 'version': 'synthetic', 'objective_value': 123,
               'best_objective_bound': 123, 'rows': [{'task_id': prepared['payload']['jobs'][0]['id'],
               'segments': [[480, 510]]}], 'unplaced': []}
        with patch.object(engines, '_worker', return_value=bad):
            result = engines.solve_prepared(prepared)
        self.assertTrue(result['validation']['valid'])
        self.assertEqual(result['engine']['status'], 'FALLBACK_VALIDATED')
        self.assertEqual(result['engine']['solver_status'], 'OPTIMAL')
        self.assertNotIn('objective_value', result['engine'])
        self.assertNotIn('best_objective_bound', result['engine'])

    def test_missing_rows_or_start_returns_validation_failure(self):
        payload = {'jobs': [{'id': 'a', 'duration': 10, 'release': 0, 'windows': [[0, 30]],
                            'resources': ['person'], 'dependencies': [], 'wait_minutes': 0}]}
        for output in (None, {}, {'rows': [None]}, {'rows': [{'task_id': 'a', 'segments': [[0, 10]]}]}):
            self.assertFalse(engines.validate_schedule(payload, output)['valid'])


if __name__ == '__main__':
    unittest.main()
