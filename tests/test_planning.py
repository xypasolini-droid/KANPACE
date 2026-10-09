"""Production planning HTTP tests use temporary SQLite databases and no hardware."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

import test_api


class PlanningTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    prepared = test_api.APITests.prepared
    execution_prepared = test_api.APITests.execution_prepared
    task_action = test_api.APITests.task_action

    def grid(self, query=''):
        code, body = self.request('/api/planning?start=2026-09-07&end=2026-09-13' + query)
        self.assertEqual(code, 200, body)
        return body

    def fixture(self, person=None):
        project, _, tasks = self.execution_prepared()
        if not person:
            person = self.request('/api/people', {'name': '真实木工', 'skills': ['木工'], 'capacity_minutes': 480})[1]['person']
        for task in tasks:
            if task['trade'] == '木工':
                self.assertEqual(self.task_action(task, 'assign', {'person_id': person['id']})[0], 200)
        tasks = [t for t in self.state()['tasks'] if t['project_id'] == project['id']]
        return project, next(t for t in tasks if not t['dependencies']), person, tasks

    def payload(self, task, **extra):
        current = next(t for t in self.state()['tasks'] if t['id'] == task['id'])
        return {'task_id': task['id'], 'start_date': '2026-09-07', 'end_date': '2026-09-07',
                'planned_minutes': 120, 'minutes_source': 'manual', 'material_status': 'ready', 'note': '车间核对',
                'expected_task_version': current['execution_version'], **extra}

    def save(self, task, **extra):
        code, body = self.request('/api/planning', self.payload(task, **extra))
        self.assertEqual(code, 200, body)
        return body['plan']

    def update(self, task, plan, **extra):
        return self.save(task, id=plan['id'], expected_version=plan['version'], **extra)

    def test_default_empty_calendar_no_fake_dates_and_real_people_required(self):
        with self.store.connect() as con:
            for person in self.store.all(con, 'people'):
                person['demo'] = True
                self.store.put(con, 'people', person)
        project, _, tasks = self.execution_prepared()
        task = next(t for t in tasks if not t['dependencies'])
        grid = self.grid()
        self.assertEqual(grid['plans'], [])
        self.assertEqual(grid['people'], [])
        self.assertEqual(grid['calendar'], {'version': 0, 'weekdays': [1, 2, 3, 4, 5], 'daily_capacity_source': 'people'})
        self.assertEqual(grid['workdays'], ['2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11'])
        row = next(t for t in grid['unscheduled_tasks'] if t['id'] == task['id'])
        self.assertIn('请先分派负责人', ''.join(row['schedule_blockers']))
        self.assertEqual(row['person_name'], '')
        self.assertFalse(row['assignee_is_demo'])
        self.assertIsNone(task['assignee'])
        self.assertEqual(row['remaining_minutes'], row['estimated_remaining_minutes'])
        before = self.state()
        code, result = self.request('/api/planning', self.payload(task))
        self.assertEqual(code, 409, result)
        self.assertEqual(result['details']['code'], 'assignee_not_ready')
        self.assertEqual(self.state(), before)

    def test_cross_day_save_reserves_workdays_without_changing_task_or_assignment(self):
        project, task, person, _ = self.fixture()
        before = self.state()
        plan = self.save(task, start_date='2026-09-11', end_date='2026-09-14', planned_minutes=481)
        self.assertEqual(plan['allocations'], [{'date': '2026-09-11', 'minutes': 240.5}, {'date': '2026-09-14', 'minutes': 240.5}])
        self.assertEqual(plan['person_id'], person['id'])
        self.assertEqual(plan['version'], 1)
        self.assertEqual(plan['minutes_source'], 'manual')
        for collection in ('tasks', 'projects', 'people'):
            self.assertEqual(self.state()[collection], before[collection])
        grid = self.grid()
        self.assertEqual(len(grid['plans']), 1)
        self.assertNotIn(task['id'], {t['id'] for t in grid['unscheduled_tasks']})
        day = next(row for row in grid['capacity'] if row['person_id'] == person['id'] and row['date'] == '2026-09-11')
        self.assertEqual((day['planned_minutes'], day['remaining_minutes']), (240.5, 239.5))
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'plans', plan['id'])['planned_minutes'], 481)

    def test_capacity_is_global_across_project_filters_and_rejection_is_atomic(self):
        project, a, person, _ = self.fixture()
        _, b, _, _ = self.fixture(person)
        self.save(a, planned_minutes=350)
        before = self.state()
        code, error = self.request('/api/planning', self.payload(b, planned_minutes=200))
        self.assertEqual(code, 409, error)
        self.assertEqual(error['details']['code'], 'capacity_conflict')
        self.assertEqual(error['details']['conflicts'][0]['used_minutes'], 350)
        self.assertEqual(self.state(), before)
        grid = self.grid('&project_id=' + project['id'])
        self.assertEqual(next(c for c in grid['capacity'] if c['person_id'] == person['id'] and c['date'] == '2026-09-07')['planned_minutes'], 350)

    def test_concurrent_capacity_reservations_cannot_overbook(self):
        _, a, person, _ = self.fixture()
        _, b, _, _ = self.fixture(person)
        payloads = [self.payload(t, planned_minutes=350) for t in (a, b)]
        gate = threading.Barrier(2)
        def reserve(payload):
            gate.wait(timeout=3)
            return self.request('/api/planning', payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, payloads))
        self.assertEqual(sorted(code for code, _ in results), [200, 409], results)
        self.assertEqual(len(self.grid()['plans']), 1)

    def test_pending_material_blocks_start_until_ready_without_fake_progress(self):
        _, task, _, _ = self.fixture()
        plan = self.save(task, material_status='pending', note='封边条待到货确认')
        self.assertFalse(plan['can_start'])
        before = self.state()['tasks']
        code, error = self.task_action(task, 'status', {'status': 'in_progress'})
        self.assertEqual(code, 409, error)
        self.assertIn('物料待确认', ''.join(error['details']))
        self.assertEqual(self.state()['tasks'], before)
        ready = self.update(task, plan, material_status='ready', note='封边条入库确认')
        self.assertTrue(ready['can_start'])
        self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        latest = self.update(task, ready, material_status='shortage', note='后续批次板材欠料')
        self.assertEqual(latest['task']['status'], 'in_progress')
        self.assertEqual(self.task_action(task, 'progress', {'completed_quantity': 1, 'note': '现有物料加工一件'})[0], 200)
        self.assertEqual(self.task_action(task, 'status', {'status': 'done'})[0], 200)
        self.assertEqual(self.grid()['plans'], [])

    def test_unknown_estimate_requires_manual_positive_minutes(self):
        _, task, _, _ = self.fixture()
        with self.store.connect() as con:
            saved = self.store.get(con, 'tasks', task['id'])
            saved['hours'] = None
            self.store.put(con, 'tasks', saved)
        row = next(t for t in self.grid()['unscheduled_tasks'] if t['id'] == task['id'])
        self.assertIsNone(row['remaining_minutes'])
        self.assertEqual(self.request('/api/planning', self.payload(task, minutes_source='task_estimate'))[0], 400)
        for bad in (0, -1, True, None, '60'):
            self.assertEqual(self.request('/api/planning', self.payload(task, planned_minutes=bad))[0], 400)
        manual = self.save(task, planned_minutes=180)
        self.assertEqual((manual['planned_minutes'], manual['minutes_source']), (180, 'manual'))

    def test_estimate_uses_remaining_quantity_and_preserves_source(self):
        _, task, _, _ = self.fixture()
        self.task_action(task, 'status', {'status': 'in_progress'})
        self.task_action(task, 'progress', {'completed_quantity': 1, 'note': '两件中完成一件'})
        plan = self.save(task, minutes_source='task_estimate', planned_minutes=999)
        self.assertEqual(plan['planned_minutes'], round(task['hours'] * 60 / 2, 2))
        self.assertEqual(plan['minutes_source'], 'task_estimate')

    def test_dependency_sequence_reverse_edit_and_cancel_guards(self):
        _, first, _, tasks = self.fixture()
        later = next(t for t in tasks if first['id'] in t['dependencies'] and t['trade'] == '木工')
        self.assertEqual(self.request('/api/planning', self.payload(later))[0], 409)
        preceding = self.save(first)
        self.assertEqual(self.request('/api/planning', self.payload(later))[0], 409)
        succeeding = self.save(later, start_date='2026-09-08', end_date='2026-09-08')
        self.assertFalse(succeeding['can_start'])
        before = self.state()
        code, error = self.request('/api/planning', self.payload(first, id=preceding['id'], expected_version=preceding['version'], end_date='2026-09-08'))
        self.assertEqual(code, 409, error)
        self.assertEqual(error['details']['code'], 'dependency_conflict')
        self.assertEqual(self.request('/api/planning/' + preceding['id'] + '/cancel', {'expected_version': 1})[0], 409)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.request('/api/planning/' + succeeding['id'] + '/cancel', {'expected_version': 1, 'note': '后序重排'})[0], 200)
        self.assertEqual(self.request('/api/planning/' + preceding['id'] + '/cancel', {'expected_version': 1, 'note': '前序重排'})[0], 200)
        self.assertEqual(self.grid()['plans'], [])

    def test_closed_invalidated_and_done_tasks_cannot_be_scheduled(self):
        project, task, _, _ = self.fixture()
        plan = self.save(task)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', {'status': 'shipped', 'confirm_unfinished': True})[0], 200)
        before = self.state()
        self.assertEqual(self.grid()['plans'], [])
        self.assertEqual(self.grid()['unscheduled_tasks'], [])
        self.assertEqual(self.request('/api/planning', self.payload(task, id=plan['id'], expected_version=1))[0], 409)
        self.assertEqual(self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 1})[0], 409)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', {'status': 'active'})[0], 200)
        self.task_action(task, 'status', {'status': 'in_progress'})
        self.task_action(task, 'status', {'status': 'done'})
        self.assertEqual(self.request('/api/planning', self.payload(task))[0], 409)

    def test_optimistic_versions_duplicate_creation_and_cancel_are_safe(self):
        _, task, _, _ = self.fixture()
        plan = self.save(task)
        before = self.state()
        self.assertEqual(self.request('/api/planning', self.payload(task))[0], 409)
        self.assertEqual(self.request('/api/planning', self.payload(task, id=plan['id'], expected_version=0))[0], 409)
        self.assertEqual(self.state(), before)
        updated = self.update(task, plan, planned_minutes=130)
        self.assertEqual(updated['version'], 2)
        self.assertEqual(self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 1})[0], 409)
        code, cancelled = self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 2, 'note': '客户改期'})
        self.assertEqual(code, 200, cancelled)
        before = self.state()
        code, repeated = self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 3})
        self.assertEqual(code, 200, repeated)
        self.assertTrue(repeated['unchanged'])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.save(task)['version'], 1)

    def test_assignee_change_makes_reservation_stale_until_explicit_save(self):
        _, task, _, _ = self.fixture()
        plan = self.save(task)
        other = self.request('/api/people', {'name': '新木工', 'skills': ['木工'], 'capacity_minutes': 480})[1]['person']
        self.task_action(task, 'assign', {'person_id': other['id']})
        grid = self.grid()
        self.assertFalse(grid['plans'][0]['valid'])
        self.assertEqual(next(t for t in grid['unscheduled_tasks'] if t['id'] == task['id'])['existing_plan_id'], plan['id'])
        self.assertTrue(all(row['planned_minutes'] == 0 for row in grid['capacity']))
        self.assertEqual(self.request('/api/planning', dict(self.payload(task), id=plan['id'], expected_version=1, expected_task_version=plan['task_execution_version']))[0], 409)
        self.assertEqual(self.update(task, plan)['person_id'], other['id'])

    def test_workweek_configuration_requires_no_live_plans(self):
        _, task, _, _ = self.fixture()
        code, result = self.request('/api/planning/calendar', {'weekdays': [1, 2, 3, 4, 5, 6], 'expected_version': 0})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['calendar']['version'], 1)
        plan = self.save(task, start_date='2026-09-12', end_date='2026-09-12')
        self.assertEqual(self.request('/api/planning/calendar', {'weekdays': [1, 2, 3, 4, 5], 'expected_version': 1})[0], 409)
        self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 1, 'note': '调整工作周'})
        self.assertEqual(self.request('/api/planning/calendar', {'weekdays': [1, 2, 3, 4, 5], 'expected_version': 1})[0], 200)
        for value in ([], [True], [0], [8], [1, 1], 'weekdays'):
            self.assertEqual(self.request('/api/planning/calendar', {'weekdays': value, 'expected_version': 2})[0], 400)

    def test_factory_type_validation_default_and_non_cabinet_generate_guard(self):
        self.assertEqual(self.project()['factory_type'], 'cabinet')
        for factory_type in ('machinery', 'site'):
            code, body = self.request('/api/projects', {'name': '其他行业建档', 'factory_type': factory_type})
            self.assertEqual(code, 200, body)
            project = body['project']
            self.assertEqual(project['factory_type'], factory_type)
            before = self.state()
            code, result = self.request('/api/projects/' + project['id'] + '/generate', {})
            self.assertEqual(code, 422, result)
            self.assertEqual(result['error'], '请使用本厂行业流程配置工作包，再生成工种任务')
            self.assertEqual(result['details']['code'], 'industry_workflow_required')
            self.assertEqual(result['details']['page'], 'templates')
            self.assertEqual(result['details']['project_id'], project['id'])
            self.assertEqual(self.state(), before)
        for bad in ('', 'unknown', None, [], True):
            self.assertEqual(self.request('/api/projects', {'name': '无效行业', 'factory_type': bad})[0], 400)

    def test_date_material_and_unreleased_validation(self):
        project, task, _, _ = self.fixture()
        for values in ({'start_date': '2026-09-06'}, {'end_date': '2026-09-05'}, {'start_date': '2026-9-7'},
                       {'end_date': '2027-09-07'}, {'material_status': 'maybe'}, {'material_status': 'shortage', 'note': ''},
                       {'expected_task_version': True}, {'person_id': task['assignee']}):
            self.assertEqual(self.request('/api/planning', self.payload(task, **values))[0], 400, values)
        self.assertEqual(self.request('/api/planning?start=2026-09-07&end=2026-10-50')[0], 400)
        self.assertEqual(self.request('/api/planning')[0], 400)
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', project['id'])
            project['status'] = 'review'
            self.store.put(con, 'projects', project)
        self.assertEqual(self.grid()['unscheduled_tasks'], [])
        self.assertEqual(self.request('/api/planning', self.payload(task))[0], 409)

    def test_off_window_stale_plan_is_readable_and_requires_change_reasons(self):
        _, task, _, _ = self.fixture()
        plan = self.save(task, start_date='2026-09-21', end_date='2026-09-21')
        other = self.request('/api/people', {'name': '换班木工', 'skills': ['木工'], 'capacity_minutes': 480})[1]['person']
        self.task_action(task, 'assign', {'person_id': other['id']})
        grid = self.grid()
        self.assertEqual(grid['plans'], [])
        self.assertEqual(next(t for t in grid['unscheduled_tasks'] if t['id'] == task['id'])['existing_plan_id'], plan['id'])
        code, result = self.request('/api/planning/' + plan['id'])
        self.assertEqual(code, 200, result)
        self.assertEqual(result['plan']['id'], plan['id'])
        self.assertFalse(result['plan']['valid'])
        self.assertEqual(self.request('/api/planning', self.payload(task, id=plan['id'], expected_version=1, note=''))[0], 400)
        self.assertEqual(self.request('/api/planning/' + plan['id'] + '/cancel', {'expected_version': 1})[0], 400)
        self.assertEqual(self.update(task, result['plan'], note='换班后重新核对工时')['person_id'], other['id'])

    def test_unknown_capacity_stays_unknown_and_cannot_accept_reservations(self):
        _, task, person, _ = self.fixture()
        with self.store.connect() as con:
            saved = self.store.get(con, 'people', person['id'])
            saved['capacity_minutes'] = None
            self.store.put(con, 'people', saved)
        grid = self.grid()
        relevant = [row for row in grid['capacity'] if row['person_id'] == person['id']]
        self.assertTrue(relevant)
        self.assertTrue(all(row['capacity_unknown'] for row in relevant))
        self.assertTrue(all(row['remaining_minutes'] is None for row in relevant))
        self.assertEqual(self.request('/api/planning', self.payload(task))[0], 409)

    def test_new_material_pause_expires_old_ready_and_requires_fresh_confirmation(self):
        _, task, _, _ = self.fixture()
        plan = self.save(task, material_status='ready', note='首次齐套核对')
        self.assertEqual(plan['effective_material_status'], 'ready')
        self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
        self.assertEqual(self.task_action(task, 'pause', {'reason': 'material', 'note': '实际缺一条封边条',
            'handover_note': '一件完成，另一件放 A 架', 'completed_quantity': 1})[0], 200)
        before = self.state()
        grid = self.grid()
        self.assertEqual(grid['summary']['material_risks'], 1)
        visible = next(p for p in grid['plans'] if p['id'] == plan['id'])
        self.assertEqual((visible['material_status'], visible['recorded_material_status'], visible['effective_material_status']),
                         ('ready', 'ready', 'shortage'))
        self.assertTrue(visible['material_confirmation_expired'])
        self.assertIn('原齐套确认已过期', '；'.join(visible['warnings']))
        self.assertFalse(visible['can_start'])
        with self.store.connect() as con:
            self.assertEqual(self.store.get(con, 'plans', plan['id'])['material_status'], 'ready')
        for action, body in [('resume', {'note': '仍使用原计划确认'}),
                             ('status', {'status': 'in_progress', 'note': '仍使用原计划确认'}),
                             ('status', {'status': 'ready', 'note': '仅恢复到队列也须齐套'})]:
            code, error = self.task_action(task, action, body)
            self.assertEqual(code, 409, error)
            self.assertIn('重新确认齐套', '；'.join(error['details']))
        self.assertEqual(self.state(), before)
        confirmed = self.update(task, plan, material_status='ready', note='补料到位，现场核对齐套')
        self.assertEqual(confirmed['task_execution_version'], confirmed['task']['execution_version'])
        self.assertEqual(confirmed['effective_material_status'], 'ready')
        self.assertFalse(confirmed['material_confirmation_expired'])
        self.assertEqual(self.grid()['summary']['material_risks'], 0)
        self.assertEqual(confirmed['task']['status'], 'blocked', 'material confirmation does not resume work automatically')
        self.assertEqual(self.task_action(task, 'resume', {'note': ''})[0], 400)
        code, resumed = self.task_action(task, 'resume', {'note': '已核对新增封边条并重新接班'})
        self.assertEqual(code, 200, resumed)
        self.assertEqual(resumed['task']['completed_quantity'], 1)
        self.assertEqual(self.request('/api/planning/' + plan['id'])[1]['plan']['effective_material_status'], 'ready')

    def test_nonmaterial_pause_does_not_invent_material_shortage(self):
        for reason in ('quality', 'urgent'):
            with self.subTest(reason=reason):
                _, task, _, _ = self.fixture()
                plan = self.save(task, material_status='ready')
                self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
                self.assertEqual(self.task_action(task, 'pause', {'reason': reason, 'note': '等处理后继续',
                    'handover_note': '夹具及板件已留存'})[0], 200)
                visible = self.request('/api/planning/' + plan['id'])[1]['plan']
                self.assertEqual(visible['effective_material_status'], 'ready')
                self.assertFalse(visible['material_confirmation_expired'])
                self.assertNotIn('原齐套确认已过期', '；'.join(visible['warnings']))
                self.assertEqual(self.task_action(task, 'resume', {'note': '对应问题已处理'})[0], 200)

    def test_pending_and_shortage_cannot_bypass_gate_by_returning_to_ready(self):
        for material in ('pending', 'shortage'):
            with self.subTest(material=material):
                _, task, _, _ = self.fixture()
                plan = self.save(task, material_status=material, note='等待核对补料')
                self.assertEqual(self.task_action(task, 'pause', {'reason': 'other', 'note': '等待安排',
                    'handover_note': '工件未开工'})[0], 200)
                before = self.state()
                self.assertEqual(self.task_action(task, 'resume', {'note': '申请恢复'})[0], 409)
                self.assertEqual(self.task_action(task, 'status', {'status': 'ready', 'note': '先回队列'})[0], 409)
                self.assertEqual(self.state(), before)
                self.update(task, plan, material_status='ready', note='物料核对齐套')
                self.assertEqual(self.task_action(task, 'status', {'status': 'ready', 'note': '核对交接后回队列'})[0], 200)
                self.assertEqual(self.task_action(task, 'status', {'status': 'in_progress'})[0], 200)
                current_plan = self.request('/api/planning/' + plan['id'])[1]['plan']
                self.update(task, current_plan, material_status=material, note='后续批次待补料')
                self.assertEqual(self.task_action(task, 'progress', {'completed_quantity': 1, 'note': '现有来料加工完成一件'})[0], 200)
                self.assertEqual(self.task_action(task, 'status', {'status': 'done'})[0], 200)


if __name__ == '__main__':
    unittest.main()
