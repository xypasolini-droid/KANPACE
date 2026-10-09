"""Analytics correctness checks use a fixed clock and isolated HTTP database."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analytics
import app

AS_OF = datetime(2026, 9, 4, 15, tzinfo=timezone.utc)


def project(identifier='P', **extra):
    result = dict(id=identifier, name=identifier, revision=2, released_revision=2,
                  status='released', due_date='2026-09-03')
    result.update(extra)
    return result


def task(identifier='T', **extra):
    result = dict(id=identifier, project_id='P', revision=2, title=identifier, trade='木工',
                  status='ready', archived=False, quantity=10, completed_quantity=0,
                  progress_recorded=True, hours=10, assignee='worker', dependencies=[])
    result.update(extra)
    return result


def state(tasks, **extra):
    result = dict(projects=[project()], tasks=tasks, people=[{'id':'worker','name':'师傅','skills':['木工']}], events=[])
    result.update(extra)
    return result


def done_event(identifier, date='2026-09-03T12:00:00+00:00', **extra):
    result = dict(action='task_status', created_at=date, message=identifier+'：in_progress → done',
                  details={'task_id': identifier, 'status':'done'})
    result.update(extra)
    return result


class AnalyticsTests(unittest.TestCase):
    def test_empty_data_preserves_undefined_ratios(self):
        result = analytics.build_analytics(state([], projects=[], people=[]), as_of=AS_OF)
        self.assertEqual(result['summary']['task_total'], 0)
        self.assertIsNone(result['summary']['completion_ratio'])
        self.assertIsNone(result['progress_coverage']['ratio'])
        self.assertEqual(result['projects'], [])
        self.assertEqual(result['people'], [])
        self.assertEqual(len(result['completion_trend']['days']), 14)
        self.assertEqual(result['completion_trend']['total'], 0)
        json.dumps(result, allow_nan=False)

    def test_partial_pause_legacy_unknown_hours_and_due_risk(self):
        source = state([task('partial', status='blocked', completed_quantity=3, pause_reason='material'),
                        task('legacy', progress_recorded=False, completed_quantity=0, hours=4),
                        task('unknown', hours=None, assignee=None, dependencies=['partial'])])
        before = deepcopy(source)
        result = analytics.build_analytics(source, as_of=AS_OF)
        summary = result['summary']
        self.assertIsNone(summary['remaining_planned_hours'])
        self.assertEqual(summary['known_remaining_planned_hours'], 11)
        self.assertEqual(summary['unknown_estimate_tasks'], 1)
        self.assertEqual(summary['unrecorded_progress_tasks'], 1)
        self.assertEqual(summary['overdue_projects'], 1)
        person = next(p for p in result['people'] if p['person_id'] == 'worker')
        self.assertEqual(person['remaining_planned_hours'], 11)
        self.assertEqual(person['unrecorded_progress_tasks'], 1)
        self.assertEqual(next(p for p in result['pause_reasons'] if p['reason'] == 'material')['task_ids'], ['partial'])
        self.assertEqual(result['blockers']['unique_task_count'], 2)
        self.assertEqual(result['blockers']['dependencies'][0]['pending_task_ids'], ['partial'])
        self.assertIsNone(result['task_index']['legacy']['completed_quantity'])
        self.assertEqual(source, before)

    def test_current_scope_filters_out_drafts_old_versions_and_archives(self):
        source = state([task('current'), task('glass', trade='玻璃'), task('draft', status='draft'),
                        task('old', revision=1), task('archived', archived=True), task('review-task', project_id='review')],
                       projects=[project(), project('review', status='review')])
        result = analytics.build_analytics(source, as_of=AS_OF)
        self.assertEqual(result['summary']['project_total'], 2)
        self.assertEqual(result['summary']['production_project_total'], 1)
        self.assertEqual(result['summary']['task_total'], 2)
        filtered = analytics.build_analytics(source, trade='玻璃', as_of=AS_OF)
        self.assertEqual(filtered['summary']['project_total'], 1)
        self.assertEqual(filtered['summary']['task_total'], 1)
        self.assertEqual(filtered['trade_status'][0]['trade'], '玻璃')
        self.assertEqual(filtered['blockers']['skill_mismatch'][0]['task_id'], 'glass')
        self.assertEqual(analytics.build_analytics(source, project_id='review', as_of=AS_OF)['summary']['task_total'], 0)

    def test_trend_deduplicates_done_and_ignores_ack_progress_and_carry(self):
        tasks = [task('history', archived=True, status='invalidated', revision=1),
                 task('carried', status='done', completed_quantity=10, carried_from_task_id='history'),
                 task('today', status='done', completed_quantity=10), task('progress-only', completed_quantity=10)]
        events = [done_event('history'), done_event('history', '2026-09-04T10:00:00+00:00'),
                  done_event('today', '2026-09-04T10:00:00+00:00'),
                  done_event('progress-only', action='task_progress'), done_event('progress-only', action='device_received')]
        result = analytics.build_analytics(state(tasks, events=events), days=2, as_of=AS_OF)
        self.assertEqual(result['summary']['task_total'], 3)
        self.assertEqual(result['completion_trend']['total'], 2)
        self.assertEqual([d['completed_operations'] for d in result['completion_trend']['days']], [1,1])
        self.assertTrue(result['task_index']['history']['historical'])
        self.assertTrue(result['task_index']['history']['archived'])
        self.assertEqual(result['task_index']['history']['title'], 'history')
        self.assertFalse(result['task_index']['today']['historical'])
        self.assertNotIn('carried', sum([d['task_ids'] for d in result['completion_trend']['days']], []))
        legacy = done_event('history', details={'task_id':'history'})
        self.assertEqual(analytics.build_analytics(state(tasks, events=[legacy]), as_of=AS_OF)['completion_trend']['total'], 1)
        unknown_date = done_event('today', None)
        incomplete = analytics.build_analytics(state(tasks, events=[unknown_date]), as_of=AS_OF)
        self.assertEqual(incomplete['completion_trend']['unknown_date_events'], 1)
        self.assertEqual(incomplete['completion_trend']['total'], 0)

    def test_missing_due_and_finished_past_due_are_not_false_overdue(self):
        source = state([task('finished', status='done', completed_quantity=10), task('unknown', project_id='unknown')],
                       projects=[project(), project('unknown', due_date='')])
        result = analytics.build_analytics(source, as_of=AS_OF)
        self.assertEqual(result['summary']['overdue_projects'], 0)
        unknown = next(p for p in result['projects'] if p['id']=='unknown')
        self.assertIsNone(unknown['due_date'])
        self.assertIsNone(unknown['days_to_due'])
        self.assertEqual(unknown['risk'], 'unknown_due')

    def test_http_validation_read_only_and_published_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = app.Store(directory, seed=False)
            with store.connect() as con:
                store.put(con, 'projects', project())
                store.put(con, 'tasks', task())
                store.event(con, 'P', 'source_note', '既有记录')
            server = app.Server(('127.0.0.1', 0), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                for query, expected in [('?days=2&trade='+urllib.parse.quote('木工'), 200), ('?days=0',400), ('?days=1.5',400),
                                        ('?days=9999',400), ('?trade=invalid',400), ('?project_id=missing',404)]:
                    try:
                        response = urllib.request.urlopen(base+'/api/analytics'+query)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        self.assertEqual(response.status, expected)
                        result = json.load(response)
                        if expected == 200:
                            self.assertEqual(result['summary']['task_total'], 1)
                            self.assertEqual(len(result['completion_trend']['days']), 2)
                with store.connect() as con:
                    self.assertEqual(len(store.all(con, 'events')), 1)
                    self.assertEqual(store.get(con, 'tasks', 'T')['status'], 'ready')
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
