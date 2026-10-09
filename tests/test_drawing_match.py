"""Synthetic STEP/OCR contracts for evidence-only cross-source matching."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drawing_match


def snapshot(*names):
    return {'project_id': 'prj_test', 'job_id': 'eng_cad', 'source_sha256': 'a' * 64,
            'proposals': [{'id': 'sp_' + str(index), 'name': name} for index, name in enumerate(names)]}


def ocr_job(*texts, label='工程图.pdf', job_id='eng_ocr', page=2):
    return {'id': job_id, 'metadata': {'source_label': label, 'source_page': None},
            'source': {'filename': label, 'sha256': 'b' * 64},
            'result': {'pages': [{'page': page, 'width': 1000, 'height': 700, 'regions': [
                {'text': text, 'bbox': [10, index * 30, 200, index * 30 + 20],
                 'score': .97, 'coordinate_system': 'pixels_top_left'}
                for index, text in enumerate(texts)]}]}}


class DrawingMatchTests(unittest.TestCase):
    def test_exact_name_with_dimensions_retains_region_not_manufacturing_fields(self):
        result = drawing_match.build(snapshot('玻璃侧板'), [ocr_job('玻璃侧板 600×450×8mm')])
        row = result['matches'][0]
        self.assertEqual(row['match_status'], 'matched')
        evidence = row['drawing_evidence'][0]
        self.assertEqual((evidence['source_page'], evidence['region_index'], evidence['bbox']),
                         (2, 0, [10.0, 0.0, 200.0, 20.0]))
        self.assertEqual(evidence['dimension_candidates'][0]['values'], [600.0, 450.0, 8.0])
        self.assertEqual(evidence['dimension_candidates'][0]['unit'], 'mm')
        self.assertEqual((evidence['page_width'], evidence['page_height']), (1000, 700))
        self.assertNotIn('manufacturing_dimensions', row)
        self.assertFalse(result['manufacturing_release'])

    def test_generic_and_substring_names_do_not_link(self):
        result = drawing_match.build(snapshot('侧板', '玻璃侧板'),
                                     [ocr_job('侧板 600x450x18', '玻璃侧板加强件 600x450x8')])
        self.assertEqual([row['match_status'] for row in result['matches']], ['generic_name', 'unmatched'])
        self.assertTrue(all(not row['drawing_evidence'] for row in result['matches']))

    def test_exact_part_number_can_join_but_mismatched_named_part_is_conflict(self):
        result = drawing_match.build(snapshot('A-01', 'B-02 左侧板'),
                                     [ocr_job('A-01 开门铰接件', 'B-02 右侧板')])
        self.assertEqual(result['matches'][0]['match_status'], 'matched')
        self.assertEqual(result['matches'][0]['drawing_evidence'][0]['match_method'], 'exact_part_number')
        self.assertEqual(result['matches'][1]['match_status'], 'conflict')
        self.assertFalse(result['matches'][1]['drawing_evidence'])
        self.assertEqual(result['matches'][1]['conflicting_drawing_evidence'][0]['region_index'], 1)

    def test_different_dimension_annotations_conflict_without_deciding_size(self):
        result = drawing_match.build(snapshot('柜体左侧板'),
                                     [ocr_job('柜体左侧板 600x450x18mm', '柜体左侧板 620x450x18mm')])
        row = result['matches'][0]
        self.assertEqual(row['match_status'], 'conflict')
        self.assertEqual(len(row['drawing_evidence']), 2)

    def test_same_part_number_two_different_part_names_is_conflict(self):
        result = drawing_match.build(snapshot('L-01'),
                                     [ocr_job('L-01 左侧板', 'L-01 右侧板')])
        row = result['matches'][0]
        self.assertEqual(row['match_status'], 'conflict')
        self.assertEqual(len(row['drawing_evidence']), 2)
        self.assertTrue(any('多个不同构件名称' in issue for issue in row['issues']))

    def test_one_region_matching_two_step_definitions_is_ambiguous(self):
        result = drawing_match.build(snapshot('柜体左侧板', '柜体左侧板'), [ocr_job('柜体左侧板')])
        self.assertEqual([row['match_status'] for row in result['matches']], ['ambiguous', 'ambiguous'])

    def test_render_label_excluded_and_cached_page_keeps_original_page(self):
        original = ocr_job('柜体左侧板', label='施工图 P-07.pdf')
        original['result']['pages'][0]['source_page'] = 7
        render = ocr_job('柜体左侧板', label='展柜效果图.jpg', job_id='eng_render')
        result = drawing_match.build(snapshot('柜体左侧板'), [original, render])
        row = result['matches'][0]
        self.assertEqual(len(row['drawing_evidence']), 1)
        self.assertEqual(row['drawing_evidence'][0]['source_page'], 7)

    def test_repeated_identity_fanout_has_explicit_limit(self):
        with self.assertRaisesRegex(ValueError, '候选过多'):
            drawing_match.build(snapshot(*(['柜体左侧板'] * 101)),
                                [ocr_job(*(['柜体左侧板'] * 200))])


if __name__ == '__main__':
    unittest.main()
