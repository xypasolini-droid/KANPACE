"""Configuration preview/install uses temporary stores, never customer data."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import factory_config as config
import operations as ops


class FactoryConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        self.factory = self.call(ops.save_factory, {'name': '独立测试展柜厂', 'factory_type': 'cabinet'})['factory']

    def tearDown(self):
        self.temp.cleanup()

    def call(self, fn, *args, **kwargs):
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            return fn(self.store, con, *args, **kwargs)

    def rows(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def snapshot(self):
        with self.store.connect() as con:
            return [tuple(r) for r in con.execute('SELECT kind,id,project_id,data FROM entities ORDER BY id')]

    def plan(self, **kwargs):
        return self.call(config.save_plan, {'factory_id': self.factory['id'], **kwargs})['plan']

    def preview(self, plan, **kwargs):
        return self.call(config.preview, {'plan_id': plan['id'], 'expected_version': plan['version'], **kwargs})

    def installation(self, plan, preview=None, **kwargs):
        preview = preview or self.preview(plan)
        return {'plan_id': plan['id'], 'expected_version': plan['version'], 'preview_token': preview['preview_token'],
                'reviewed': True, 'reviewer': '工艺主管', 'review_note': '确认对象范围、前序与验收要求；未知工时在首单复核',
                'request_id': 'install_test_00001', **kwargs}

    def failure(self, fn, *args, status=409, code=None, **kwargs):
        with self.assertRaises(ops.OperationError) as caught:
            self.call(fn, *args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        if code:
            self.assertEqual(caught.exception.details['code'], code)
        return caught.exception

    def test_catalog_does_not_create_plans_templates_or_production_tasks(self):
        before = self.snapshot()
        result = self.call(config.catalog, self.factory['id'])
        self.assertEqual(result['factory']['id'], self.factory['id'])
        self.assertEqual(len(result['references']), 1)
        self.assertEqual(result['references'][0]['factory_type'], 'cabinet')
        self.assertIsNone(result['active_profile'])
        self.assertEqual(self.snapshot(), before)

    def test_all_three_scenes_preview_readonly_and_install_versioned_template(self):
        for typ in ops.FACTORY_TYPES:
            with self.subTest(factory_type=typ):
                if typ != self.factory['factory_type']:
                    self.factory = self.call(ops.save_factory, {'name': '测试' + typ, 'factory_type': typ})['factory']
                plan = self.plan()
                before = self.snapshot()
                with self.store.connect() as con:
                    con.execute('PRAGMA query_only=ON')
                    result = config.preview(self.store, con, {'plan_id': plan['id'], 'expected_version': plan['version']})
                self.assertEqual(before, self.snapshot())
                self.assertTrue(result['can_install'])
                self.assertEqual(result['summary']['task_count'], len(plan['nodes']))
                self.assertIsNone(result['summary']['critical_path_minutes_per_object'])
                self.assertEqual(result['summary']['unknown_task_duration_count'], len(plan['nodes']))
                self.assertTrue(all(t['preview_only'] and t['status'] == 'draft' and t['hours'] is None for t in result['tasks']))
                actual = self.call(config.install, self.installation(plan, result))
                self.assertEqual(actual['template']['status'], 'published')
                self.assertEqual(actual['profile']['factory_id'], self.factory['id'])
                self.assertEqual(actual['profile']['version'], 1)
                self.assertEqual(actual['receipt']['changes']['new_production_tasks'], 0)
                self.assertFalse(self.rows('tasks'))
                self.assertFalse(self.rows('projects'))

    def test_preview_contains_parallel_dependencies_and_precise_missing_staff(self):
        worker = self.call(ops.save_person, {'name': '本厂木工', 'factory_id': self.factory['id'], 'skills': ['木工'], 'capacity_minutes': 480})['person']
        other = self.call(ops.save_factory, {'name': '另一厂', 'factory_type': 'cabinet'})['factory']
        self.call(ops.save_person, {'name': '其他厂技术员', 'factory_id': other['id'], 'skills': ['技术'], 'capacity_minutes': 480})
        plan = self.plan()
        result = self.preview(plan)
        self.assertIn(['wood', 'metal', 'glass'], result['stages'])
        missing_trades = {r['trade'] for r in result['missing_resources']}
        self.assertNotIn('木工', missing_trades)
        self.assertIn('技术', missing_trades)
        tasks = {t['template_node_id']: t for t in result['tasks']}
        self.assertEqual(set(tasks['assembly']['dependencies']), {tasks[x]['id'] for x in ('paint', 'metal', 'glass')})
        self.assertNotIn(worker['id'], json.dumps(result, ensure_ascii=False))

    def test_quantity_estimates_and_node_validation_reuse_workflow_rules(self):
        nodes = [ops.node('a', '开料', '木工', acceptance=['尺寸']), ops.node('b', '钻孔', '木工', ['a'], acceptance=['孔位'])]
        nodes[0]['estimated_minutes'] = 20
        nodes[1]['estimated_minutes'] = 10
        plan = self.plan(nodes=nodes)
        objects = [{'code': 'A1', 'name': '工作对象', 'quantity': 3, 'instructions': '确认图纸R1'}]
        result = self.preview(plan, objects=objects)
        self.assertEqual(result['summary']['known_work_minutes'], 90)
        self.assertEqual(result['summary']['critical_path_minutes_per_object'], 30)
        self.assertEqual(result['summary']['unknown_task_duration_count'], 0)
        nodes[0]['predecessors'] = ['b']
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'nodes': nodes}, status=400, code='cyclic_graph')

    def test_install_is_exactly_idempotent_and_rejects_changed_request(self):
        plan = self.plan()
        data = self.installation(plan)
        installed = self.call(config.install, data)
        snapshot = self.snapshot()
        replay = self.call(config.install, data)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['receipt'], installed['receipt'])
        self.assertEqual(snapshot, self.snapshot())
        self.failure(config.install, {**data, 'review_note': '不同内容'}, code='idempotency_conflict')
        self.assertEqual(len(self.rows('workflow_templates')), 1)
        self.assertEqual(len(self.rows(config.PROFILE_KIND)), 1)

    def test_preview_stale_when_people_or_workcenter_or_plan_changes(self):
        plan = self.plan()
        original = self.installation(plan)
        self.call(ops.save_person, {'name': '新工人', 'factory_id': self.factory['id'], 'skills': ['木工']})
        self.failure(config.install, original, code='stale_preview')
        refreshed = self.installation(plan)
        self.call(ops.save_workcenter, {'factory_id': self.factory['id'], 'name': '新工位', 'kind': 'station'})
        self.failure(config.install, refreshed, code='stale_preview')
        refreshed = self.installation(plan)
        updated = self.call(config.save_plan, {'expected_version': plan['version'], 'object_label': '柜号'}, plan['id'])['plan']
        self.failure(config.install, refreshed, code='version_conflict')
        self.assertFalse(self.rows(config.PROFILE_KIND))
        self.assertEqual(updated['version'], 2)

    def test_missing_acceptance_blocks_install_without_partial_writes(self):
        nodes = [ops.node('work', '加工', '木工')]
        plan = self.plan(nodes=nodes)
        result = self.preview(plan)
        self.assertFalse(result['can_install'])
        before = self.snapshot()
        self.failure(config.install, self.installation(plan, result), code='install_blocked')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.rows('workflow_templates'))

    def test_immutable_install_new_version_preserves_old_profile_and_orders(self):
        plan = self.plan()
        first = self.call(config.install, self.installation(plan))
        production = {'id': 'test_project', 'name': '原订单', 'revision': 3, 'factory_id': self.factory['id'], 'status': 'active'}
        with self.store.connect() as con:
            self.store.put(con, 'projects', production)
            self.store.put(con, 'tasks', {'id': 'test_task', 'project_id': production['id'], 'status': 'in_progress',
                           'template_id': first['template']['id'], 'quantity': 1, 'completed_quantity': 0})
        old_production = deepcopy((self.rows('projects'), self.rows('tasks')))
        self.failure(config.save_plan, {'expected_version': 2, 'name': '偷偷改'}, plan['id'], code='immutable_config')
        second_plan = self.plan(source_plan_id=plan['id'], name='第二版流程')
        second = self.call(config.install, self.installation(second_plan, request_id='install_test_00002'))
        self.assertEqual(second['profile']['version'], 2)
        self.assertEqual(second['template']['template_version'], 2)
        self.assertEqual(second['profile']['previous_profile_id'], first['profile']['id'])
        self.assertEqual(first['profile'], self.rows(config.PROFILE_KIND)[0])
        self.assertEqual(old_production, (self.rows('projects'), self.rows('tasks')))
        self.assertEqual(self.call(config.active_profile, self.factory['id'])['id'], second['profile']['id'])

    def test_active_profile_change_invalidates_other_draft_preview(self):
        a, b = self.plan(name='方案A'), self.plan(name='方案B')
        stale_b = self.installation(b, request_id='install_b_00002')
        self.call(config.install, self.installation(a))
        self.failure(config.install, stale_b, code='stale_preview')

    def test_isolated_factory_rejects_foreign_scope_and_document_references(self):
        other = self.call(ops.save_factory, {'name': '他厂', 'factory_type': 'cabinet'})['factory']
        foreign_plan = self.call(config.save_plan, {'factory_id': other['id']})['plan']
        with self.store.connect() as con:
            con.execute('INSERT INTO config(key,value) VALUES(?,?)', ('factory_instance', json.dumps({
                'id': 'inst_' + 'a' * 32, 'factory_id': self.factory['id'], 'factory_type': self.factory['factory_type']})))
        self.failure(config.catalog, other['id'], status=403, code='factory_mismatch')
        self.failure(config.preview, {'plan_id': foreign_plan['id'], 'expected_version': 1}, status=403, code='factory_mismatch')
        own = self.plan()
        self.failure(config.preview, {'plan_id': own['id'], 'expected_version': 1,
                     'objects': [{'code': 'A', 'name': '样件', 'document_ids': ['private_other_document']}]}, code='foreign_document')
        installed = self.call(config.install, self.installation(own))
        self.assertEqual(installed['profile']['instance_id'], 'inst_' + 'a' * 32)
        self.assertEqual(self.call(config.active_profile)['id'], installed['profile']['id'])

    def test_default_page_is_a_supported_route_and_an_enabled_module(self):
        modules = list(config.DEFAULT_MODULES) + ['costs', 'checks']
        for page in ('issues', 'costs', 'checks'):
            with self.subTest(page=page):
                self.failure(config.save_plan, {'factory_id': self.factory['id'],
                             'enabled_modules': modules, 'default_page': page}, status=400)
        self.failure(config.save_plan, {'factory_id': self.factory['id'],
                     'enabled_modules': list(config.CORE_MODULES), 'default_page': 'planning'}, status=400)
        self.assertFalse(self.rows(config.PLAN_KIND))
        for page in config.DEFAULT_PAGES:
            with self.subTest(valid_page=page):
                plan = self.plan(default_page=page)
                self.assertEqual(plan['default_page'], page)

    def test_factory_binding_modules_and_approval_are_enforced(self):
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'factory_type': 'site'}, code='factory_mismatch')
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'enabled_modules': ['projects']}, status=400)
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'source_requirements': ['render']}, status=400)
        plan = self.plan()
        data = self.installation(plan)
        self.failure(config.install, {**data, 'reviewed': False}, status=400, code='review_required')
        self.failure(config.install, {**data, 'reviewer': ''}, status=400)
        self.failure(config.install, {**data, 'review_note': ''}, status=400)
        self.assertFalse(self.rows('workflow_templates'))


if __name__ == '__main__':
    unittest.main()
