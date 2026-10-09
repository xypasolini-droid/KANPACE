"""Industry configuration installation tests: every write uses a temporary store."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import factory_config as config
import industry_templates as industries
import operations as ops


class IndustryConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        self.factory = self.call(ops.save_factory, {'name': '行业模板测试厂', 'factory_type': 'cabinet'})['factory']

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

    def failure(self, fn, *args, code=None, status=409, **kwargs):
        with self.assertRaises(ops.OperationError) as caught:
            self.call(fn, *args, **kwargs)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        if code:
            self.assertEqual(caught.exception.details['code'], code)
        return caught.exception

    def reference(self, index=0):
        item = industries.catalog()[index]
        return industries.resolve(item['id'], item['variants'][0]['id'])

    def plan(self, reference=None, **extra):
        ref = reference or self.reference()
        return self.call(config.save_plan, {'factory_id': self.factory['id'], 'industry_id': ref['industry_id'],
                         'variant_id': ref['variant_id'], 'source_industry_hash': ref['hash'], **extra})['plan']

    def preview(self, plan, **extra):
        return self.call(config.preview, {'plan_id': plan['id'], 'expected_version': plan['version'], **extra})

    def installation(self, plan, preview=None, request_id='industry_install_0001', **extra):
        result = preview or self.preview(plan)
        return {'plan_id': plan['id'], 'expected_version': plan['version'], 'preview_token': result['preview_token'],
                'reviewed': True, 'reviewer': '测试工艺员', 'review_note': '确认所选行业、生产类型、工序范围和验收项；首单核对工时',
                'request_id': request_id, **extra}

    def test_all_nineteen_industries_and_every_variant_install_without_touching_production(self):
        catalog = industries.catalog()
        self.assertEqual(len(catalog), 19)
        before = self.snapshot()
        loaded = self.call(config.catalog, self.factory['id'])
        self.assertEqual(len(loaded['industries']), 19)
        self.assertEqual(len(loaded['references']), 1)  # Legacy references remain compatible.
        self.assertEqual(before, self.snapshot())
        old_profiles = []
        count = 0
        for industry in catalog:
            for variant in industry['variants']:
                with self.subTest(industry=industry['id'], variant=variant['id']):
                    ref = industries.resolve(industry['id'], variant['id'])
                    plan = self.plan(ref)
                    self.assertEqual(plan['factory_type'], 'cabinet')  # Never retypes an existing factory.
                    self.assertEqual(plan['industry_origin'], ref)
                    self.assertEqual(plan['nodes'], ops.validate_nodes(self.store, None, ref['nodes']))
                    before = self.snapshot()
                    with self.store.connect() as con:
                        con.execute('PRAGMA query_only=ON')
                        preview = config.preview(self.store, con, {'plan_id': plan['id'], 'expected_version': plan['version']})
                    self.assertEqual(before, self.snapshot())
                    self.assertTrue(preview['can_install'])
                    self.assertEqual(len(preview['tasks']), len(ref['nodes']))
                    self.assertTrue(all(t['hours'] is None and t['status'] == 'draft' for t in preview['tasks']))
                    count += 1
                    installed = self.call(config.install, self.installation(plan, preview, 'industry_install_' + str(count)))
                    profile, template = installed['profile'], installed['template']
                    self.assertEqual(profile['industry_id'], industry['id'])
                    self.assertEqual(profile['variant_id'], variant['id'])
                    self.assertEqual(template['industry_origin'], ref)
                    self.assertEqual(template['object_fields'], plan['object_fields'])
                    self.assertEqual(template['status'], 'published')
                    self.assertEqual(profile['version'], count)
                    self.assertEqual(old_profiles, self.rows(config.PROFILE_KIND)[:len(old_profiles)])
                    old_profiles.append(profile)
        self.assertFalse(self.rows('projects'))
        self.assertFalse(self.rows('tasks'))
        self.assertEqual(self.rows('factories'), [self.factory])
        self.assertGreaterEqual(count, 28)

    def test_switch_resets_route_object_schema_and_sources_unless_explicitly_edited(self):
        a, b = self.reference(0), self.reference(1)
        plan = self.plan(a, name='上一个行业的私有方案')
        changed = self.call(config.save_plan, {'expected_version': plan['version'], 'industry_id': b['industry_id'],
                            'variant_id': b['variant_id']}, plan['id'])['plan']
        self.assertEqual(changed['name'], b['name'])
        self.assertEqual(changed['nodes'], ops.validate_nodes(self.store, None, b['nodes']))
        self.assertEqual(changed['object_fields'], ops.validate_object_fields(b['object_fields']))
        self.assertEqual(changed['source_requirements'], b['source_requirements'])
        local = deepcopy(a['nodes'])
        local[0]['name'] = '本厂调整的首道工序'
        changed = self.call(config.save_plan, {'expected_version': changed['version'], 'industry_id': a['industry_id'],
                            'variant_id': a['variant_id'], 'nodes': local}, changed['id'])['plan']
        self.assertEqual(changed['nodes'][0]['name'], '本厂调整的首道工序')
        self.assertEqual(changed['industry_origin']['nodes'][0]['name'], a['nodes'][0]['name'])

    def test_clear_industry_returns_to_legacy_reference(self):
        plan = self.plan()
        cleared = self.call(config.save_plan, {'expected_version': plan['version'], 'industry_id': '', 'variant_id': ''}, plan['id'])['plan']
        self.assertIsNone(cleared['industry_id'])
        self.assertEqual(cleared['object_fields'], [])
        self.assertEqual(cleared['nodes'], ops.validate_nodes(self.store, None, ops.builtin_templates()[0]['nodes']))

    def test_new_factory_industry_selection_is_default_for_its_first_plan(self):
        ref = self.reference(1)
        with self.store.connect() as con:
            self.store.put(con, 'factories', {**self.factory, 'industry_id': ref['industry_id'], 'variant_id': ref['variant_id']})
        plan = self.call(config.save_plan, {'factory_id': self.factory['id']})['plan']
        self.assertEqual(plan['industry_id'], ref['industry_id'])
        self.assertEqual(plan['variant_id'], ref['variant_id'])
        self.assertEqual(plan['nodes'], ops.validate_nodes(self.store, None, ref['nodes']))
        legacy = self.call(config.save_plan, {'factory_id': self.factory['id'], 'industry_id': '', 'variant_id': ''})['plan']
        self.assertIsNone(legacy['industry_id'])

    def test_unknown_selection_and_stale_hash_do_not_write_partial_plans(self):
        before = self.snapshot()
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'industry_id': 'not_an_industry'},
                     status=400, code='unknown_industry_template')
        ref = self.reference()
        self.failure(config.save_plan, {'factory_id': self.factory['id'], 'industry_id': ref['industry_id'],
                     'source_industry_hash': '0' * 64}, code='stale_industry_reference')
        self.assertEqual(before, self.snapshot())

    def test_reference_updates_require_explicit_refresh_and_old_install_receipts_stay_replayable(self):
        plan = self.plan()
        original = self.installation(plan)
        installed = self.call(config.install, original)
        copy = self.plan(source_plan_id=plan['id'])
        old = industries.resolve

        def updated(industry_id, variant_id=None):
            value = deepcopy(old(industry_id, variant_id))
            value['hash'] = value['content_hash'] = '1' * 64
            return value

        with patch.object(industries, 'resolve', side_effect=updated):
            replay = self.call(config.install, original)
            self.assertTrue(replay['replayed'])
            self.assertEqual(replay['profile'], installed['profile'])
            self.failure(config.preview, {'plan_id': copy['id'], 'expected_version': copy['version']}, code='stale_industry_reference')
            refreshed = self.call(config.save_plan, {'expected_version': copy['version'], 'source_industry_hash': '1' * 64}, copy['id'])['plan']
            self.assertEqual(refreshed['industry_origin']['hash'], '1' * 64)
            self.assertTrue(self.preview(refreshed)['can_install'])
        self.assertEqual(self.rows(config.PROFILE_KIND)[0], installed['profile'])

    def test_sample_field_values_bind_preview_token_and_never_create_production_tasks(self):
        plan = self.plan(object_fields=[{'id': 'physical_amount', 'label': '面积', 'type': 'decimal', 'required': True, 'unit': 'm²'}])
        objects = [{'code': 'B1', 'name': '第一批', 'quantity': 2, 'industry_fields': {'physical_amount': 1.25}}]
        preview = self.preview(plan, objects=objects)
        self.assertEqual(preview['tasks'][0]['industry_fields']['physical_amount'], 1.25)
        changed = deepcopy(objects)
        changed[0]['industry_fields']['physical_amount'] = 2.5
        self.failure(config.install, self.installation(plan, preview, objects=changed), code='stale_preview')
        installed = self.call(config.install, self.installation(plan, preview, objects=objects))
        self.assertEqual(installed['profile']['object_fields'][0]['unit'], 'm²')
        self.assertFalse(self.rows('tasks'))

    def test_cross_factory_copy_and_isolated_catalog_access_remain_blocked(self):
        plan = self.plan()
        other = self.call(ops.save_factory, {'name': '另一客户', 'factory_type': 'cabinet'})['factory']
        self.failure(config.save_plan, {'factory_id': other['id'], 'source_plan_id': plan['id']}, status=403, code='factory_mismatch')
        with self.store.connect() as con:
            con.execute('INSERT INTO config(key,value) VALUES(?,?)', ('factory_instance', json.dumps({
                'id': 'inst_' + 'a' * 32, 'factory_id': self.factory['id'], 'factory_type': 'cabinet'})))
        self.failure(config.catalog, other['id'], status=403, code='factory_mismatch')
        self.assertEqual(len(self.call(config.catalog, self.factory['id'])['industries']), 19)

    def test_install_is_immutable_and_request_reuse_rejects_different_content(self):
        plan = self.plan()
        request = self.installation(plan)
        installed = self.call(config.install, request)
        self.failure(config.install, {**request, 'review_note': '不同说明'}, code='idempotency_conflict')
        self.failure(config.save_plan, {'expected_version': 2, 'industry_id': self.reference(1)['industry_id']}, plan['id'], code='immutable_config')
        self.assertEqual(self.rows(config.PROFILE_KIND), [installed['profile']])


if __name__ == '__main__':
    unittest.main()
