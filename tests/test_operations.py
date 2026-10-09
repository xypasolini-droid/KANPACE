"""Isolated workflow and organization tests. No live data or hardware access."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import operations as ops


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, *args, **kwargs):
        with self.store.connect() as con:
            return getattr(ops, method)(self.store, con, *args, **kwargs)

    def all(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def put(self, kind, item):
        with self.store.connect() as con:
            self.store.put(con, kind, item)

    def failure(self, method, *args, status=409, **kwargs):
        with self.assertRaises(ops.OperationError) as ctx:
            self.call(method, *args, **kwargs)
        self.assertEqual(ctx.exception.status, status, ctx.exception.message)
        return ctx.exception

    def factory(self, typ='cabinet', name='测试工厂'):
        return self.call('save_factory', {'name': name, 'factory_type': typ})['factory']

    def template(self, typ='cabinet', factory=None, nodes=None):
        data = {'source_template_id': 'builtin_' + typ + '_v1', 'name': '已核对的' + typ}
        if factory:
            data['factory_id'] = factory['id']
        if nodes:
            data['nodes'] = nodes
        draft = self.call('save_template', data)['template']
        return self.call('publish_template', draft['id'], {'expected_version': draft['version']})['template']

    def project(self, typ='cabinet'):
        p = {'id': ops.uid('prj'), 'name': '测试生产订单', 'factory_type': typ, 'revision': 1,
             'status': 'draft', 'demo': False, 'fulfillment_status': 'active'}
        self.put('projects', p)
        return p

    def workflow(self, typ='cabinet', objects=None, nodes=None):
        f = self.factory(typ)
        p = self.project(typ)
        t = self.template(typ, f, nodes)
        result = self.call('save_workflow', p['id'], {'template_id': t['id'], 'factory_id': f['id'],
                          'expected_revision': 1, 'expected_version': 0, 'scope_note': '根据已确认图纸的人工工作包',
                          'objects': objects or [{'code': 'A01', 'name': '一号工作对象', 'quantity': 2, 'unit': '台',
                                                 'location': '车间A', 'instructions': '按R1加工并核验连接尺寸'}]})
        return f, p, t, result

    def review(self, p, result):
        return self.call('review_workflow', p['id'], {'expected_version': result['workflow']['version'],
                         'reviewer': '测试负责人', 'review_note': '已逐对象核对技术要求及来源', 'acknowledge_manual_scope': True})

    def test_read_does_not_seed_real_resources_or_mutate_legacy(self):
        before = self.all('people')
        result = self.call('build')
        self.assertEqual(result['factories'], [])
        self.assertEqual(result['people'], [])
        self.assertEqual(len(result['builtin_templates']), 3)
        self.assertEqual(before, self.all('people'))
        self.assertFalse(self.all('workflow_templates'))
        for template in result['builtin_templates']:
            self.assertTrue(all(n['estimated_minutes'] is None for n in template['nodes']))
            self.assertNotIn('拍摄', json.dumps(template, ensure_ascii=False))
            ops.dag_order(template['nodes'])

    def test_resource_membership_unknown_capacity_custom_trade_and_conflict(self):
        f = self.factory('machinery')
        other = self.factory('site', '另一现场')
        team = self.call('save_team', {'name': '调试班', 'factory_id': f['id']})['team']
        p = self.call('save_person', {'name': '测试技师', 'skills': ['机器人调试'], 'factory_id': f['id'],
                     'team_id': team['id'], 'capacity_minutes': None})['person']
        self.assertIsNone(p['capacity_minutes'])
        self.assertEqual(p['skills'], ['机器人调试'])
        self.failure('save_person', {'expected_version': p['version'], 'factory_id': other['id']}, p['id'])
        self.failure('save_person', {'expected_version': 0, 'name': '陈师傅'}, p['id'])
        self.assertEqual(self.all('people')[-1], p)
        wc = self.call('save_workcenter', {'name': '测试工位', 'factory_id': f['id'], 'team_id': team['id'], 'kind': 'station'})['workcenter']
        self.assertIsNone(wc['capacity_minutes'])
        self.failure('save_workcenter', {'name': '异厂工位', 'factory_id': other['id'], 'team_id': team['id']})
        self.assertTrue(ops.assignment_issues({'factory_id': other['id']}, p))
        self.assertFalse(ops.assignment_issues({'factory_id': f['id']}, p))
        self.assertFalse(ops.assignment_issues({}, p))

    def test_person_change_invalidates_pending_assignment(self):
        f, project, _, result = self.workflow()
        person = self.call('save_person', {'name': '师傅', 'skills': ['技术'], 'factory_id': f['id'], 'capacity_minutes': 480})['person']
        task = result['tasks'][0]
        task.update(assignee=person['id'], status='ready')
        self.put('tasks', task)
        updated = self.call('save_person', {'expected_version': person['version'], 'factory_id': None}, person['id'])['person']
        changed = next(t for t in self.all('tasks') if t['id'] == task['id'])
        self.assertIsNone(changed['assignee'])
        self.assertEqual(changed['execution_version'], task['execution_version'] + 1)
        self.assertEqual(updated['factory_id'], None)
        self.assertEqual(changed['reassignment_from'], person['id'])
        self.failure('save_person', {'expected_version': person['version'], 'skills': ['木工']}, person['id'])

    def test_template_validation_cycles_missing_ids_and_unknown_duration(self):
        base = ops.builtin_templates()[0]
        nodes = deepcopy(base['nodes'])
        nodes[0]['predecessors'] = ['packing']
        self.failure('save_template', {'name': '循环', 'factory_type': 'cabinet', 'nodes': nodes}, status=400)
        nodes[0]['predecessors'] = ['no_such_node']
        self.failure('save_template', {'name': '错误前序', 'factory_type': 'cabinet', 'nodes': nodes}, status=400)
        nodes[0]['predecessors'] = []
        for bad in (0, -1, True, float('nan')):
            nodes[0]['estimated_minutes'] = bad
            self.failure('save_template', {'name': '工时错误', 'factory_type': 'cabinet', 'nodes': nodes}, status=400)
        self.assertEqual(self.all('workflow_templates'), [])

    def test_publish_requires_acceptance_and_is_immutable(self):
        draft = self.call('save_template', {'source_template_id': 'builtin_cabinet_v1'})['template']
        nodes = deepcopy(draft['nodes'])
        nodes[0]['acceptance'] = []
        draft = self.call('save_template', {'expected_version': draft['version'], 'nodes': nodes}, draft['id'])['template']
        self.failure('publish_template', draft['id'], {'expected_version': draft['version']}, status=400)
        self.assertEqual(self.all('workflow_templates')[0]['status'], 'draft')
        nodes[0]['acceptance'] = ['核对尺寸']
        draft = self.call('save_template', {'expected_version': draft['version'], 'nodes': nodes}, draft['id'])['template']
        published = self.call('publish_template', draft['id'], {'expected_version': draft['version']})['template']
        self.failure('save_template', {'expected_version': published['version'], 'name': '偷偷修改'}, published['id'])
        copied = self.call('save_template', {'source_template_id': published['id'], 'name': '第二版'})['template']
        self.assertEqual(published['template_version'], 1)
        self.assertEqual(copied['template_version'], 2)
        self.assertEqual(copied['parent_template_id'], published['id'])
        self.assertEqual(self.all('workflow_templates')[0], published)

    def test_three_scene_objects_compile_real_dag_and_keep_unknown_hours(self):
        for typ in ops.FACTORY_TYPES:
            with self.subTest(typ=typ):
                _, p, template, result = self.workflow(typ, objects=[
                    {'code': 'B1', 'name': '第一批', 'quantity': 1, 'instructions': '依现场确认单执行', 'batch_code': '首批', 'delivery_group': '首车'},
                    {'code': 'B2', 'name': '第二批', 'quantity': 1, 'instructions': '依施工图R2执行', 'batch_code': '二批'}])
                tasks = result['tasks']
                self.assertEqual(len(tasks), len(template['nodes']) * 2)
                self.assertTrue(all(t['hours'] is None and t['status'] == 'draft' for t in tasks))
                self.assertTrue(all(t['source']['kind'] == 'reviewed_work_package' for t in tasks))
                by_id = {t['id']: t for t in tasks}
                for task in tasks:
                    self.assertTrue(all(by_id[d]['object_code'] == task['object_code'] for d in task['dependencies']))
                self.assertTrue(any(t['inspection_required'] for t in tasks))
                self.assertEqual(result['workflow']['status'], 'draft')
                self.assertTrue(self.call('release_blockers', result['project']))
                reviewed = self.review(p, result)['workflow']
                self.assertEqual(reviewed['status'], 'reviewed')
                self.assertEqual(self.call('release_blockers', result['project']), [])
                self.assertTrue(all(t['status'] == 'draft' for t in self.all('tasks') if t['project_id'] == p['id']))

    def test_workflow_requires_published_template_matching_factory_and_revision(self):
        f, p, template, result = self.workflow()
        data = {'template_id': 'builtin_cabinet_v1', 'factory_id': f['id'], 'expected_revision': 1,
                'expected_version': result['workflow']['version'], 'scope_note': '人工工作范围',
                'objects': [{'code': 'A', 'name': '测试', 'quantity': 1, 'instructions': '按施工图'}]}
        before = self.all('tasks')
        self.failure('save_workflow', p['id'], data)
        data['template_id'] = template['id']
        data['expected_revision'] = 9
        self.failure('save_workflow', p['id'], data)
        self.assertEqual(before, self.all('tasks'))
        data['expected_revision'] = 1
        data['factory_id'] = self.factory('site')['id']
        self.failure('save_workflow', p['id'], data)
        self.assertEqual(before, self.all('tasks'))

    def test_explicit_scope_review_and_document_ownership(self):
        _, p, _, result = self.workflow(objects=[{'code': 'A', 'name': '未明确对象', 'quantity': 1}])
        self.failure('review_workflow', p['id'], {'expected_version': 1, 'reviewer': '负责人', 'review_note': '确认',
                                               'acknowledge_manual_scope': True})
        self.assertTrue(self.call('release_blockers', result['project']))
        f = self.factory()
        template = self.template(factory=f)
        other = self.project()
        self.put('documents', {'id': 'doc_other', 'project_id': other['id'], 'filename': '另一个项目.pdf'})
        self.failure('save_workflow', p['id'], {'template_id': template['id'], 'factory_id': f['id'], 'expected_revision': 1,
                     'expected_version': 1, 'scope_note': '人工范围',
                     'objects': [{'code': 'A', 'name': '对象', 'document_ids': ['doc_other']}]})

    def test_duplicate_objects_and_legacy_production_tasks_never_overwritten(self):
        _, p, _, result = self.workflow()
        before = self.all('tasks')
        data = {key: result['workflow'][key] for key in ('template_id', 'factory_id', 'objects', 'scope_note')}
        data.update(expected_version=1, expected_revision=1)
        data['objects'] *= 2
        self.failure('save_workflow', p['id'], data, status=400)
        self.assertEqual(before, self.all('tasks'))
        data['objects'] = data['objects'][:1]
        t = deepcopy(result['tasks'][0]); t['status'] = 'ready'; self.put('tasks', t)
        before = self.all('tasks')
        self.failure('save_workflow', p['id'], data)
        self.assertEqual(before, self.all('tasks'))

    def change_template(self, template, target_id='packing'):
        nodes = deepcopy(template['nodes'])
        next(n for n in nodes if n['id'] == target_id)['acceptance'].append('追加标签检查')
        draft = self.call('save_template', {'source_template_id': template['id'], 'nodes': nodes})['template']
        return self.call('publish_template', draft['id'], {'expected_version': draft['version']})['template']

    def test_migration_impact_token_stale_and_progress_guard(self):
        _, p, template, result = self.workflow()
        after = self.change_template(template)
        preview = self.call('migration_preview', p['id'], {'template_id': after['id']})
        self.assertEqual(preview['changed'], ['packing'])
        self.assertTrue(preview['can_migrate'])
        task = next(t for t in result['tasks'] if t['template_node_id'] == 'packing')
        task.update(status='in_progress', started_at=ops.stamp(), execution_version=1)
        self.put('tasks', task)
        payload = {key: preview[key] for key in ('template_id', 'expected_version', 'expected_revision', 'impact_token')}
        payload['review_note'] = '核对流程变化'
        self.failure('migrate_workflow', p['id'], payload)
        fresh = self.call('migration_preview', p['id'], {'template_id': after['id']})
        self.assertFalse(fresh['can_migrate'])
        self.assertEqual(fresh['blockers'][0]['id'], task['id'])
        self.assertEqual(self.all('projects')[0]['revision'], 1)

    def test_migration_preserves_completed_unaffected_work_and_history(self):
        _, p, template, result = self.workflow()
        task = result['tasks'][0]
        task.update(status='done', completed_quantity=task['quantity'], completed_at=ops.stamp(), started_at=ops.stamp())
        self.put('tasks', task)
        after = self.change_template(template)
        preview = self.call('migration_preview', p['id'], {'template_id': after['id']})
        payload = {key: preview[key] for key in ('template_id', 'expected_version', 'expected_revision', 'impact_token')}
        payload['review_note'] = '只更改未开始的包装要求'
        migrated = self.call('migrate_workflow', p['id'], payload)
        self.assertEqual(migrated['project']['revision'], 2)
        self.assertEqual(migrated['workflow']['status'], 'draft')
        carried = next(t for t in migrated['tasks'] if t.get('carried_from_task_id') == task['id'])
        self.assertEqual((carried['status'], carried['completed_quantity']), ('done', 2))
        self.assertTrue(all(t.get('archived') for t in self.all('tasks') if t['id'] in result['workflow']['task_ids']))
        self.review(migrated['project'], migrated)
        self.assertEqual(self.call('release_blockers', migrated['project']), [])
        self.assertEqual(len(self.all('project_workflows')), 2)

    def test_unfinished_rework_blocks_migration_even_unchanged_node(self):
        _, p, template, result = self.workflow()
        original = result['tasks'][0]
        rework = dict(original, id='task_rework_unfinished', rework_of=original['id'], title='返工', status='draft', quantity=1)
        self.put('tasks', rework)
        after = self.change_template(template)
        preview = self.call('migration_preview', p['id'], {'template_id': after['id']})
        self.assertFalse(preview['can_migrate'])
        self.assertEqual(preview['blockers'][0]['id'], rework['id'])
        self.assertIn('返工', preview['blockers'][0]['reason'])
        payload = {key: preview[key] for key in ('template_id', 'expected_version', 'expected_revision', 'impact_token')}
        self.failure('migrate_workflow', p['id'], dict(payload, review_note='不应覆盖返工'))

    def test_completed_rework_history_does_not_override_original_completed_quantity(self):
        _, p, template, result = self.workflow()
        original = result['tasks'][0]
        original.update(status='done', completed_quantity=2, completed_at=ops.stamp(), started_at=ops.stamp(), quality_hold_since=ops.stamp())
        self.put('tasks', original)
        rework = dict(original, id='task_rework_complete', rework_of=original['id'], title='返工', quantity=1, completed_quantity=1)
        self.put('tasks', rework)
        after = self.change_template(template)
        preview = self.call('migration_preview', p['id'], {'template_id': after['id']})
        self.assertTrue(preview['can_migrate'])
        self.assertEqual(preview['historical_reworks'][0]['id'], rework['id'])
        payload = {key: preview[key] for key in ('template_id', 'expected_version', 'expected_revision', 'impact_token')}
        migrated = self.call('migrate_workflow', p['id'], dict(payload, review_note='仅变更未开工包装'))
        carried = next(t for t in migrated['tasks'] if t['template_node_id'] == original['template_node_id'])
        self.assertEqual(carried['carried_from_task_id'], original['id'])
        self.assertEqual(carried['completed_quantity'], 2)
        self.assertEqual(carried['quality_hold_since'], original['quality_hold_since'])
        old_rework = next(t for t in self.all('tasks') if t['id'] == rework['id'])
        self.assertTrue(old_rework['archived'])
        self.assertEqual(old_rework['previous_status'], 'done')
        self.assertEqual(old_rework['completed_quantity'], 1)

    def test_migration_tracks_downstream_dependency_changes(self):
        _, p, template, result = self.workflow()
        after = self.change_template(template, 'wood')
        preview = self.call('migration_preview', p['id'], {'template_id': after['id']})
        impacted = {t['id'] for t in preview['affected_tasks']}
        self.assertEqual({t['template_node_id'] for t in result['tasks'] if t['id'] in impacted},
                         {'wood', 'paint', 'assembly', 'electrical', 'quality', 'packing'})

    def test_workcenter_cannot_cross_template_factory(self):
        f = self.factory()
        other = self.factory()
        wc = self.call('save_workcenter', {'name': '别厂喷房', 'factory_id': other['id'], 'kind': 'equipment'})['workcenter']
        nodes = deepcopy(ops.builtin_templates()[0]['nodes'])
        nodes[0]['workcenter_id'] = wc['id']
        self.failure('save_template', {'name': '错误资源绑定', 'factory_type': 'cabinet', 'factory_id': f['id'], 'nodes': nodes})

    def test_factory_filter_keeps_unbound_legacy_real_people_visible(self):
        f = self.factory('machinery')
        self.call('save_person', {'name': '待归属员工', 'skills': ['安装'], 'capacity_minutes': None})
        self.call('save_person', {'name': '机械员工', 'skills': ['调试'], 'factory_id': f['id'], 'capacity_minutes': 480})
        cabinet = self.call('build', factory_type='cabinet')
        self.assertEqual([p['name'] for p in cabinet['people']], ['待归属员工'])
        self.assertEqual(len(cabinet['builtin_templates']), 1)
        self.assertEqual(len(self.call('build', factory_type='machinery')['people']), 2)


if __name__ == '__main__':
    unittest.main()
