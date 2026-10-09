"""Independent business QA; all servers, files and SQLite databases are temporary."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

import test_api


class KanpaceBusinessQATests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    prepared = test_api.APITests.prepared
    execution_prepared = test_api.APITests.execution_prepared
    task_action = test_api.APITests.task_action

    def test_closed_history_does_not_permanently_lock_worker_skills(self):
        project, _, tasks = self.execution_prepared()
        wood = next(t for t in tasks if t['trade'] == '木工')
        person_id = wood['assignee']
        for status in ('completed', 'shipped'):
            with self.subTest(status=status):
                self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment',
                    {'status': status, 'confirm_unfinished': True})[0], 200)
                before = self.state()
                code, body = self.request('/api/people/' + person_id, {'skills': ['装配']})
                self.assertEqual(code, 200, body)
                self.assertEqual(body['person']['skills'], ['装配'])
                self.assertEqual(self.state()['tasks'], before['tasks'])
                self.assertEqual(self.request('/api/people/' + person_id, {'skills': ['木工']})[0], 200)

    def test_reopen_cannot_restore_running_work_to_unqualified_worker(self):
        project, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment',
            {'status': 'shipped', 'confirm_unfinished': True})[0], 200)
        # Simulate the legitimate personnel change after closing a project.
        # Direct fixture setup separates the reopen guard from the skill-edit bug.
        with self.store.connect() as con:
            worker = self.store.get(con, 'people', task['assignee'])
            worker['skills'] = ['装配']
            self.store.put(con, 'people', worker)
        before = self.state()
        code, body = self.request('/api/projects/' + project['id'] + '/fulfillment', {'status': 'active'})
        self.assertEqual(code, 409, body)
        after = self.state()
        for collection in ('projects', 'tasks', 'events'):
            self.assertEqual(after[collection], before[collection])

    def test_active_skill_change_requires_reassignment_without_erasing_closed_history(self):
        closed, _, old_tasks = self.execution_prepared()
        worker = next(t for t in old_tasks if not t['dependencies'])['assignee']
        self.assertEqual(self.request('/api/projects/' + closed['id'] + '/fulfillment',
            {'status': 'shipped', 'confirm_unfinished': True})[0], 200)
        _, _, current_tasks = self.execution_prepared()
        current = next(t for t in current_tasks if not t['dependencies'])
        self.assertEqual(current['assignee'], worker)
        before = self.state()
        code, body = self.request('/api/people/' + worker, {'skills': ['装配']})
        self.assertEqual(code, 200, body)
        after = self.state()
        released = next(t for t in after['tasks'] if t['id'] == current['id'])
        self.assertIsNone(released['assignee'])
        self.assertEqual(released['execution_version'], current['execution_version'] + 1)
        self.assertEqual(released['status'], current['status'])
        old = next(t for t in after['tasks'] if t['id'] == old_tasks[0]['id'])
        previous = next(t for t in before['tasks'] if t['id'] == old_tasks[0]['id'])
        self.assertEqual(old, previous)

    def test_concurrent_start_cannot_double_book_one_worker(self):
        _, _, first = self.execution_prepared()
        _, _, second = self.execution_prepared()
        a, b = [next(t for t in tasks if not t['dependencies']) for tasks in (first, second)]
        self.assertEqual(a['assignee'], b['assignee'])
        gate = threading.Barrier(2)

        def start(task):
            gate.wait(timeout=3)
            return self.task_action(task, 'status', {'status': 'in_progress',
                'expected_execution_version': task['execution_version']})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(start, (a, b)))
        self.assertEqual(sorted(code for code, _ in results), [200, 409], results)
        running = [t for t in self.state()['tasks'] if t['status'] == 'in_progress']
        self.assertEqual(len(running), 1)

    def test_repeated_resume_does_not_duplicate_work_or_events(self):
        _, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        code, body = self.task_action(task, 'pause', {'reason': 'material',
            'note': '缺板材', 'handover_note': '一件完成，一件留在 A 架', 'completed_quantity': 1})
        self.assertEqual(code, 200, body)
        payload = {'note': '板材到位并验收', 'expected_execution_version': body['task']['execution_version']}
        code, resumed = self.task_action(task, 'resume', payload)
        self.assertEqual(code, 200, resumed)
        before = self.state()
        code, duplicate = self.task_action(task, 'resume', payload)
        self.assertEqual(code, 409, duplicate)
        self.assertEqual(self.state(), before)
        self.assertEqual(resumed['task']['completed_quantity'], 1)
        self.assertEqual(resumed['task']['remaining_quantity'], 1)

    def reopen_payload(self, project):
        before = self.state()
        code, conflict = self.request('/api/projects/' + project['id'] + '/fulfillment', {'status': 'active'})
        self.assertEqual(code, 409, conflict)
        self.assertEqual(conflict['details']['code'], 'reopen_conflicts')
        self.assertEqual(self.state(), before, 'declining or cancelling the conflict prompt leaves everything unchanged')
        return {'status': 'active', 'confirm_reopen_pause': True,
                'reopen_task_versions': {t['id']: t['execution_version'] for t in conflict['details']['reopening_tasks']}}

    def closed_running(self):
        project, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.task_action(task, 'progress', {'completed_quantity': 1, 'note': '一件完成；半成品留在 A 架'})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment',
            {'status': 'shipped', 'confirm_unfinished': True})[0], 200)
        return project, task

    def test_confirmed_reopen_pauses_only_conflicts_and_has_real_reassignment_path(self):
        project, task = self.closed_running()
        worker = task['assignee']
        self.assertEqual(self.request('/api/people/' + worker, {'skills': ['装配']})[0], 200)
        payload = self.reopen_payload(project)
        before = self.state()
        old = next(t for t in before['tasks'] if t['id'] == task['id'])
        code, body = self.request('/api/projects/' + project['id'] + '/fulfillment', payload)
        self.assertEqual(code, 200, body)
        self.assertEqual(body['paused_task_ids'], [task['id']])
        after = self.state()
        paused = next(t for t in after['tasks'] if t['id'] == task['id'])
        self.assertEqual((paused['status'], paused['pause_reason']), ('blocked', 'other'))
        for key in ('assignee', 'completed_quantity', 'remaining_quantity', 'quantity', 'handover_note', 'started_at', 'revision'):
            self.assertEqual(paused.get(key), old.get(key), key)
        self.assertEqual(paused['execution_version'], old['execution_version'] + 1)
        self.assertEqual([t for t in before['tasks'] if t['id'] != task['id']],
                         [t for t in after['tasks'] if t['id'] != task['id']])
        added = after['events'][len(before['events']):]
        self.assertEqual([e['action'] for e in added], ['task_paused', 'project_fulfillment_changed'])
        self.assertTrue(added[0]['details']['reopened_project'])
        self.assertEqual(added[0]['details']['previous_status'], 'in_progress')
        self.assertEqual(added[1]['details']['paused_task_ids'], [task['id']])
        self.assertFalse(added[1]['details']['tasks_preserved'])
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', payload)[1]['unchanged'], True)
        self.assertEqual(self.state(), after)
        person = self.request('/api/people', {'name': '接班木工', 'skills': ['木工']})[1]['person']
        self.assertEqual(self.task_action(paused, 'assign', {'person_id': person['id']})[0], 200)
        code, resumed = self.task_action(paused, 'resume', {'note': '接班复核夹具及剩余板件完成'})
        self.assertEqual(code, 200, resumed)
        self.assertEqual(resumed['task']['assignee'], person['id'])
        self.assertEqual(resumed['task']['completed_quantity'], 1)
        self.assertEqual(next(p for p in self.state()['people'] if p['id'] == worker)['skills'], ['装配'])

    def test_confirmed_busy_worker_reopen_keeps_current_order_running(self):
        project, old = self.closed_running()
        _, _, tasks = self.execution_prepared()
        current = next(t for t in tasks if not t['dependencies'])
        self.assertEqual(current['assignee'], old['assignee'])
        self.assertEqual(self.task_action(current, 'status', {'status': 'in_progress'})[0], 200)
        payload = self.reopen_payload(project)
        before = self.state()
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', payload)[0], 200)
        after = self.state()
        self.assertEqual(next(t for t in after['tasks'] if t['id'] == current['id']),
                         next(t for t in before['tasks'] if t['id'] == current['id']))
        self.assertEqual(next(t for t in after['tasks'] if t['id'] == old['id'])['status'], 'blocked')
        self.assertEqual(self.task_action(old, 'resume', {'note': '当前急单还未完成'})[0], 409)

    def test_missing_assignee_can_be_reopened_paused_then_assigned(self):
        for missing in (None, 'person_no_longer_exists'):
            with self.subTest(assignee=missing):
                project, old = self.closed_running()
                original_worker = old['assignee']
                with self.store.connect() as con:
                    task = self.store.get(con, 'tasks', old['id'])
                    task['assignee'] = missing
                    self.store.put(con, 'tasks', task)
                payload = self.reopen_payload(project)
                self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', payload)[0], 200)
                self.assertEqual(self.task_action(old, 'assign', {'person_id': original_worker})[0], 200)
                self.assertEqual(self.task_action(old, 'resume', {'note': '确认负责人接班'})[0], 200)
                self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment',
                    {'status': 'completed', 'confirm_unfinished': True})[0], 200)

    def test_reopen_confirmation_is_strict_and_stale_review_does_not_mutate(self):
        project, old = self.closed_running()
        self.assertEqual(self.request('/api/people/' + old['assignee'], {'skills': ['装配']})[0], 200)
        payload = self.reopen_payload(project)
        before = self.state()
        invalid = [dict(payload, confirm_reopen_pause=value) for value in ('true', 1, None, [])]
        invalid += [dict(payload, reopen_task_versions=value) for value in (None, [], {'t': True}, {'t': -1}, {'t': '2'})]
        invalid += [dict(payload, status='completed')]
        for body in invalid:
            code, result = self.request('/api/projects/' + project['id'] + '/fulfillment', body)
            self.assertEqual(code, 400, result)
            self.assertEqual(self.state(), before)
        for versions in ({}, {old['id']: payload['reopen_task_versions'][old['id']] - 1}, {'wrong-task': 1}):
            code, result = self.request('/api/projects/' + project['id'] + '/fulfillment', dict(payload, reopen_task_versions=versions))
            self.assertEqual(code, 409, result)
            self.assertEqual(result['details']['reopening_tasks'][0]['id'], old['id'])
            self.assertEqual(self.state(), before)

    def test_concurrent_confirmed_reopen_pauses_and_records_only_once(self):
        project, old = self.closed_running()
        self.assertEqual(self.request('/api/people/' + old['assignee'], {'skills': ['装配']})[0], 200)
        payload = self.reopen_payload(project)
        before = self.state()
        gate = threading.Barrier(2)

        def reopen(_):
            gate.wait(timeout=3)
            return self.request('/api/projects/' + project['id'] + '/fulfillment', payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reopen, (0, 1)))
        self.assertEqual([code for code, _ in results], [200, 200], results)
        self.assertEqual(sorted(body['unchanged'] for _, body in results), [False, True])
        after = self.state()
        self.assertEqual(len(after['events']) - len(before['events']), 2)
        saved = next(t for t in after['tasks'] if t['id'] == old['id'])
        self.assertEqual(saved['execution_version'], payload['reopen_task_versions'][old['id']] + 1)

    def multi_trade_closed(self):
        project, imported = self.imported(content=b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\nGlass,Tempered,glass,1000,500,10,2,mm,clear\n')
        for part in imported['parts']:
            self.assertEqual(self.request('/api/parts/' + part['id'] + '/review', {'approved': True})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/auto-assign', {})[0], 200)
        roots = [t for t in self.state()['tasks'] if t['project_id'] == project['id'] and not t['dependencies']]
        self.assertEqual({t['trade'] for t in roots}, {'木工', '玻璃'})
        for task in roots:
            self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment',
            {'status': 'shipped', 'confirm_unfinished': True})[0], 200)
        wood = next(t for t in roots if t['trade'] == '木工')
        glass = next(t for t in roots if t['trade'] == '玻璃')
        self.assertEqual(self.request('/api/people/' + wood['assignee'], {'skills': ['装配']})[0], 200)
        return project, wood, glass

    def test_confirmed_reopen_preserves_eligible_running_trade(self):
        project, wood, glass = self.multi_trade_closed()
        payload = self.reopen_payload(project)
        self.assertEqual(set(payload['reopen_task_versions']), {wood['id']})
        before = self.state()
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', payload)[0], 200)
        after = self.state()
        self.assertEqual(next(t for t in after['tasks'] if t['id'] == glass['id']),
                         next(t for t in before['tasks'] if t['id'] == glass['id']))

    def test_changed_conflict_set_requires_new_confirmation(self):
        project, wood, glass = self.multi_trade_closed()
        payload = self.reopen_payload(project)
        # A second person changes qualification while the confirmation dialog is open.
        self.assertEqual(self.request('/api/people/' + glass['assignee'], {'skills': ['装配']})[0], 200)
        before = self.state()
        code, changed = self.request('/api/projects/' + project['id'] + '/fulfillment', payload)
        self.assertEqual(code, 409, changed)
        self.assertEqual({t['id'] for t in changed['details']['reopening_tasks']}, {wood['id'], glass['id']})
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
