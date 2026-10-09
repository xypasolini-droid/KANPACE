"""Project isolation, evidence selection and real JPEG preparation for badges."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, PngImagePlugin
import badge_media as badge
from upload_preview import executable


class Store:
    def __init__(self, root):
        self.data_dir = root
        self.entities = {'projects': [{'id': 'p', 'name': '测试展柜项目', 'revision': 4},
                                      {'id': 'other', 'name': '其他项目', 'revision': 1}],
                         'tasks': [], 'parts': [], 'documents': []}

    def get(self, con, kind, identifier):
        return next(item for item in self.entities[kind] if item['id'] == identifier)

    def all(self, con, kind, project_id=None):
        return [item for item in self.entities[kind] if not project_id or item.get('project_id') == project_id]


def pdf_bytes():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R >>',
               b'<< /Length 28 >>\nstream\n0 0 1 RG 20 20 200 100 re S\nendstream',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 6 0 R >>',
               b'<< /Length 28 >>\nstream\n1 0 0 RG 40 40 150 120 re S\nendstream']
    data = b'%PDF-1.4\n'; offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 7\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + b'trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'


class BadgeMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'drawing-previews' / 'assets'
        self.assets.mkdir(parents=True)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        self.store = Store(self.root)
        self.counter = 0

    def image(self, *, kind='施工图', title='柜体图', file='施工图.pdf', page=1, image=None, **options):
        self.counter += 1
        name = hashlib.sha256(str(self.counter).encode()).hexdigest() + '.png'
        path = self.assets / name
        (image or Image.new('RGB', (240, 120), 'teal')).save(path, **options)
        return {'kind': kind, 'title': title, 'source_file': file, 'page': page,
                'url': '/api/drawing-media/assets/' + name}

    def manifest(self, *, parts=None, sources=None, renders=None, other=None):
        value = {'projects': {'p': {'parts': parts or {}, 'sources': sources or [], 'renders': renders or []}}}
        if other:
            value['projects']['other'] = other
        path = self.root / 'drawing-previews' / 'manifest.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def catalog(self, task_id=None):
        return badge.catalog(self.store, None, 'p', task_id)

    def prepare(self, ids, task_id=None):
        return badge.prepare(self.store, None, 'p', ids, task_id)

    def test_no_cross_project_fallback_and_no_mutation(self):
        original = self.manifest(other={'sources': [self.image()], 'renders': [self.image(kind='效果图')]})
        before = original.read_bytes()
        result = self.catalog()
        self.assertEqual(result['items'], [])
        self.assertEqual(len(result['warnings']), 2)
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.store.entities['tasks'], [])

    def test_identical_pixels_deduplicate_and_id_stays_stable_when_title_changes(self):
        metadata = PngImagePlugin.PngInfo(); metadata.add_text('source', 'another file')
        a = self.image(); b = self.image(title='重复文件', pnginfo=metadata)
        self.manifest(parts={'part': [a]}, sources=[a, b])
        before = self.catalog()['items']
        self.assertEqual(len(before), 1)
        a['title'] = '改名'; self.manifest(sources=[a])
        self.assertEqual(before[0]['id'], self.catalog()['items'][0]['id'])
        self.assertFalse(any(key.startswith('_') for key in before[0]))
        self.assertNotIn(str(self.root), json.dumps(before))

    def test_part_and_page_evidence_rank_ahead_of_unrelated_project_drawings(self):
        unrelated = self.image(image=Image.new('RGB', (240, 120), 'red'))
        match = self.image(title='对应柜体', file='关联图.pdf', page=3)
        self.manifest(parts={'external-part-1': [match]}, sources=[unrelated, match])
        self.store.entities['parts'] = [{'id': 'part1', 'project_id': 'p', 'source': {'external_id': 'external-part-1'},
                                         'evidence': [{'file': '关联图.pdf', 'page': 3}]}]
        self.store.entities['tasks'] = [{'id': 'task', 'project_id': 'p', 'part_id': 'part1'}]
        result = self.catalog('task')
        self.assertEqual(result['items'][0]['title'], '对应柜体')
        self.assertTrue(result['items'][0]['task_match'])
        self.assertFalse(result['items'][1]['task_match'])
        self.assertEqual(result['items'][0]['association'], 'part')

    def test_task_from_other_project_rejected(self):
        self.store.entities['tasks'] = [{'id': 'task', 'project_id': 'other'}]
        with self.assertRaisesRegex(badge.BadgeMediaError, '不属于'):
            self.catalog('task')

    def test_packet_exact_pdf_page_keeps_part_link_and_prepares_correct_page(self):
        if not executable('pdftoppm'):self.skipTest('Poppler required')
        raw=pdf_bytes();(self.uploads/'packet.source').write_bytes(raw)
        self.store.entities['documents']=[{'id':'pdf','project_id':'p','filename':'施工图.pdf',
            'storage_name':'packet.source','sha256':hashlib.sha256(raw).hexdigest(),'page_count':2}]
        self.store.entities['parts']=[{'id':'part1','project_id':'p','source':{'part_number':'ORDER-001'},
            'evidence':[{'file':'施工图.pdf','page':2}]}]
        self.store.entities['tasks']=[{'id':'task','project_id':'p','part_id':'part1'}]
        self.manifest(parts={'ORDER-001':[{'document_id':'pdf','source_file':'施工图.pdf','kind':'工程图',
            'title':'指定柜体的零件页','page':2,'url':'/api/documents/pdf/preview-image?page=2'}]})
        result=self.catalog('task');chosen=result['items'][0]
        self.assertEqual((chosen['page'],chosen['association']),(2,'part'))
        self.assertFalse(any('原图预览不可用' in w for w in result['warnings']))
        self.assertEqual(self.prepare([chosen['id']],'task')['images'][0]['source_page'],2)

    def test_verified_cad_export_is_task_linked_only_while_original_is_current(self):
        if not executable('pdftoppm'): self.skipTest('Poppler required')
        raw = pdf_bytes()
        (self.uploads / 'export.source').write_bytes(raw)
        self.store.entities['documents'] = [
            {'id': 'native', 'project_id': 'p', 'filename': 'cabinet.dwg',
             'sha256': 'a' * 64, 'storage_name': 'native.source'},
            {'id': 'export', 'project_id': 'p', 'filename': 'cabinet.pdf',
             'sha256': hashlib.sha256(raw).hexdigest(), 'storage_name': 'export.source',
             'companion_for': [{'document_id': 'native', 'sha256': 'a' * 64}]},
        ]
        self.store.entities['tasks'] = [{'id': 'task', 'project_id': 'p',
                                         'source': {'document_ids': ['native']}}]
        self.manifest()
        linked = self.catalog('task')['items']
        self.assertEqual(len(linked), 2)
        self.assertTrue(all(item['task_match'] and item['association'] == 'document' for item in linked))
        self.store.entities['documents'][0]['superseded'] = True
        old = self.catalog('task')['items']
        self.assertTrue(all(not item['task_match'] for item in old))

    def test_product_reference_is_not_falsely_called_construction_drawing(self):
        self.manifest(sources=[self.image(kind='产品参考')])
        self.assertFalse(self.catalog()['items'])

    def test_arbitrary_url_path_and_symlink_are_not_sources(self):
        external = self.root / 'outside.png'; Image.new('RGB', (20, 20)).save(external)
        symlink = self.assets / ('f' * 64 + '.png'); symlink.symlink_to(external)
        items = [{'kind': '施工图', 'url': value, 'source_file': 'bad.png'} for value in
                 ['https://example.com/x.png', str(external), '/api/drawing-media/assets/../../outside.png',
                  '/api/drawing-media/assets/' + symlink.name]]
        self.manifest(sources=items)
        self.assertFalse(self.catalog()['items'])
        with self.assertRaisesRegex(badge.BadgeMediaError, '不属于'):
            self.prepare([str(external)])

    def test_each_kind_only_one_and_duplicate_selection_rejected(self):
        self.manifest(sources=[self.image(), self.image(image=Image.new('RGB', (240, 120), 'red'))])
        ids = [item['id'] for item in self.catalog()['items']]
        for selection in ([], ids + ['fake'], ids, [ids[0], ids[0]], '../picture.jpg', [None]):
            with self.assertRaises(badge.BadgeMediaError):
                self.prepare(selection)

    def test_full_image_keeps_aspect_ratio_and_white_letterbox_without_crop(self):
        original = Image.new('RGB', (200, 100), 'red')
        self.manifest(sources=[self.image(image=original)])
        result = self.prepare([self.catalog()['items'][0]['id']])
        image = result['images'][0]
        self.assertEqual((image['width'], image['height']), badge.CANVAS)
        self.assertEqual(image['sha256'], hashlib.sha256(image['bytes']).hexdigest())
        self.assertLessEqual(len(image['bytes']), badge.MAX_BYTES)
        with Image.open(io.BytesIO(image['bytes'])) as decoded:
            self.assertEqual(decoded.format, 'JPEG')
            self.assertFalse(decoded.info.get('progressive'))
            self.assertEqual(decoded.size, badge.CANVAS)
            self.assertEqual(decoded.getpixel((640, 10)), (255, 255, 255))
            r, g, b = decoded.getpixel((640, 896)); self.assertGreater(r, 240); self.assertLess(g + b, 20)
            r, g, b = decoded.getpixel((10, 896)); self.assertGreater(r, 240); self.assertLess(g + b, 20)
        self.assertEqual(result['revision'], 4)
        self.assertIsNone(result['task_id'])
        self.assertFalse(self.store.entities['tasks'])

    def test_exif_orientation_and_transparency_are_respected(self):
        source = Image.new('RGBA', (10, 20), (20, 60, 220, 255))
        source.putpixel((0, 0), (0, 0, 0, 0))
        exif = Image.Exif(); exif[274] = 6
        self.manifest(renders=[self.image(kind='效果图', image=source, exif=exif)])
        image = self.prepare([self.catalog()['items'][0]['id']])['images'][0]
        self.assertEqual((image['source_width'], image['source_height']), (20, 10))
        with Image.open(io.BytesIO(image['bytes'])) as decoded:
            self.assertNotIn(274, decoded.getexif())
            self.assertEqual(decoded.getpixel((640, 0)), (255, 255, 255))

    def test_complex_noise_still_fits_payload_cap_at_fixed_canvas_size(self):
        noise = Image.effect_noise(badge.CANVAS, 100).convert('RGB')
        self.manifest(sources=[self.image(image=noise)])
        image = self.prepare([self.catalog()['items'][0]['id']])['images'][0]
        self.assertLess(image['quality'], 90)
        self.assertLessEqual(image['size'], badge.MAX_BYTES)
        self.assertEqual((image['width'], image['height']), badge.CANVAS)

    def test_render_upload_is_registered_and_foreign_upload_never_selected(self):
        for identifier, project in [('render', 'p'), ('secret', 'other')]:
            path = self.uploads / (identifier + '.source'); Image.new('RGB', (20, 20), 'green').save(path, format='PNG')
            self.store.entities['documents'].append({'id': identifier, 'project_id': project, 'filename': identifier + '.png',
                 'storage_name': path.name, 'purpose': 'render', 'image': {'width': 20, 'height': 20, 'mime_type': 'image/png'}})
        self.manifest(renders=[{'kind': '效果图', 'url': '/api/documents/secret/image'}])
        result = self.catalog()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['document_id'], 'render')
        self.assertEqual(result['items'][0]['kind'], 'render')

    def test_corrupt_manifest_does_not_hide_registered_render_upload(self):
        path = self.uploads / 'render.source'
        Image.new('RGB', (20, 20), 'green').save(path, format='PNG')
        self.store.entities['documents'] = [{'id': 'render', 'project_id': 'p', 'filename': '效果图.png',
            'storage_name': path.name, 'purpose': 'render',
            'image': {'width': 20, 'height': 20, 'mime_type': 'image/png'}}]
        (self.root / 'drawing-previews' / 'manifest.json').write_text(
            json.dumps({'projects': {'p': {'parts': ['invalid shape']}}}))
        result = self.catalog()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['document_id'], 'render')
        self.assertTrue(any('索引无法读取' in warning for warning in result['warnings']))

    def test_changed_source_invalidates_selected_id(self):
        entry = self.image(); self.manifest(sources=[entry])
        identifier = self.catalog()['items'][0]['id']
        path = self.assets / entry['url'].rsplit('/', 1)[-1]
        Image.new('RGB', (240, 120), 'blue').save(path)
        with self.assertRaisesRegex(badge.BadgeMediaError, '已经更新'):
            self.prepare([identifier])

    def test_corrupt_pdf_returns_actionable_warning(self):
        path = self.uploads / 'bad.source'; path.write_bytes(b'not a PDF')
        self.store.entities['documents'] = [{'id': 'bad', 'project_id': 'p', 'filename': '坏图.pdf',
                                            'storage_name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
        result = self.catalog()
        self.assertFalse(result['items'])
        self.assertTrue(any('有效 PDF' in warning for warning in result['warnings']))

    @unittest.skipUnless(executable('pdftoppm') and executable('pdfinfo'), 'Poppler required')
    def test_registered_pdf_pages_are_selectable_with_real_page_content(self):
        path = self.uploads / 'pdf.source'; path.write_bytes(pdf_bytes())
        self.store.entities['documents'] = [{'id': 'pdf', 'project_id': 'p', 'filename': '施工图.pdf',
                                            'storage_name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
        candidates = self.catalog()['items']
        self.assertEqual([item['page'] for item in candidates], [1, 2])
        first = self.prepare([candidates[0]['id']])['images'][0]
        second = self.prepare([candidates[1]['id']])['images'][0]
        self.assertEqual(second['source_page'], 2)
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertEqual(path.read_bytes(), pdf_bytes())

    @unittest.skipUnless(executable('pdftoppm') and executable('pdfinfo'), 'Poppler required')
    def test_selected_pdf_render_failure_is_explicit(self):
        path = self.uploads / 'pdf.source'; path.write_bytes(pdf_bytes())
        self.store.entities['documents'] = [{'id': 'pdf', 'project_id': 'p', 'filename': '施工图.pdf',
                                            'storage_name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
        selected = self.catalog()['items'][1]['id']
        actual = badge.preview_pdf
        def fail_second(*args):
            if args[-1] == 2:
                raise badge.PreviewError('这一页无法生成预览')
            return actual(*args)
        with patch.object(badge, 'preview_pdf', side_effect=fail_second):
            with self.assertRaisesRegex(badge.BadgeMediaError, '第 2 页.*无法生成预览'):
                self.prepare([selected])


if __name__ == '__main__':
    unittest.main()
