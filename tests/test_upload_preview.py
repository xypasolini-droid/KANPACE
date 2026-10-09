"""Real HTTP upload feedback and registered PDF preview behavior."""
import base64
import hashlib
import unittest
from unittest.mock import patch

import test_api
import test_order_drafts
from upload_preview import executable


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
    data += b'trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'
    return data


class UploadPreviewTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    state = test_api.APITests.state

    @unittest.skipUnless(executable('pdftoppm') and executable('pdfinfo'), 'Poppler required for PDF rendering')
    def test_pdf_upload_returns_real_preview_without_fabricated_parts(self):
        project, result = self.imported(filename='展示柜施工图.pdf', content=pdf_bytes())
        doc = result['document']
        self.assertEqual(doc['page_count'], 2)
        self.assertEqual(doc['preview_status'], 'ready')
        self.assertEqual(doc['status'], 'needs_conversion')
        self.assertEqual(result['parts'], [])
        preview = doc['previews'][0]
        status, image = self.request(preview['url'], raw=True)
        self.assertEqual(status, 200)
        self.assertTrue(image.startswith(b'\xff\xd8'))
        status, page = self.request(f"/api/documents/{doc['id']}/preview?page=2")
        self.assertEqual(status, 200, page)
        self.assertEqual(page['page'], 2)
        self.assertNotEqual(page['url'], preview['url'])
        self.assertEqual(self.request(f"/api/documents/{doc['id']}/preview?page=3")[0], 422)
        self.assertEqual(self.request(f"/api/documents/{doc['id']}/preview?page=../1")[0], 400)
        self.assertFalse(self.state()['tasks'])

    @unittest.skipUnless(executable('pdftoppm') and executable('pdfinfo'), 'Poppler required for PDF rendering')
    def test_legacy_pdf_gets_preview_without_reupload_or_revision_change(self):
        project, result = self.imported(filename='旧图纸.pdf', content=pdf_bytes())
        doc = result['document']
        with self.store.connect() as con:
            for field in ['preview_status', 'page_count', 'previews']:
                doc.pop(field, None)
            self.store.put(con, 'documents', doc)
        before = self.state()['projects'][0]['revision']
        status, image = self.request(f"/api/documents/{doc['id']}/preview-image?page=1&thumb=1", raw=True)
        self.assertEqual(status, 200)
        self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertEqual(self.state()['projects'][0]['revision'], before)

    def test_invalid_pdf_is_retained_with_visible_preview_error(self):
        _, result = self.imported(filename='错误图纸.pdf', content=b'not a pdf')
        doc = result['document']
        self.assertEqual(doc['preview_status'], 'error')
        self.assertIn('有效 PDF', doc['preview_error'])
        self.assertEqual(self.request(f"/api/documents/{doc['id']}/download", raw=True)[1], b'not a pdf')
        self.assertEqual(self.request(f"/api/documents/{doc['id']}/preview")[0], 422)

    def test_missing_preview_tool_does_not_lose_upload(self):
        with patch('upload_preview.executable', return_value=None):
            _, result = self.imported(filename='施工图.pdf', content=pdf_bytes())
        self.assertEqual(result['document']['preview_status'], 'error')
        self.assertIn('Poppler', result['document']['preview_error'])

    def test_identical_source_links_existing_draft_without_copying_parts(self):
        content = b'registered source bytes'
        draft = test_order_drafts.payload()
        draft['sources'][0]['sha256'] = hashlib.sha256(content).hexdigest()
        status, original = self.request('/api/order-drafts/import', draft)
        self.assertEqual(status, 200, original)
        project, result = self.imported(filename='施工图.dwg', content=content)
        self.assertEqual(result['existing_drafts'][0]['project_id'], original['project']['id'])
        self.assertEqual(result['existing_drafts'][0]['part_count'], 1)
        self.assertFalse(result['parts'])
        again = self.imported(project, filename='施工图.dwg', content=content)[1]
        self.assertTrue(again['duplicate'])
        self.assertEqual(again['existing_drafts'], result['existing_drafts'])
        self.assertEqual(len(self.state()['parts']), 1)
        self.assertEqual(next(d for d in self.state()['documents'] if d['id'] == result['document']['id'])['existing_drafts'], result['existing_drafts'])

    def test_only_registered_documents_and_generated_assets_are_accessible(self):
        self.assertEqual(self.request('/api/documents/not-a-document/preview')[0], 404)
        self.assertEqual(self.request('/api/drawing-media/assets/../../app.py')[0], 404)
        self.assertEqual(self.request('/api/drawing-media/assets/' + 'f'*64 + '.jpg')[0], 404)
        project = self.project()
        status, media = self.request('/api/projects/' + project['id'] + '/drawing-media')
        self.assertEqual(status, 200)
        self.assertEqual(media['parts'], {})


if __name__ == '__main__':
    unittest.main()
