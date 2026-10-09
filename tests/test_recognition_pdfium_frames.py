"""Real PDFium render pixels verify intrinsic rotation and MediaBox coordinates."""
import hashlib
import importlib.util
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import document_recognition as recognition


def fixture_pdf(rotation=0, crop=None, media=(10, 20, 210, 120)):
    # One black H at a fixed PDF point and a red marker centered at (50,40).
    stream = b'BT /F1 12 Tf 80 60 Td (H) Tj ET\n1 0 0 rg 48 38 4 4 re f\n'
    box = lambda values: ' '.join(str(v) for v in values)
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               (f'<< /Type /Page /Parent 2 0 R /MediaBox [{box(media)}] /Rotate {rotation} '
                + (f'/CropBox [{box(crop)}] ' if crop else '')
                + '/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>').encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    body, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body)); body.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(body); body.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]: body.extend(f'{offset:010d} 00000 n \n'.encode())
    body.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(body)


@unittest.skipUnless(importlib.util.find_spec('pypdfium2') and importlib.util.find_spec('PIL'), 'real PDFium/Pillow required')
class PDFiumFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'source.pdf'
        self.opts = {'parser': 'native', 'pages': None, 'max_pages': 20}
        self.source = {'source_id': 'doc:frame', 'document_id': 'frame', 'filename': 'frame.pdf',
                       'source_sha256': 'a' * 64, 'source_revision': 1, 'source_role': 'drawing'}

    def tearDown(self): self.temp.cleanup()

    def test_four_intrinsic_rotations_with_crop_and_nonzero_media_origin_match_render_pixels(self):
        import pypdfium2 as pdfium
        expected_marker = {0: (40, 80), 90: (20, 40), 180: (160, 20), 270: (80, 160)}
        for rotation in (0, 90, 180, 270):
            for crop in (None, (30, 30, 180, 100)):
                with self.subTest(rotation=rotation, crop=crop):
                    self.path.write_bytes(fixture_pdf(rotation, crop)); original_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
                    result = recognition._pdf_pdfium(self.path, self.source, self.opts, allow_transformed=True)
                    self.assertEqual(result['engine'], 'pdfium-native-char')
                    self.assertEqual(result['completeness'], 'observed')
                    self.assertEqual(len(result['evidence_refs']), 1)
                    ref = result['evidence_refs'][0]; loc = ref['locator']; bbox = loc['bbox_pdf_points']
                    self.assertEqual(ref['raw_text'], 'H')
                    self.assertEqual(loc['rotation'], rotation)
                    self.assertEqual(loc['mediabox'], [10., 20., 210., 120.])
                    self.assertEqual(loc['cropbox'], list(crop or (10, 20, 210, 120)))
                    self.assertEqual(loc['coordinate_space'], 'pdf_media_display_page')
                    self.assertEqual(loc['page_size_pdf_points'], [100, 200] if rotation in (90, 270) else [200, 100])
                    self.assertTrue(all(math.isfinite(value) for value in bbox))
                    self.assertTrue(0 <= bbox[0] < bbox[2] <= loc['page_size_pdf_points'][0])
                    self.assertTrue(0 <= bbox[1] < bbox[3] <= loc['page_size_pdf_points'][1])
                    document = pdfium.PdfDocument(str(self.path)); page = document[0]
                    original_crop = page.get_cropbox()
                    try:
                        with recognition._pdfium_media_frame(page) as frame:
                            # Same render parameters as the mapping: origin 0,
                            # displayed page size, and extra rotation 0.
                            bitmap = page.render(scale=4, rotation=0, draw_annots=False)
                            try: image = bitmap.to_pil().convert('RGB')
                            finally: bitmap.close()
                            point = frame['point'](50, 40)
                        self.assertEqual(page.get_cropbox(), original_crop)
                    finally: page.close(); document.close()
                    self.assertAlmostEqual(point[0], expected_marker[rotation][0], places=3)
                    self.assertAlmostEqual(point[1], expected_marker[rotation][1], places=3)
                    red, black = [], []
                    for y in range(image.height):
                        for x in range(image.width):
                            r, g, b = image.getpixel((x, y))
                            if r > 200 and g < 40 and b < 40: red.append((x + .5, y + .5))
                            elif max(r, g, b) < 80: black.append((x + .5, y + .5))
                    self.assertTrue(red); self.assertTrue(black)
                    self.assertAlmostEqual(sum(x for x, _ in red) / len(red), point[0] * 4, delta=1)
                    self.assertAlmostEqual(sum(y for _, y in red) / len(red), point[1] * 4, delta=1)
                    for x, y in black:
                        self.assertTrue(bbox[0] * 4 - 2 <= x <= bbox[2] * 4 + 2)
                        self.assertTrue(bbox[1] * 4 - 2 <= y <= bbox[3] * 4 + 2)
                    self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), original_hash)

    def test_zero_origin_unrotated_character_box_does_not_regress(self):
        import pypdfium2 as pdfium
        self.path.write_bytes(fixture_pdf(media=(0, 0, 200, 100)))
        result = recognition._pdf_pdfium(self.path, self.source, self.opts)
        doc = pdfium.PdfDocument(str(self.path)); page = doc[0]; text = page.get_textpage()
        try:
            left, bottom, right, top = text.get_charbox(0)
            expected = [left, 100 - top, right, 100 - bottom]
        finally: text.close(); page.close(); doc.close()
        for actual, wanted in zip(result['evidence_refs'][0]['locator']['bbox_pdf_points'], expected):
            self.assertAlmostEqual(actual, wanted, delta=.001)

    def test_failed_native_conversion_and_invalid_frame_never_create_locator(self):
        import pypdfium2 as pdfium
        self.path.write_bytes(fixture_pdf(270, (30, 30, 180, 100)))
        with patch('pypdfium2.raw.FPDF_PageToDevice', return_value=0):
            with self.assertRaises(recognition.RecognitionError) as caught:
                recognition._pdf_pdfium(self.path, self.source, self.opts, allow_transformed=True)
        self.assertEqual(caught.exception.status, 422)
        doc = pdfium.PdfDocument(str(self.path)); page = doc[0]; original_crop = page.get_cropbox()
        try:
            for media in ([0, 0, float('nan'), 100], [0, 0, 0, 100]):
                with self.assertRaises(recognition.RecognitionError):
                    with recognition._pdfium_media_frame(page, {'mediabox': media, 'cropbox': [0, 0, 200, 100], 'rotation': 270}):
                        self.fail('invalid frame accepted')
            self.assertEqual(page.get_cropbox(), original_crop)
        finally: page.close(); doc.close()

    def test_poppler_failure_rescues_rotated_pdf_with_verified_sdk_mapping(self):
        self.path.write_bytes(fixture_pdf(270, (30, 30, 180, 100)))
        with patch.object(recognition, '_pdf_poppler', side_effect=recognition.RecognitionError(422, 'fixture compatibility failure')):
            result = recognition.parse(self.path, self.source, self.opts)
        self.assertEqual(result['engine'], 'pdfium-native-char')
        self.assertEqual(result['evidence_refs'][0]['raw_text'], 'H')
        self.assertTrue(any(issue['code'] == 'poppler_compatibility_fallback' for issue in result['issues']))

    def test_unknown_media_box_without_independent_geometry_fails_explicitly(self):
        self.path.write_bytes(fixture_pdf(270))
        with patch('document_recognition.shutil.which', return_value=None), \
                patch('pypdfium2.PdfPage.get_mediabox', return_value=None):
            with self.assertRaises(recognition.RecognitionError) as caught:
                recognition._pdf_pdfium(self.path, self.source, self.opts, allow_transformed=True)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn('无法核实MediaBox', str(caught.exception))

    def test_partial_image_pages_report_ocr_even_when_other_page_contains_text(self):
        # Single blank selected page remains explicitly incomplete; mixed-page
        # bookkeeping is exercised on a real document using a second page.
        import pypdfium2 as pdfium
        original = pdfium.PdfDocument.new(); original.new_page(200, 100)
        self.path.write_bytes(fixture_pdf(media=(0, 0, 200, 100)))
        text = pdfium.PdfDocument(str(self.path))
        try:
            original.import_pages(text)
            original.save(self.path)
        finally: text.close(); original.close()
        result = recognition._pdf_pdfium(self.path, self.source, self.opts)
        self.assertEqual(len(result['pages']), 2)
        self.assertEqual(result['completeness'], 'partial')
        self.assertEqual(next(issue for issue in result['issues'] if issue['code'] == 'ocr_required')['pages'], [1])
        self.assertEqual(result['evidence_refs'][0]['locator']['page'], 2)


if __name__ == '__main__': unittest.main()
