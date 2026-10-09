"""Project appearance references stay separate from engineering evidence."""
import base64
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request

import test_api
from drawing_media import project_media

try:
    from PIL import Image
except ImportError:
    Image = None


def image_bytes(fmt='PNG', color='navy'):
    stream = io.BytesIO()
    Image.new('RGB', (96, 64), color).save(stream, format=fmt)
    return stream.getvalue()


@unittest.skipUnless(Image, 'Run python3 setup_media.py to install local image support')
class RenderUploadTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    prepared = test_api.APITests.prepared
    state = test_api.APITests.state

    def upload(self, project, filename='整体效果图.png', content=None, purpose='render'):
        return self.request('/api/import', {'project_id': project['id'], 'filename': filename,
            'purpose': purpose, 'content_base64': base64.b64encode(content if content is not None else image_bytes()).decode()})

    def test_supported_images_are_inline_project_references(self):
        project = self.project()
        for ext, fmt, mime in [('jpg', 'JPEG', 'image/jpeg'), ('jpeg', 'JPEG', 'image/jpeg'),
                               ('png', 'PNG', 'image/png'), ('webp', 'WEBP', 'image/webp')]:
            content = image_bytes(fmt)
            code, result = self.upload(project, '效果图.' + ext, content)
            self.assertEqual(code, 200, result)
            doc = result['document']
            self.assertEqual((doc['purpose'], doc['status'], doc['resolved']), ('render', 'reference', True))
            self.assertEqual(doc['image'], {'width': 96, 'height': 64, 'mime_type': mime})
            self.assertFalse(result['parts'])
            with urllib.request.urlopen(self.url + doc['image_url']) as response:
                self.assertEqual(response.headers['Content-Type'], mime)
                self.assertIsNone(response.headers.get('Content-Disposition'))
                self.assertEqual(response.read(), content)
            self.assertEqual(self.request('/api/documents/' + doc['id'] + '/download', raw=True)[1], content)

    def test_upload_does_not_change_engineering_and_does_not_block_release(self):
        project, _, _ = self.prepared()
        before = self.state()
        code, result = self.upload(project)
        self.assertEqual(code, 200, result)
        after = self.state()
        for collection in ('projects', 'parts', 'tasks'):
            self.assertEqual(before[collection], after[collection], collection)
        self.assertEqual(after['events'][-1]['action'], 'render_uploaded')
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 200)

    def test_duplicate_is_idempotent_and_different_purposes_do_not_alias(self):
        project = self.project()
        content = image_bytes()
        first = self.upload(project, content=content)[1]
        before = self.state()
        second = self.upload(project, filename='同一张效果图.png', content=content)[1]
        self.assertTrue(second['duplicate'])
        self.assertEqual(second['document']['id'], first['document']['id'])
        self.assertEqual(before, self.state())
        code, drawing = self.upload(project, content=content, purpose='drawing')
        self.assertEqual(code, 200, drawing)
        self.assertFalse(drawing['duplicate'])
        self.assertNotEqual(drawing['document']['id'], first['document']['id'])
        self.assertFalse(any(d.get('superseded') for d in self.state()['documents']))
        again = self.upload(project, content=content)[1]
        self.assertEqual(again['document']['id'], first['document']['id'])
        # Also exercise drawing first, then the same bytes registered as a render.
        other = self.project('另一项目')
        normal = self.upload(other, content=content, purpose='drawing')[1]
        render = self.upload(other, content=content)[1]
        self.assertNotEqual(normal['document']['id'], render['document']['id'])
        self.assertFalse(render['duplicate'])

    def test_same_name_replaces_only_render_preserving_tasks_and_original_bytes(self):
        project, _, _ = self.prepared()
        first = self.upload(project)[1]['document']
        before = self.state()
        second = self.upload(project, content=image_bytes(color='teal'))[1]['document']
        after = self.state()
        for collection in ('projects', 'parts', 'tasks'):
            self.assertEqual(before[collection], after[collection], collection)
        original = next(d for d in after['documents'] if d['id'] == first['id'])
        self.assertEqual(original['superseded_by'], second['id'])
        self.assertEqual(self.request(first['image_url'], raw=True)[1], image_bytes())
        media = self.request('/api/projects/' + project['id'] + '/drawing-media')[1]
        self.assertEqual([r['id'] for r in media['renders']], [second['id']])

    def test_manifest_renders_merge_with_only_this_projects_uploads(self):
        project = self.project()
        other = self.project('独立项目')
        first = self.upload(project)[1]['document']
        latest = self.upload(project, '近景.png', image_bytes(color='teal'))[1]['document']
        self.upload(other)
        folder = Path(self.temp.name) / 'drawing-previews'
        folder.mkdir()
        manifest_render = {'id': 'source-render', 'title': '源订单效果图', 'url': '/source.png'}
        (folder / 'manifest.json').write_text(json.dumps({'projects': {project['id']: {
            'parts': {'cabinet-1': [{'id': 'drawing-1'}]}, 'sources': [], 'renders': [manifest_render]}}}))
        code, media = self.request('/api/projects/' + project['id'] + '/drawing-media')
        self.assertEqual(code, 200, media)
        self.assertEqual([r['id'] for r in media['renders']], [latest['id'], first['id'], 'source-render'])
        self.assertEqual(media['parts'], {'cabinet-1': [{'id': 'drawing-1'}]})
        self.assertEqual(project_media(self.temp.name, project['id'], self.state()['documents'])['renders'], media['renders'])

    def test_corrupt_mislabeled_animated_and_unsafe_formats_rejected_without_writes(self):
        project = self.project()
        frames = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(frames, format='PNG', save_all=True,
            append_images=[Image.new('RGB', (8, 8), 'blue')], duration=100)
        cases = [('伪造.png', b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                 ('图.svg', b'<svg/>'), ('图.jpg', image_bytes('PNG')),
                 ('损坏.jpg', image_bytes('JPEG')[:-30]), ('损坏.png', image_bytes()[:-20]),
                 ('动画.png', frames.getvalue()), ('文件.pdf', b'%PDF-1.4')]
        before = self.state()
        for filename, content in cases:
            code, result = self.upload(project, filename, content)
            self.assertEqual(code, 422, (filename, result))
        self.assertEqual(self.state(), before)
        self.assertEqual(list(self.store.uploads.iterdir()), [])
        self.assertEqual(self.upload(project, purpose='model')[0], 400)

    def test_closed_project_cannot_upload_but_existing_reference_remains_visible(self):
        project = self.project()
        doc = self.upload(project)[1]['document']
        for state in ('completed', 'shipped'):
            self.assertEqual(self.request('/api/projects/' + project['id'] + '/fulfillment', {'status': state})[0], 200)
            before = self.state()
            self.assertEqual(self.upload(project, '另一个效果图.png', image_bytes(color='teal'))[0], 409)
            self.assertEqual(self.state(), before)
            self.assertEqual(self.request(doc['image_url'], raw=True)[0], 200)

    def test_missing_decoder_is_clear_and_does_not_silently_archive(self):
        project = self.project()
        content = image_bytes()
        with patch.dict(sys.modules, {'PIL': None}):
            code, result = self.upload(project, content=content)
        self.assertEqual(code, 503, result)
        self.assertIn('setup_media.py', result['error'])
        self.assertFalse(self.state()['documents'])
        self.assertEqual(list(self.store.uploads.iterdir()), [])

    def test_inline_route_requires_registered_render_and_rejects_symlink_escape(self):
        project, source = self.imported()
        self.assertEqual(self.request('/api/documents/' + source['document']['id'] + '/image')[0], 404)
        self.assertEqual(self.request('/api/documents/no-record/image')[0], 404)
        doc = self.upload(project)[1]['document']
        storage = self.store.uploads / doc['storage_name']
        outside = Path(self.temp.name) / 'private.png'
        outside.write_bytes(image_bytes(color='white'))
        storage.unlink()
        storage.symlink_to(outside)
        self.assertEqual(self.request(doc['image_url'])[0], 404)


if __name__ == '__main__':
    unittest.main()
