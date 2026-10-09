"""Actual OOXML ZIP cells and security boundaries, no Excel application needed."""
import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app
import document_recognition as recognition
import order_drafts


def xlsx_bytes(extra=None, external=False, worksheet=None):
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="柜体&amp;符号" sheetId="1" r:id="r1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"' + (' TargetMode="External"' if external else '') + '/></Relationships>',
        'xl/sharedStrings.xml': '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>600×</t></r><r><t>450 ±0.5</t></r></si></sst>',
        'xl/worksheets/sheet1.xml': worksheet or '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>左&amp;右\n说明</t></is></c></row><row r="3"><c r="C3"><v>001.2300</v></c><c r="D3"><f>SUM(C3:C8)</f><v>999</v></c><c r="E3" t="b"><v>0</v></c></row></sheetData><mergeCells><mergeCell ref="A1:A2"/></mergeCells></worksheet>'}
    if extra: parts.update(extra)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items(): archive.writestr(name, text)
    return output.getvalue()


class XLSXRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'source.xlsx'
        self.source = {'source_id': 'doc:sheet', 'document_id': 'sheet', 'filename': '清单.xlsx', 'source_sha256': 'a' * 64, 'source_revision': 1, 'source_role': 'order'}
        self.options = {'parser': 'native', 'pages': None, 'max_pages': 20}
    def tearDown(self): self.temp.cleanup()
    def test_real_shared_inline_rich_strings_merges_formula_and_literal_number(self):
        self.path.write_bytes(xlsx_bytes())
        result = recognition.parse(self.path, self.source, self.options)
        cells = {r['locator']['cell']: r for r in result['evidence_refs']}
        self.assertEqual(cells['A1']['raw_text'], '600×450 ±0.5')
        self.assertEqual(cells['B1']['raw_text'], '左&右\n说明')
        self.assertEqual(cells['C3']['candidate']['value'], '001.2300')
        self.assertEqual(cells['D3']['raw_text'], '=SUM(C3:C8)'); self.assertIsNone(cells['D3']['candidate']['value'])
        self.assertFalse(cells['E3']['candidate']['value'])
        self.assertEqual(result['tables'][0]['cells'][0]['row_span'], 2)
        self.assertIsNone(cells['A1']['locator']['page']); self.assertIsNone(cells['A1']['locator']['bbox_pdf_points'])
        self.assertEqual(order_drafts.evidence(cells['A1'])['locator']['sheet'], '柜体&符号')
        self.assertTrue(any(i['code'] == 'formula_not_evaluated' for i in result['issues']))
    def test_unsafe_archives_entities_external_rels_and_duplicate_cells_rejected(self):
        bad = [xlsx_bytes(extra={'../escape.xml': '<x/>'}), xlsx_bytes(external=True),
               xlsx_bytes(extra={'xl/vbaProject.bin': 'macro'}),
               xlsx_bytes(extra={'xl/sharedStrings.xml': '<!DOCTYPE s [<!ENTITY x "bad">]><s>&x;</s>'}),
               xlsx_bytes(worksheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row></sheetData></worksheet>')]
        for raw in bad:
            self.path.write_bytes(raw)
            with self.assertRaises(recognition.RecognitionError): recognition.parse(self.path, self.source, self.options)
        self.path.write_bytes(xlsx_bytes())
        with self.assertRaises(recognition.RecognitionError): recognition.parse(self.path, self.source, {**self.options, 'pages': [1]})
    def test_real_registered_xlsx_is_discoverable_and_no_fabricated_geometry(self):
        store = app.Store(Path(self.temp.name) / 'factory', seed=False)
        with store.write_transaction() as con:
            project = store.new_project(con, {'name': 'XLSX识别'})
            uploaded = store.import_file(con, {'project_id': project['id'], 'filename': '真实清单.xlsx', 'content_base64': base64.b64encode(xlsx_bytes()).decode()})
        with store.read_transaction() as con:
            source = next(s for s in recognition.sources(store, con, project['id']) if s['document_id'] == uploaded['document']['id'])
        self.assertEqual(source['format'], 'xlsx')
        self.assertIn('xlsx', recognition.capabilities()['native_text']['formats'])

    def test_external_hyperlinks_keep_cell_text_without_network_or_destination_evidence(self):
        worksheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                     '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>包装要求：防震</t></is></c>'
                     '<c r="B1" t="inlineStr"><is><t>保持原文字</t></is></c></row></sheetData>'
                     '<hyperlinks><hyperlink ref="A1" r:id="h1"/><hyperlink ref="B1" r:id="h2"/></hyperlinks></worksheet>')
        relationships = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="h1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                         'Target="https://example.invalid/never-follow" TargetMode="External"/>'
                         '<Relationship Id="h2" Type="http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink" '
                         'Target="file:///nonexistent/never-read.txt" TargetMode="External"/></Relationships>')
        self.path.write_bytes(xlsx_bytes(worksheet=worksheet, extra={'xl/worksheets/_rels/sheet1.xml.rels': relationships}))
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as urlopen, \
                patch('socket.create_connection', side_effect=AssertionError('network forbidden')) as connect, \
                patch.object(recognition, '_service_request', side_effect=AssertionError('remote parser forbidden')) as remote:
            result = recognition.parse(self.path, self.source, self.options)
        urlopen.assert_not_called(); connect.assert_not_called(); remote.assert_not_called()
        self.assertEqual([ref['raw_text'] for ref in result['evidence_refs']], ['包装要求：防震', '保持原文字'])
        self.assertEqual([ref['locator']['cell'] for ref in result['evidence_refs']], ['A1', 'B1'])
        self.assertEqual(result['issues'], [{'code': 'external_hyperlink_ignored',
                         'relationship_part': 'xl/worksheets/_rels/sheet1.xml.rels', 'count': 2,
                         'message': '外部超链接目标已忽略且未访问；只保留原单元格显示文字，不作为外部依据'}])
        self.assertEqual(result['completeness'], 'observed')
        encoded = str(result)
        self.assertNotIn('example.invalid', encoded)
        self.assertNotIn('never-read.txt', encoded)

    def test_other_external_relationships_and_hyperlink_lookalikes_stay_rejected(self):
        prefix = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        types = [prefix + suffix for suffix in ('externalLink', 'externalLinkPath', 'image', 'oleObject', 'worksheet')]
        types += ['https://example.invalid/relationships/hyperlink', prefix + 'hyperlink/extra']
        for relationship_type in types:
            with self.subTest(relationship_type=relationship_type):
                rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="h1" Type="' + prefix + 'hyperlink" Target="https://example.invalid/ignored" TargetMode="External"/>'
                        '<Relationship Id="bad" Type="' + relationship_type + '" Target="https://example.invalid/not-read" TargetMode="External"/></Relationships>')
                self.path.write_bytes(xlsx_bytes(extra={'xl/worksheets/_rels/sheet1.xml.rels': rels}))
                with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network:
                    with self.assertRaises(recognition.RecognitionError) as caught:
                        recognition.parse(self.path, self.source, self.options)
                network.assert_not_called()
                self.assertEqual(caught.exception.status, 422)
                self.assertIn('外部关系', str(caught.exception))

    def test_external_hyperlink_with_nonstandard_relationship_namespace_is_rejected(self):
        rels = ('<Relationships xmlns="urn:not-ooxml"><Relationship Id="h1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                'Target="https://example.invalid/ignored" TargetMode="External"/></Relationships>')
        self.path.write_bytes(xlsx_bytes(extra={'xl/worksheets/_rels/sheet1.xml.rels': rels}))
        with self.assertRaises(recognition.RecognitionError):
            recognition.parse(self.path, self.source, self.options)


if __name__ == '__main__': unittest.main()
