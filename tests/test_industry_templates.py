"""Reference catalog checks; no live store, external site, or hardware mutation."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import industry_templates as templates
import operations as ops


class IndustryTemplateTests(unittest.TestCase):
    def routes(self):
        return [templates.resolve(industry['id'], variant['id'])
                for industry in templates.catalog() for variant in industry['variants']]

    def test_all_researched_industries_have_executable_separate_routes(self):
        research = json.loads((templates.CATALOG_PATH.parents[1] / 'static/industry-map/industries.json').read_text())
        actual = templates.catalog()
        self.assertEqual({item['id'] for item in actual}, {item['id'] for item in research})
        self.assertEqual(len(actual), 19)
        self.assertEqual(len(self.routes()), 30)
        identifiers = set()
        for route in self.routes():
            with self.subTest(route=route['id']):
                self.assertNotIn(route['id'], identifiers)
                identifiers.add(route['id'])
                nodes = ops.validate_nodes(None, None, route['nodes'], publishing=True)
                ops.validate_object_fields(route['object_fields'])
                self.assertEqual(len(ops.dag_order(nodes)), len(nodes))
                self.assertTrue(any(node['quality_gate'] for node in nodes))
                self.assertTrue(all(node['estimated_minutes'] is None for node in nodes))
                self.assertTrue(all(node['workcenter_id'] is None for node in nodes))
                self.assertTrue(all(node['instructions'] and node['start_checks'] and node['acceptance'] for node in nodes))
                self.assertTrue(route['requires_review'])
                self.assertEqual(route['status'], 'reference')
                self.assertIn(route['factory_type'], ops.FACTORY_TYPES)
                self.assertIn('engineering', route['source_requirements'])
                self.assertTrue(set(route['source_requirements']) <= {'engineering','bom','render','acceptance','schedule','people'})
                self.assertNotIn('拍摄', json.dumps(route, ensure_ascii=False))

    def test_sources_and_content_hash_travel_with_each_route(self):
        source = {i['id']: i for i in json.loads((templates.CATALOG_PATH.parents[1] / 'static/industry-map/industries.json').read_text())}
        for route in self.routes():
            expected_urls = {s['url'] for s in source[route['industry_id']]['sources']}
            self.assertEqual({s['url'] for s in route['sources']}, expected_urls)
            self.assertTrue(all(s['title'] and s['url'].startswith('https://') for s in route['sources']))
            self.assertEqual(route['research_date'], '2026-09-07')
            self.assertEqual(len(route['content_hash']), 64)
            self.assertEqual(route['content_hash'], route['hash'])
            repeated = templates.resolve(route['industry_id'], route['variant_id'])
            self.assertEqual(route['content_hash'], repeated['content_hash'])
            content = {k:v for k,v in route.items() if k not in ('content_hash','hash')}
            self.assertEqual(templates._digest(content), route['content_hash'])

    def test_callers_cannot_change_shared_catalog_or_another_resolved_route(self):
        reference = templates.resolve('rattan', 'iron_wood_rattan')
        original_hash = reference['content_hash']
        reference['nodes'][0]['name'] = 'Customer private instruction'
        reference['sources'].clear()
        catalog = templates.catalog()
        catalog[0]['variants'][0]['name'] = 'Private factory name'
        self.assertEqual(templates.resolve('rattan', 'iron_wood_rattan')['content_hash'], original_hash)
        self.assertNotEqual(templates.catalog()[0]['variants'][0]['name'], 'Private factory name')
        with self.assertRaises(ValueError):
            templates.resolve('../customer-data')
        with self.assertRaises(ValueError):
            templates.resolve('rattan', 'missing')
        with self.assertRaises(ValueError):
            templates.resolve('rattan', '')

    def test_rattan_merges_only_its_finished_product_material_branches(self):
        composite = templates.resolve('rattan', 'iron_wood_rattan')
        by_id = {n['id']: n for n in composite['nodes']}
        self.assertEqual(composite['object_label'], '成品批次')
        self.assertEqual(composite['object_unit'], '批')
        self.assertEqual(set(by_id['kit']['predecessors']), {'metal_surface','wood_finish','fiber'})
        self.assertEqual(by_id['metal']['predecessors'], ['sample'])
        self.assertEqual(by_id['wood']['predecessors'], ['sample'])
        self.assertEqual(by_id['fiber']['predecessors'], ['sample'])
        iron_only = {n['id'] for n in templates.resolve('rattan','iron_rattan')['nodes']}
        wood_only = {n['id'] for n in templates.resolve('rattan','wood')['nodes']}
        self.assertFalse({'wood','wood_finish'} & iron_only)
        self.assertFalse({'metal','metal_surface','fiber'} & wood_only)
        self.assertIn('木件', by_id['wood']['acceptance'][0])

    def test_alternative_factory_boundaries_do_not_turn_into_parallel_branches(self):
        chosen = {
            'stone': {'board', 'carving'},
            'textile': {'integrated', 'incoming_dye'},
            'food': {'powder', 'bakery', 'beverage'},
            'tea': {'initial', 'refining', 'packing'},
            'hygiene': {'tissue_converting', 'sanitary_converting'},
            'chip': {'wafer', 'pack_test'},
            'petro': {'maintenance', 'continuous_boundary'},
        }
        catalog = {i['id']: i for i in templates.catalog()}
        for industry, variants in chosen.items():
            self.assertEqual({v['id'] for v in catalog[industry]['variants']}, variants)
            hashes = {templates.resolve(industry,v)['content_hash'] for v in variants}
            self.assertEqual(len(hashes),len(variants))
        tea_pack = {n['id'] for n in templates.resolve('tea','packing')['nodes']}
        self.assertFalse({'leaf','process','blend','sort'} & tea_pack)
        incoming = {n['id'] for n in templates.resolve('textile','incoming_dye')['nodes']}
        self.assertNotIn('yarn', incoming)
        bakery = {n['id'] for n in templates.resolve('food','bakery')['nodes']}
        beverage = {n['id'] for n in templates.resolve('food','beverage')['nodes']}
        self.assertIn('bake', bakery)
        self.assertNotIn('bake', beverage)

    def test_process_and_controlled_industries_are_explicit_coordination_scopes(self):
        for industry, variants in (('chip',['wafer','pack_test']),('petro',['maintenance','continuous_boundary'])):
            for variant in variants:
                route = templates.resolve(industry, variant)
                self.assertEqual(route['scope'], 'controlled_system_handoff')
                self.assertIn('主责', json.dumps(route['nodes'], ensure_ascii=False))
                self.assertTrue(all(n['estimated_minutes'] is None for n in route['nodes']))
        for industry in ('tiles','paper'):
            self.assertEqual(templates.resolve(industry)['scope'], 'continuous_coordination')
        petro = templates.resolve('petro','maintenance')
        by_id = {n['id']:n for n in petro['nodes']}
        self.assertEqual(set(by_id['permit']['predecessors']), {'docs','spares','crew'})
        self.assertEqual(by_id['work']['predecessors'], ['permit'])
        self.assertIn('不审批', by_id['permit']['instructions'])

    def test_batch_count_and_physical_measurement_are_not_conflated(self):
        for route in self.routes():
            self.assertNotIn(route['object_unit'], ('kg','m²','m','吨','米','千克'))
            for field in route['object_fields']:
                self.assertNotIn('value',field)
                if field['type'] == 'decimal':
                    self.assertTrue(field['unit'])
                    self.assertFalse(field['required'])
            self.assertIn('不自动换算', route['measurement_note'])
            self.assertLessEqual(len(route['object_fields']),5)
        weight = next(f for f in templates.resolve('textile','incoming_dye')['object_fields'] if f['id']=='weight_kg')
        self.assertEqual(weight['type'],'decimal')
        self.assertEqual(weight['unit'],'kg')


if __name__ == '__main__':
    unittest.main()
