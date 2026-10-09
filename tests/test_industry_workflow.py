"""Real work packages preserve their own reviewed industry schemas and values."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import factory_config as config
import industry_templates as industries
import operations as ops


class IndustryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        self.factory = self.call(ops.save_factory, {'name': '临时工厂', 'factory_type': 'cabinet'})['factory']
        ref = industries.resolve(industries.catalog()[0]['id'])
        self.fields = [{'id': 'drawing_revision', 'label': '图纸版本', 'type': 'text', 'required': True},
                       {'id': 'surface_area', 'label': '加工面积', 'type': 'decimal', 'unit': 'm²', 'required': True}]
        plan = self.call(config.save_plan, {'factory_id': self.factory['id'], 'industry_id': ref['industry_id'],
                         'variant_id': ref['variant_id'], 'object_fields': self.fields})['plan']
        preview = self.call(config.preview, {'plan_id': plan['id'], 'expected_version': plan['version']})
        self.installed = self.call(config.install, {'plan_id': plan['id'], 'expected_version': plan['version'],
            'preview_token': preview['preview_token'], 'reviewed': True, 'reviewer': '本厂技术员',
            'review_note': '核对工序和对象字段', 'request_id': 'workflow_install_0001'})
        self.template = self.installed['template']
        self.project = {'id': ops.uid('prj'), 'name': '临时合成订单', 'factory_type': 'cabinet',
                        'factory_id': self.factory['id'], 'revision': 1, 'status': 'draft', 'demo': False, 'fulfillment_status': 'active'}
        self.put('projects', self.project)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, fn, *args, **kwargs):
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            return fn(self.store, con, *args, **kwargs)

    def put(self, kind, record):
        with self.store.connect() as con:
            self.store.put(con, kind, record)

    def rows(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def failure(self, fn, *args, code=None, status=409, **kwargs):
        with self.assertRaises(ops.OperationError) as caught:
            self.call(fn, *args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        if code:
            self.assertEqual(caught.exception.details['code'], code)
        return caught.exception

    def obj(self, **extra):
        return {'code': 'B1', 'name': '板件批次', 'quantity': 2, 'unit': '批', 'instructions': '根据确认图纸逐件核对',
                'industry_fields': {'drawing_revision': 'R3', 'surface_area': 1.234567}, **extra}

    def save(self, objects=None, expected_version=0):
        return self.call(ops.save_workflow, self.project['id'], {'template_id': self.template['id'],
                         'factory_id': self.factory['id'], 'expected_revision': 1, 'expected_version': expected_version,
                         'scope_note': '首批已确认资料', 'objects': objects or [self.obj()]})

    def review(self, workflow):
        return self.call(ops.review_workflow, self.project['id'], {'expected_version': workflow['version'],
                         'acknowledge_manual_scope': True, 'reviewer': '测试审核人', 'review_note': '已核对图纸版本、面积和工艺要求'})

    def test_industry_details_reach_each_task_and_keep_physical_amount_separate_from_batch_count(self):
        result = self.save()
        self.assertEqual(result['workflow']['object_fields'], self.template['object_fields'])
        for task in result['tasks']:
            self.assertEqual(task['quantity'], 2)
            self.assertEqual(task['unit'], '批')
            self.assertEqual(task['industry_fields']['surface_area'], 1.234567)
            self.assertIn('图纸版本：R3', task['instructions'])
            self.assertIn('加工面积：1.234567 m²', task['instructions'])
            self.assertEqual(task['industry_id'], self.template['industry_id'])
            self.assertEqual(task['source']['industry_origin_hash'], self.template['industry_origin']['hash'])
            self.assertIsNone(task['hours'])
        reviewed = self.review(result['workflow'])
        self.assertEqual(reviewed['workflow']['status'], 'reviewed')
        self.assertFalse(self.call(ops.release_blockers, result['project']))

    def test_all_industry_variants_create_reviewable_work_packages_with_real_field_values(self):
        count = 0
        for industry in industries.catalog():
            for variant in industry['variants']:
                with self.subTest(industry=industry['id'], variant=variant['id']):
                    ref = industries.resolve(industry['id'], variant['id'])
                    plan = self.call(config.save_plan, {'factory_id': self.factory['id'],
                        'industry_id': industry['id'], 'variant_id': variant['id']})['plan']
                    preview = self.call(config.preview, {'plan_id': plan['id'], 'expected_version': plan['version']})
                    count += 1
                    installed = self.call(config.install, {'plan_id': plan['id'], 'expected_version': plan['version'],
                        'preview_token': preview['preview_token'], 'reviewed': True, 'reviewer': '测试技术员',
                        'review_note': '核对本类型的工艺范围', 'request_id': 'all_industry_workflow_' + str(count)})
                    project = {**self.project, 'id': ops.uid('prj'), 'name': ref['name'] + '合成测试'}
                    self.put('projects', project)
                    values = {f['id']: 1.25 if f['type'] == 'decimal' else '本厂确认资料 R1'
                              for f in plan['object_fields']}
                    result = self.call(ops.save_workflow, project['id'], {'factory_id': self.factory['id'],
                        'template_id': installed['template']['id'], 'expected_version': 0, 'expected_revision': 1,
                        'scope_note': '合成订单测试范围', 'objects': [{'code': 'TEST-01', 'name': plan['object_label'],
                            'quantity': 1, 'unit': plan['object_unit'], 'industry_fields': values, 'instructions': '经测试技术员确认的本对象范围'}]})
                    self.assertEqual(len(result['tasks']), len(ref['nodes']))
                    self.assertTrue(all(t['industry_fields'] == values for t in result['tasks']))
                    reviewed = self.call(ops.review_workflow, project['id'], {'expected_version': 1,
                        'acknowledge_manual_scope': True, 'reviewer': '测试技术员', 'review_note': '合成对象全部字段已核对'})
                    self.assertEqual(reviewed['workflow']['status'], 'reviewed')
                    self.assertFalse(self.call(ops.release_blockers, result['project']))
        self.assertGreaterEqual(count, 28)

    def test_missing_industry_values_can_save_draft_but_block_review_and_release(self):
        result = self.save([self.obj(industry_fields={})])
        self.assertEqual(result['workflow']['status'], 'draft')
        blocked = self.failure(ops.review_workflow, self.project['id'], {'expected_version': 1,
                     'acknowledge_manual_scope': True, 'reviewer': '技术员', 'review_note': '准备复核'}, code='industry_fields_missing')
        self.assertEqual({f['field_id'] for f in blocked.details['fields']}, {'drawing_revision', 'surface_area'})
        self.assertTrue(any('行业对象资料未完整' in message for message in self.call(ops.release_blockers, result['project'])))
        fixed = self.save(expected_version=1)
        self.assertEqual(self.review(fixed['workflow'])['workflow']['status'], 'reviewed')

    def test_unknown_fields_invalid_numbers_and_text_types_never_enter_tasks(self):
        invalid = [{'unknown': '私货'}, {'surface_area': True}, {'surface_area': float('nan')},
                   {'surface_area': float('inf')}, {'surface_area': -1}, {'surface_area': 0},
                   {'surface_area': '1.25'}, {'drawing_revision': ['R1']}, {'drawing_revision': 'x' * 501}]
        for values in invalid:
            with self.subTest(values=values):
                self.failure(ops.save_workflow, self.project['id'], {'template_id': self.template['id'],
                    'factory_id': self.factory['id'], 'expected_revision': 1, 'expected_version': 0,
                    'scope_note': '来源', 'objects': [self.obj(industry_fields=values)]}, status=400)
        self.assertFalse(self.rows('tasks'))
        self.assertFalse(self.rows('project_workflows'))

    def test_template_clone_retains_origin_and_schema_but_no_customer_object_values(self):
        result = self.save()
        clone = self.call(ops.save_template, {'source_template_id': self.template['id'], 'name': '本厂下一版'})['template']
        self.assertEqual(clone['industry_origin'], self.template['industry_origin'])
        self.assertEqual(clone['object_fields'], self.template['object_fields'])
        self.assertNotIn('objects', clone)
        self.assertNotIn('industry_fields', clone)
        clone = self.call(ops.publish_template, clone['id'], {'expected_version': clone['version']})['template']
        self.assertEqual(result['workflow']['template_id'], self.template['id'])
        self.assertNotEqual(clone['id'], self.template['id'])
        self.failure(ops.save_template, {'expected_version': clone['version'], 'name': '改已发布'}, clone['id'], code='immutable_template')

    def test_schema_changes_cannot_silently_migrate_existing_work_package(self):
        self.save()
        metadata = {key: deepcopy(self.template.get(key)) for key in ops.INDUSTRY_METADATA_KEYS}
        metadata['object_fields'][0]['label'] = '版本与确认日期'
        clone = self.call(ops.save_template, {'source_template_id': self.template['id'], 'name': '字段变更'}, industry_metadata=metadata)['template']
        clone = self.call(ops.publish_template, clone['id'], {'expected_version': clone['version']})['template']
        self.assertNotEqual(clone['content_hash'], self.template['content_hash'])
        self.failure(ops.migration_preview, self.project['id'], {'template_id': clone['id']}, code='industry_schema_changed')

    def test_ordinary_template_payload_cannot_forge_origin_snapshot(self):
        self.failure(ops.save_template, {'name': '伪造来源', 'factory_type': 'cabinet',
                     'nodes': self.template['nodes'], 'industry_origin': {'hash': 'forged'}}, status=400)

    def test_legacy_object_validation_still_works_without_industry_schema(self):
        with self.store.connect() as con:
            objects = ops.validate_objects(self.store, con, self.project['id'], [{'code': 'LEGACY', 'name': '旧对象'}])
        self.assertEqual(objects[0]['quantity'], 1)
        self.assertEqual(objects[0]['industry_fields'], {})
        self.assertFalse(ops.missing_industry_fields(objects, []))


if __name__ == '__main__':
    unittest.main()
