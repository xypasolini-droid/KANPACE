"""Evidence survives the real draft pipeline; provenance never grants approval."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import order_drafts
from kanpace.application.store import Store
from kanpace.core.errors import APIError


def draft(source, evidence):
    return {'order_key': 'EVIDENCE-TEST', 'source_revision': '订单 R2',
            'project': {'name': '证据测试', 'quantity': None}, 'sources': [source],
            'parts': [{'name': '待核对板件', 'item_level': 'component',
                       'quantity': None, 'length_mm': None, 'evidence': [evidence]}]}


class EvidenceValidationTests(unittest.TestCase):
    def reference(self):
        source = {'source_path': '/synthetic/drawing.pdf', 'sha256': 'A' * 64,
                  'revision': 'R2', 'pages': 2}
        evidence = {'source_path': source['source_path'], 'page': 1,
                    'locator': {'kind': 'pdf_region', 'page': 1, 'bbox': [10, 20, 50, 60],
                                'page_size_pdf_points': {'width': 200, 'height': 300},
                                'origin': 'top_left', 'rotation': 0},
                    'engine': {'name': 'ocr', 'version': 'test'},
                    'model': {'name': 'test', 'revision': None},
                    'observation_kind': 'inferred', 'review_status': 'approved'}
        return draft(source, evidence)

    def test_normalise_parse_preserves_provenance_and_unknowns(self):
        payload = self.reference()
        normalized = order_drafts.normalise(payload)
        self.assertEqual(normalized, order_drafts.normalise(normalized))
        parsed = order_drafts.parse(normalized, 'draft.json')
        part = parsed['parts'][0]
        ref = part['evidence'][0]
        self.assertEqual(ref['source_sha256'], 'a' * 64)
        self.assertEqual(ref['source_revision'], 'R2')
        self.assertEqual(ref['locator']['bbox'], [10, 20, 50, 60])
        self.assertIsNone(ref['model']['revision'])
        self.assertIsNone(part['quantity'])
        self.assertIsNone(part['length'])
        self.assertEqual(ref['observation_kind'], 'inferred')
        self.assertEqual(ref['review_status'], 'unreviewed')
        self.assertEqual(part['review_status'], 'pending')
        self.assertTrue(part['draft_only'])

    def test_legacy_page_ranges_and_cell_references_remain(self):
        body = draft({'source_path': '/synthetic/file.xlsx'},
                     {'sheet': '清单', 'cell': 'A1:C2', 'row': '1-2', 'quote': '原文字'})
        ref = order_drafts.parse(body, 'draft.json')['parts'][0]['evidence'][0]
        self.assertEqual((ref['cell'], ref['row'], ref['quote']), ('A1:C2', '1-2', '原文字'))

    def test_locator_kinds_do_not_fabricate_coordinates(self):
        locators = [{'kind': 'table_cell', 'sheet': '清单', 'row': 1, 'column': 2},
                    {'kind': 'step_face', 'face_id': 'face-3', 'assembly_path': ['cabinet', 'panel']},
                    {'kind': 'dxf_entity', 'handle': 'A12', 'layer': 'BOM'},
                    {'kind': 'csv_cell', 'row': 1, 'column': 2, 'bbox': None},
                    {'kind': 'json_pointer', 'pointer': '/parts/0/name', 'bbox': None},
                    {'kind': 'text_line', 'line': 1, 'bbox': None}]
        for loc in locators:
            with self.subTest(kind=loc['kind']):
                body = draft({'source_path': '/synthetic/source'},
                             {'source_path': '/synthetic/source', 'locator': loc})
                ref = order_drafts.parse(body, 'draft.json')['parts'][0]['evidence'][0]
                self.assertEqual(ref['locator'], loc)

    def test_invalid_geometry_hash_and_identity_are_rejected(self):
        mutations = [lambda b: b['sources'][0].update(sha256='not-a-hash'),
                     lambda b: b['parts'][0]['evidence'][0].update(source_sha256='b' * 64),
                     lambda b: b['parts'][0]['evidence'][0].update(source_path='/other.pdf'),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(page=0),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(bbox=[0, 0, float('nan'), 1]),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(bbox=[0, 0, 1, float('inf')]),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(bbox=[20, 0, 10, 1]),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(bbox=[0, 0, 201, 1]),
                     lambda b: b['parts'][0]['evidence'][0]['locator'].update(rotation=45)]
        for change in mutations:
            body = self.reference()
            change(body)
            with self.subTest(change=change), self.assertRaises(ValueError):
                order_drafts.normalise(body)

    def test_image_pixels_and_pdf_display_page_remain_distinct(self):
        loc = {'kind': 'image_region', 'page': 1, 'bbox': None, 'bbox_pdf_points': None,
               'page_size_pdf_points': None, 'bbox_pixels': [10, 20, 80, 50],
               'page_size_pixels': [100, 60], 'coordinate_system': 'pixels',
               'canonical_origin': 'top_left', 'origin': 'top_left',
               'coordinate_space': 'original_image_pixels', 'rotation': None,
               'cropbox': None, 'crop_to_page_transform': None}
        body = draft({'source_path': '/synthetic/image.png'}, {'source_path': '/synthetic/image.png', 'locator': loc})
        saved = order_drafts.parse(body, 'draft.json')['parts'][0]['evidence'][0]['locator']
        self.assertEqual(saved, loc)
        self.assertIsNone(saved['bbox_pdf_points'])
        for changed in ({'bbox_pixels': [10, 20, 101, 50]}, {'coordinate_system': 'pdf_points'},
                        {'bbox_pdf_points': [10, 20, 80, 50]}, {'coordinate_space': 'pdf_display_page'},
                        {'bbox_pixels': [10, 20, float('inf'), 50]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                order_drafts.locator(dict(loc, **changed))
        pdf = {'kind': 'pdf_region', 'page': 1, 'bbox_pdf_points': [10, 20, 80, 50],
               'page_size_pdf_points': [200, 100], 'coordinate_system': 'pdf_points',
               'canonical_origin': 'top_left', 'coordinate_space': 'pdf_media_display_page',
               'rotation': 90, 'cropbox': [0, 0, 100, 200], 'mediabox': [0, 0, 100, 200],
               'crop_to_page_transform': None}
        normalized = order_drafts.locator(pdf)
        self.assertEqual(normalized['bbox'], pdf['bbox_pdf_points'])
        self.assertEqual(normalized['page_size_pdf_points'], [200, 100])
        self.assertEqual(normalized['coordinate_space'], 'pdf_media_display_page')
        self.assertEqual(normalized['rotation'], 90)


class RegisteredEvidenceRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, seed=False)
        with self.store.write_transaction() as con:
            self.project = self.store.new_project(con, {'name': '已登记项目', 'quantity': 1})
            content = b'name,material,category,length,width,thickness,quantity,unit\nPanel,Plywood,wood,500,200,18,1,mm\n'
            imported = self.store.import_file(con, {'project_id': self.project['id'], 'filename': 'source.csv',
                                                    'content_base64': base64.b64encode(content).decode()})
            self.document = imported['document']
            self.project = self.store.get(con, 'projects', self.project['id'])

    def tearDown(self):
        self.temp.cleanup()

    def body(self):
        source = {'document_id': self.document['id'], 'source_sha256': self.document['sha256'],
                  'source_revision': self.document['revision'], 'filename': self.document['filename']}
        ref = dict(source, locator={'kind': 'csv_cell', 'row': 2, 'column': 1, 'bbox': None},
                   observation_kind='observed', review_status='approved',
                   engine={'name': 'csv', 'version': 'stdlib'}, model=None)
        body = draft(source, ref)
        body.update(project_id=self.project['id'], expected_revision=self.project['revision'])
        return body

    def test_normalise_parse_store_state_roundtrip_keeps_registered_reference(self):
        normalized = order_drafts.normalise(self.body())
        parsed = order_drafts.parse(normalized, 'draft.json')
        expected = parsed['parts'][0]['evidence'][0]
        with self.store.write_transaction() as con:
            imported = self.store.import_order_draft(con, normalized)
            saved = imported['parts'][0]
            self.assertEqual(saved['review_status'], 'pending')
            self.assertFalse(saved['approved'])
            self.assertEqual(saved['evidence'][0], expected)
            self.assertEqual(saved['source']['document_id'], self.document['id'])
        # Re-open through a fresh Store, so this is persistence, not object aliasing.
        reopened = Store(self.temp.name, seed=False)
        with reopened.read_transaction() as con:
            state = reopened.state(con)
            part = next(p for p in state['parts'] if p['id'] == saved['id'])
            self.assertEqual(part['evidence'][0], expected)
            project = next(p for p in state['projects'] if p['id'] == self.project['id'])
            source = project['order_draft']['sources'][0]
            self.assertEqual(source['document_id'], self.document['id'])
            self.assertEqual(source['source_sha256'], self.document['sha256'])
            self.assertEqual(source['source_revision'], self.document['revision'])
            self.assertEqual(state['tasks'], [])

    def test_cloud_image_region_roundtrip_keeps_native_pixel_frame(self):
        # This is the actual shared worker EvidenceRef shape. No point mapping
        # is invented merely because an image is attached to a draft.
        body = self.body()
        source_id = 'doc:' + self.document['id']
        body['sources'][0]['source_id'] = source_id
        ref = body['parts'][0]['evidence'][0]
        ref.update(source_id=source_id, evidence_id='ev_cloud_fixture', method='docling_full_pipeline',
                   raw_text='原图观察', candidate={'field': None, 'value': '原图观察', 'unit': None},
                   is_manufacturing_dimension=False)
        ref['locator'] = {'kind': 'image_region', 'page': 1, 'bbox': None, 'bbox_pdf_points': None,
                          'page_size_pdf_points': None, 'bbox_pixels': [5, 10, 80, 40],
                          'page_size_pixels': [100, 50], 'coordinate_system': 'pixels',
                          'canonical_origin': 'top_left', 'origin': 'top_left',
                          'coordinate_space': 'original_image_pixels', 'rotation': None,
                          'cropbox': None, 'crop_to_page_transform': None}
        expected = order_drafts.parse(order_drafts.normalise(body), 'draft.json')['parts'][0]['evidence'][0]
        with self.store.write_transaction() as con:
            imported = self.store.import_order_draft(con, body)
            saved = imported['parts'][0]
            self.assertEqual(saved['evidence'][0], expected)
        with Store(self.temp.name, seed=False).read_transaction() as con:
            persisted = self.store.get(con, 'parts', saved['id'])['evidence'][0]
            self.assertEqual(persisted, expected)
            self.assertIsNone(persisted['locator']['bbox_pdf_points'])
            self.assertEqual(persisted['locator']['bbox_pixels'], [5, 10, 80, 40])

    def test_server_rejects_unknown_foreign_stale_or_hash_mismatched_documents(self):
        cases = []
        unknown = self.body()
        unknown['sources'][0]['document_id'] = 'unknown-server-id'
        unknown['parts'][0]['evidence'][0]['document_id'] = 'unknown-server-id'
        cases.append(unknown)
        wrong_hash = self.body()
        wrong_hash['sources'][0]['source_sha256'] = 'b' * 64
        wrong_hash['parts'][0]['evidence'][0]['source_sha256'] = 'b' * 64
        cases.append(wrong_hash)
        stale = self.body()
        stale['expected_revision'] += 1
        cases.append(stale)
        foreign = self.body()
        with self.store.write_transaction() as con:
            other = self.store.new_project(con, {'name': '另项目', 'quantity': 1})
        foreign.update(project_id=other['id'], expected_revision=other['revision'])
        cases.append(foreign)
        stale_document = self.body()
        stale_document['sources'][0]['source_revision'] += 1
        stale_document['parts'][0]['evidence'][0]['source_revision'] += 1
        cases.append(stale_document)
        cases.append(self.body())
        for case_index, body in enumerate(cases):
            if case_index == len(cases) - 1:
                with self.store.write_transaction() as con:
                    current = self.store.get(con, 'documents', self.document['id'])
                    current['superseded'] = True
                    self.store.put(con, 'documents', current)
            with self.store.read_transaction() as con:
                before = [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY kind,id')]
            with self.subTest(body=body), self.assertRaises(APIError):
                with self.store.write_transaction() as con:
                    self.store.import_order_draft(con, body)
            with self.store.read_transaction() as con:
                after = [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY kind,id')]
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
