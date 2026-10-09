"""Native CAD originals can be linked to an explicit, reviewable export."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kanpace.application.store import Store
from kanpace.core.errors import APIError
import engineering_readiness


def one_page_pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R >>',
               b'<< /Length 28 >>\nstream\n0 0 1 RG 20 20 200 100 re S\nendstream']
    data = b'%PDF-1.4\n'; offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 5\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    data += b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'
    return data


class CADCompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, seed=False, empty=True)
        self.con = self.store.connect()
        self.project = self.store.new_project(self.con, {'name': '测试柜', 'client': '测试', 'quantity': 1})
        # These tests isolate original/companion lineage. The staged customer
        # confirmation gate has its own end-to-end coverage.
        self.project['evidence_policy'] = 'legacy_fixture'
        self.store.put(self.con, 'projects', self.project)

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def upload(self, project_id, filename, content, **extra):
        return self.store.import_file(self.con, {
            'project_id': project_id, 'filename': filename,
            'content_base64': base64.b64encode(content).decode(), **extra,
        })['document']

    def bom(self, **extra):
        raw = (b'name,material,category,length,width,thickness,quantity,unit,finish\n'
               b'Panel,Plywood,wood,1200,600,18,2,mm,clear\n')
        result = self.store.import_file(self.con, {
            'project_id': self.project['id'], 'filename': 'cabinet-bom.csv',
            'content_base64': base64.b64encode(raw).decode(), **extra,
        })
        part = result['parts'][0]
        self.store.review_part(self.con, part['id'], {'approved': True})
        return result['document'], self.store.get(self.con, 'parts', part['id'])

    def test_explicit_export_keeps_native_source_identity(self):
        original = self.upload(self.project['id'], 'cabinet.dwg', b'AC1027' + b'x' * 100)
        self.assertEqual(original['status'], 'needs_conversion')
        bom = b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\n'
        companion = self.upload(self.project['id'], 'cabinet-bom.csv', bom,
                                related_document_id=original['id'])
        self.assertEqual(companion['companion_for'], [
            {'document_id': original['id'], 'sha256': original['sha256']}])
        self.assertNotIn('companion_for', original)
        duplicate = self.upload(self.project['id'], 'cabinet-bom-copy.csv', bom,
                                related_document_id=original['id'])
        self.assertEqual(duplicate['id'], companion['id'])
        self.assertEqual(len(self.store.get(self.con, 'documents', companion['id'])['companion_for']), 1)

    def test_other_project_and_unsupported_companion_are_rejected(self):
        original = self.upload(self.project['id'], 'cabinet.sldasm', b'SolidWorks assembly original')
        other = self.store.new_project(self.con, {'name': '另一订单', 'client': '测试', 'quantity': 1})
        with self.assertRaises(APIError):
            self.upload(other['id'], 'wrong.csv', b'name,quantity\nA,1',
                        related_document_id=original['id'])
        with self.assertRaises(APIError):
            self.upload(self.project['id'], 'wrong.obj', b'v 0 0 0\n',
                        related_document_id=original['id'])

    def test_replaced_original_does_not_silently_rebind_export(self):
        original = self.upload(self.project['id'], 'cabinet.dwg', b'AC1027' + b'x' * 100)
        export = self.upload(self.project['id'], 'cabinet.csv', b'name,quantity\nPanel,1\n',
                             related_document_id=original['id'])
        updated = self.upload(self.project['id'], 'cabinet.dwg', b'AC1032' + b'y' * 100)
        self.assertNotEqual(updated['id'], original['id'])
        self.assertTrue(self.store.get(self.con, 'documents', original['id'])['superseded'])
        self.assertEqual(export['companion_for'][0]['sha256'], original['sha256'])
        with self.assertRaises(APIError):
            self.upload(self.project['id'], 'late.csv', b'name,quantity\nNew,1\n',
                        related_document_id=original['id'])

    def test_unrelated_approved_bom_cannot_resolve_native_cad(self):
        unrelated, part = self.bom()
        original = self.upload(self.project['id'], 'different.sldasm', b'unrelated-native-model')
        with self.assertRaises(APIError) as blocked:
            self.store.resolve_document(self.con, original['id'], {'note': '声称已经对照'})
        self.assertEqual(blocked.exception.status, 409)
        self.assertFalse(self.store.get(self.con, 'documents', original['id'])['resolved'])
        self.assertEqual(engineering_readiness.source_resolution_candidates(self.store, self.con, original), [])

    def test_explicit_current_companion_and_approved_parts_can_resolve(self):
        original = self.upload(self.project['id'], 'cabinet.sldasm', b'native-cabinet-v1')
        companion, part = self.bom(related_document_id=original['id'])
        resolved = self.store.resolve_document(self.con, original['id'], {'note': '按配套 BOM 与原装配图逐项核对'})
        self.assertEqual(resolved['verified_part_ids'], [part['id']])
        self.assertEqual(resolved['resolution_evidence']['parts'][0]['source_document_id'], companion['id'])
        self.assertTrue(engineering_readiness.source_resolution_current(self.store, self.con, resolved))
        self.store.generate(self.con, self.project['id'])
        released = self.store.release(self.con, self.project['id'])
        self.assertEqual(released['project']['released_revision'], released['project']['revision'])

    def test_pdf_and_bom_exports_of_same_native_source_can_both_be_reviewed(self):
        original = self.upload(self.project['id'], 'cabinet.sldasm', b'native-cabinet-v1')
        drawing = self.upload(self.project['id'], 'cabinet-engineering.pdf', one_page_pdf(),
                              related_document_id=original['id'])
        _, part = self.bom(related_document_id=original['id'])
        native = self.store.resolve_document(self.con, original['id'], {'note': '原装配图与 BOM 已核对'})
        pdf = self.store.resolve_document(self.con, drawing['id'], {'note': 'PDF 图页与同版 BOM 已核对'})
        self.assertEqual(native['verified_part_ids'], [part['id']])
        self.assertEqual(pdf['verified_part_ids'], [part['id']])
        self.store.generate(self.con, self.project['id'])
        self.store.release(self.con, self.project['id'])
        self.assertTrue(engineering_readiness.source_resolution_current(self.store, self.con, pdf))

    def test_bom_uploaded_first_can_be_explicitly_linked_later(self):
        companion, part = self.bom()
        original = self.upload(self.project['id'], 'cabinet.dwg', b'AC1027' + b'v' * 100)
        with self.assertRaises(APIError):
            self.store.resolve_document(self.con, original['id'], {'note': '尚未建立来源关联'})
        duplicate = self.upload(self.project['id'], 'cabinet-bom.csv',
                                (b'name,material,category,length,width,thickness,quantity,unit,finish\n'
                                 b'Panel,Plywood,wood,1200,600,18,2,mm,clear\n'),
                                related_document_id=original['id'])
        self.assertEqual(duplicate['id'], companion['id'])
        resolved = self.store.resolve_document(self.con, original['id'], {'note': '已关联先上传的配套 BOM'})
        self.assertEqual(resolved['verified_part_ids'], [part['id']])

    def test_replacement_companion_invalidates_prior_source_resolution(self):
        original = self.upload(self.project['id'], 'cabinet.sldasm', b'native-cabinet-v1')
        companion, part = self.bom(related_document_id=original['id'])
        resolved = self.store.resolve_document(self.con, original['id'], {'note': '首版 BOM 已核对'})
        self.assertTrue(engineering_readiness.source_resolution_current(self.store, self.con, resolved))
        changed = (b'name,material,category,length,width,thickness,quantity,unit,finish\n'
                   b'Panel,Plywood,wood,1300,600,18,2,mm,clear\n')
        self.upload(self.project['id'], 'cabinet-bom.csv', changed,
                    related_document_id=original['id'])
        self.assertFalse(engineering_readiness.source_resolution_current(
            self.store, self.con, self.store.get(self.con, 'documents', original['id'])))
        project = self.store.get(self.con, 'projects', self.project['id'])
        blockers = engineering_readiness.release_blockers(self.store, self.con, project,
                                                            engineering_readiness.part_blockers)
        self.assertTrue(any('核验关联已失效' in item for item in blockers))

    def test_approved_part_change_invalidates_prior_source_resolution(self):
        original = self.upload(self.project['id'], 'cabinet.sldasm', b'native-cabinet-v1')
        _, part = self.bom(related_document_id=original['id'])
        resolved = self.store.resolve_document(self.con, original['id'], {'note': '已核对首版尺寸'})
        self.assertTrue(engineering_readiness.source_resolution_current(self.store, self.con, resolved))
        self.store.review_part(self.con, part['id'], {'approved': True, 'edits': {'length': 1300}})
        self.assertFalse(engineering_readiness.source_resolution_current(
            self.store, self.con, self.store.get(self.con, 'documents', original['id'])))

    def test_manually_entered_part_requires_explicit_source_and_review_note(self):
        original = self.upload(self.project['id'], 'cabinet.dwg', b'AC1027' + b'v' * 100)
        data = {'project_id': self.project['id'], 'name': '侧板', 'material': 'Plywood',
                'category': 'wood', 'length': 1200, 'width': 600, 'thickness': 18,
                'quantity': 2, 'finish': 'clear', 'source_document_id': original['id']}
        part = self.store.create_part(self.con, data)
        with self.assertRaises(APIError):
            self.store.review_part(self.con, part['id'], {'approved': True})
        self.store.review_part(self.con, part['id'],
                               {'approved': True, 'review_note': '对照 DWG R1 原图逐项核验'})
        resolved = self.store.resolve_document(self.con, original['id'], {'note': '人工录入完整构件并复核'})
        self.assertEqual(resolved['verified_part_ids'], [part['id']])
        other = self.store.new_project(self.con, {'name': '另一个项目', 'client': '测试', 'quantity': 1})
        with self.assertRaises(APIError):
            self.store.create_part(self.con, {**data, 'project_id': other['id']})


if __name__ == '__main__':
    unittest.main()
