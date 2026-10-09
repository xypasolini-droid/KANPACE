"""Review-only STEP grouping rules, independent of an optional OCP install."""
import sys
import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cad_split_proposals


def job():
    return {'id':'eng_' + 'a'*32, 'kind':'cad', 'status':'completed',
            'metadata':{'project_id':'p1'}, 'source':{'sha256':'a'*64},
            'result':{'format':'STEP', 'output_length_unit':'mm', 'parts':[
                {'definition_id':'0:1:4', 'instance_path':'0:1:1/0:1:2', 'name':' Panel-A ',
                 'valid':True,'solid_count':1,'bbox_extents_mm':[600,450,18],
                 'oriented_bbox_extents_mm':[18,450,600],
                 'geometry_form_candidate':{'kind':'thin_plate_shape','thinness_ratio':0.04,
                                            'basis':'oriented_bbox','review_required':True}},
                {'definition_id':'0:1:4', 'instance_path':'0:1:1/0:1:3', 'name':'Panel-A',
                 'valid':True,'solid_count':1,'bbox_extents_mm':[450,600,18],
                 'oriented_bbox_extents_mm':[18,450,600]},
                {'definition_id':'0:1:4', 'instance_path':'0:1:1/0:1:4', 'name':'右侧板',
                 'valid':True,'solid_count':1,'bbox_extents_mm':[600,450,18]},
            ]}}


class STEPProposalRules(unittest.TestCase):
    def test_same_definition_different_name_stays_separate_and_bbox_is_reference(self):
        result = cad_split_proposals.build(job())
        self.assertEqual(result['status'],'needs_review')
        self.assertFalse(result['manufacturing_release'])
        self.assertEqual(len(result['proposals']),2)
        panel = next(p for p in result['proposals'] if p['name']=='Panel-A')
        right = next(p for p in result['proposals'] if p['name']=='右侧板')
        self.assertEqual(panel['instance_indices'],[0,1])
        self.assertEqual(panel['suggested_quantity'],2)
        self.assertEqual(right['suggested_quantity'],1)
        self.assertEqual(panel['bbox_extents_mm_sample'],[600.,450.,18.])
        self.assertEqual(panel['oriented_bbox_extents_mm_sample'],[18.,450.,600.])
        self.assertEqual(panel['oriented_bbox_extents_mm_samples'],[[18.,450.,600.]])
        self.assertEqual(panel['geometry_form_candidate_count'],1)
        self.assertEqual(panel['geometry_form_candidates'][0]['instance_index'],0)
        self.assertIsNone(right['oriented_bbox_extents_mm_sample'])
        self.assertEqual(right['geometry_form_candidates'],[])
        self.assertIsNone(panel['manufacturing_dimensions'])
        self.assertIsNone(panel['material'])
        self.assertTrue(any('轴向外包尺寸不同' in x for x in panel['issues']))
        self.assertEqual(cad_split_proposals.build(job())['proposals'],result['proposals'])
        self.assertEqual(cad_split_proposals.selected(result,panel['id'],[0,1])['id'],panel['id'])
        for indices in ([0], [1,0], [0,1,2], [0,True]):
            with self.assertRaises(ValueError):
                cad_split_proposals.selected(result,panel['id'],indices)

    def test_malformed_or_incomplete_job_cannot_produce_candidates(self):
        for changed in ({'status':'running'}, {'kind':'ocr'}, {'source':{'sha256':'wrong'}},
                        {'result':{'format':'STEP','output_length_unit':'drawing','parts':[]}}):
            bad=job();bad.update(changed)
            with self.assertRaises(ValueError): cad_split_proposals.build(bad)
        duplicate=job()
        duplicate['result']['parts'][1]['instance_path']=duplicate['result']['parts'][0]['instance_path']
        with self.assertRaises(ValueError): cad_split_proposals.build(duplicate)

    def test_long_distinct_names_cannot_merge_by_truncation(self):
        model = job()
        prefix = '侧板' * 82
        model['result']['parts'][0]['name'] = prefix + '左'
        model['result']['parts'][1]['name'] = prefix + '右'
        result = cad_split_proposals.build(model)
        self.assertEqual(len(result['proposals']), 3)
        self.assertEqual(len({p['id'] for p in result['proposals']}), 3)
        model['result']['parts'][0]['name'] = '超' * 501
        with self.assertRaises(ValueError): cad_split_proposals.build(model)

    def test_optional_geometry_hints_are_bounded_and_never_manufacturing_values(self):
        model = job()
        template = model['result']['parts'][0]
        for index in range(2, 8):
            instance = dict(template, instance_path=f'0:1:1/0:1:{index + 8}',
                            oriented_bbox_extents_mm=[18, 450 + index, 600],
                            geometry_form_candidate={'kind':'thin_plate_shape', 'basis':'oriented_bbox',
                                                     'thinness_ratio':0.03, 'review_required':True})
            model['result']['parts'].append(instance)
        model['result']['parts'][1]['oriented_bbox_extents_mm'] = [float('nan'), 450, 600]
        model['result']['parts'][1]['geometry_form_candidate'] = {'kind':'thin_plate_shape',
                                      'basis':'oriented_bbox','thinness_ratio':'0.03','review_required':True}
        result = cad_split_proposals.build(model)
        panel = next(p for p in result['proposals'] if p['name'] == 'Panel-A')
        self.assertEqual(len(panel['oriented_bbox_extents_mm_samples']),4)
        self.assertEqual(len(panel['geometry_form_candidates']),4)
        self.assertEqual(panel['geometry_form_candidate_count'],7)
        self.assertIsNone(panel['manufacturing_dimensions'])

    def test_source_units_are_only_confirmed_when_known_and_consistent(self):
        model = job()
        model['result']['source_length_units'] = ['  MILLIMETRE  ', 'mm']
        known = cad_split_proposals.build(model)
        self.assertEqual(known['source_length_units'], ['mm'])
        self.assertTrue(known['units_confirmed'])
        model['result']['source_length_units'] = ['MM', 'INCH']
        mixed = cad_split_proposals.build(model)
        self.assertEqual(mixed['source_length_units'], ['mm', 'inch'])
        self.assertFalse(mixed['units_confirmed'])
        self.assertTrue(any('源长度单位' in issue for issue in mixed['proposals'][0]['issues']))
        model['result']['source_length_units'] = ['MM', '<script>']
        unrecognized = cad_split_proposals.build(model)
        self.assertEqual(unrecognized['source_length_units'], ['mm'])
        self.assertFalse(unrecognized['units_confirmed'])
        model['result']['source_length_units'] = []
        absent = cad_split_proposals.build(model)
        self.assertEqual(absent['source_length_units'], [])
        self.assertFalse(absent['units_confirmed'])
        self.assertIsNone(absent['proposals'][0]['manufacturing_dimensions'])

    def test_nested_assemblies_preserve_per_instance_cabinet_context_without_changing_id(self):
        model = job()
        model['result']['parts'] = [
            dict(model['result']['parts'][0], instance_path='root/left/body/panel1', name='通用侧板'),
            dict(model['result']['parts'][0], instance_path='root/right/body/panel2', name='通用侧板'),
        ]
        baseline = cad_split_proposals.build(model)['proposals'][0]
        model['result']['assemblies'] = [
            {'instance_path': 'root', 'definition_id': 'ass:root', 'name': '总装'},
            {'instance_path': 'root/left', 'definition_id': 'ass:cabinet', 'name': '一号柜'},
            {'instance_path': 'root/left/body', 'definition_id': 'ass:body', 'name': '柜身'},
            {'instance_path': 'root/right', 'definition_id': 'ass:cabinet', 'name': '二号柜'},
            {'instance_path': 'root/right/body', 'definition_id': 'ass:body', 'name': '柜身'},
        ]
        proposal = cad_split_proposals.build(model)['proposals'][0]
        self.assertEqual(proposal['id'], baseline['id'])
        self.assertEqual(proposal['instance_indices'], [0, 1])
        self.assertEqual(proposal['suggested_quantity'], 2)
        contexts = proposal['assembly_contexts']
        self.assertEqual([item['instance_path'] for item in contexts],
                         ['root/left/body/panel1', 'root/right/body/panel2'])
        self.assertEqual([item['nearest_parent']['instance_path'] for item in contexts],
                         ['root/left/body', 'root/right/body'])
        self.assertEqual([[node['name'] for node in item['ancestors']] for item in contexts],
                         [['总装', '一号柜', '柜身'], ['总装', '二号柜', '柜身']])
        self.assertEqual([item['unresolved_parent_paths'] for item in contexts], [[], []])
        self.assertTrue(any('跨多个上级装配' in issue for issue in proposal['issues']))
        self.assertIsNone(proposal['material'])
        self.assertIsNone(proposal['manufacturing_dimensions'])

    def test_missing_assembly_nodes_are_explicit_and_never_inferred_from_path(self):
        model = job()
        model['result']['parts'] = [
            dict(model['result']['parts'][0], instance_path='root/cabinet/panel1')]
        model['result']['assemblies'] = [
            {'instance_path': 'root', 'definition_id': 'ass:root', 'name': '总装'}]
        proposal = cad_split_proposals.build(model)['proposals'][0]
        context = proposal['assembly_contexts'][0]
        self.assertEqual([node['name'] for node in context['ancestors']], ['总装'])
        self.assertIsNone(context['nearest_parent'])
        self.assertEqual(context['unresolved_parent_paths'], ['root/cabinet'])
        self.assertTrue(any('缺少上级装配记录' in issue for issue in proposal['issues']))
        duplicate = job()
        duplicate['result']['assemblies'] = [
            {'instance_path': 'root', 'definition_id': 'ass:root', 'name': '总装'},
            {'instance_path': 'root', 'definition_id': 'ass:root', 'name': '总装'}]
        with self.assertRaises(ValueError): cad_split_proposals.build(duplicate)

    @unittest.skipUnless(importlib.util.find_spec('OCP'), 'native OCP runtime unavailable')
    def test_native_step_fixture_flows_into_review_only_proposals(self):
        from engineering_engines import _run_cad
        from tests.test_engineering_engines import step_fixture
        with tempfile.TemporaryDirectory() as temporary:
            path = step_fixture(Path(temporary), instance_name='右侧板')
            result = _run_cad(path, {}, lambda *_: None)
            completed = {'id': 'eng_' + '1' * 32, 'kind': 'cad', 'status': 'completed',
                         'metadata': {'project_id': 'fixture'},
                         'source': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                         'result': result}
            snapshot = cad_split_proposals.build(completed)
            self.assertEqual(result['instance_count'], 2)
            self.assertEqual(len(snapshot['proposals']), 2)
            self.assertEqual({p['name'] for p in snapshot['proposals']}, {'Panel-A', '右侧板'})
            self.assertTrue(all(p['suggested_quantity'] == 1 for p in snapshot['proposals']))
            self.assertTrue(all(p['manufacturing_dimensions'] is None for p in snapshot['proposals']))
            self.assertTrue(all(p['oriented_bbox_extents_mm_sample'] is not None for p in snapshot['proposals']))
            self.assertFalse(snapshot['manufacturing_release'])
            self.assertEqual(snapshot['source_length_units'], ['mm'])
            self.assertTrue(snapshot['units_confirmed'])


if __name__ == '__main__': unittest.main()
