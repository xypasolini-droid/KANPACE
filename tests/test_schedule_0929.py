"""Simulated order-schedule imports; every store is temporary, never live data."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import schedule_reference as ref
from test_schedule_reference import order, serial, worksheet, xlsx


class SimulatedSeptemberScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)

    def tearDown(self):
        self.temp.cleanup()

    def _upload(self, filename, content):
        with self.store.connect() as con:
            return ref.import_reference(self.store, con, {
                'filename': filename, 'content_base64': base64.b64encode(content).decode()})

    def _source(self, *, wood='2026-09-24', filename='模拟测试-排程20260929.xlsx', sheet='0929'):
        row = order(**{'客户名称': '模拟客户', '店铺信息': '模拟测试-演示展柜店',
                       '单号': 'SIM-DEMO-0001', '备注': '模拟测试，不代表真实工期',
                       '下单日期': ('serial', serial('2026-09-20')),
                       '拆单日期': ('serial', serial('2026-09-21')),
                       '木作': wood, '油漆': '2026-09-25', '五金': '2026-09-24',
                       '外协': '2026-09-25', '安装': '2026-09-26', '包装': '2026-09-28',
                       '出货时间': '2026-09-29'})
        return filename, xlsx([(sheet, worksheet({4: row}))])

    def test_excel_typed_utc_midnight_is_a_date(self):
        self.assertEqual(ref.full_date('2026-09-29T00:00:00.000Z'), '2026-09-29')
        self.assertIsNone(ref.full_date('2026-09-29T15:30:00.000Z'))
        filename, content = self._source(wood=('date', '2026-09-24T00:00:00.000Z'))
        book = ref.parse_workbook(filename, content, 'typed-date')
        self.assertEqual(book['sheets'][0]['rows'][0]['nodes']['wood']['date'], '2026-09-24')

    def test_legacy_xls_keeps_original_bytes_and_same_upload_is_duplicate(self):
        original = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'simulated legacy workbook bytes'
        _, converted = self._source()
        with patch.object(ref, 'convert_legacy_xls', return_value=converted) as converter:
            first = self._upload('模拟测试-排程20260929.xls', original)
            second = self._upload('模拟测试-排程20260929.xls', original)
        self.assertFalse(first['duplicate'])
        self.assertTrue(second['duplicate'])
        converter.assert_called_once_with(original)
        with self.store.connect() as con:
            source = ref.get_source(self.store, con, first['source']['id'])
            self.assertEqual(ref.registered_path(self.store, source, 'original_file').read_bytes(), original)
            self.assertEqual(len(self.store.all(con, ref.KIND)), 1)

    def test_simulated_order_matches_project_images_and_new_upload_needs_selected_replace(self):
        with self.store.connect() as con:
            project = self.store.new_project(con, {'name': '模拟测试-演示展柜店'})
            self.store.put(con, 'documents', {'id': 'doc_simulated_render', 'project_id': project['id'],
                'purpose': 'render', 'render_scope': 'project', 'filename': '模拟效果图.png',
                'image_url': '/api/documents/doc_simulated_render/image', 'created_at': '2026-09-29T10:00:00Z'})
            self.store.put(con, 'documents', {'id': 'doc_simulated_drawing', 'project_id': project['id'],
                'purpose': 'drawing', 'format': 'PDF', 'filename': '模拟施工图.pdf',
                'created_at': '2026-09-29T10:00:00Z'})
        filename, content = self._source()
        first = self._upload(filename, content)
        with self.store.connect() as con:
            grid = ref.get_references(self.store, con, first['source']['id'])
            initial = grid['working']['orders'][0]
            self.assertEqual((initial['project_id'], initial['match_status']), (project['id'], 'matched'))
            self.assertEqual(initial['project']['render_image_url'], '/api/documents/doc_simulated_render/image')
            self.assertEqual(initial['project']['drawing_name'], '模拟施工图.pdf')
            self.assertEqual(next(n for n in initial['nodes'] if n['id'] == 'wood')['milestone_date'], '2026-09-24')
        self.assertTrue(self._upload(filename, content)['duplicate'])
        updated_filename, updated_content = self._source(wood='2026-09-25')
        latest = self._upload(updated_filename, updated_content)
        self.assertEqual(latest['source']['snapshot_version'], 2)
        with self.store.connect() as con:
            old = ref.get_references(self.store, con, first['source']['id'])['working']
            self.assertEqual(next(n for n in old['orders'][0]['nodes'] if n['id'] == 'wood')['milestone_date'], '2026-09-24')
            request = {'source_id': old['source_id'], 'sheet': old['sheet'], 'expected_version': old['version'],
                       'incoming_source_id': latest['source']['id'], 'incoming_sheet': old['sheet']}
            preview = ref.replacement_preview(self.store, con, request)
            self.assertTrue(preview['rows'][0]['selectable'])
            replaced = ref.replace_working(self.store, con, {**request,
                'selected_order_keys': [old['orders'][0]['key']]})['working']
            after = replaced['orders'][0]
            self.assertEqual(after['project_id'], project['id'])
            self.assertEqual(next(n for n in after['nodes'] if n['id'] == 'wood')['milestone_date'], '2026-09-25')
            self.assertFalse(after['confirmed'])
            self.assertEqual(len(self.store.all(con, ref.KIND)), 2)


if __name__ == '__main__':
    unittest.main()
