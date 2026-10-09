"""Staged customer evidence arrives over time; only current files may release.

All HTTP calls and images use an isolated temporary store. No factory data or
physical badge is touched.
"""
import base64
import io
import unittest

from PIL import Image

import test_api


class DocumentFlowTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state

    def project(self):
        code, body = self.request('/api/projects', {'name': '模拟测试 · 逐步补图展示柜', 'quantity': 1})
        self.assertEqual(code, 200, body)
        self.assertEqual(body['project']['evidence_policy'], 'staged')
        return body['project']

    def upload(self, project, filename, content, **extra):
        code, body = self.request('/api/import', {'project_id': project['id'], 'filename': filename,
                                  'content_base64': base64.b64encode(content).decode(), **extra})
        self.assertEqual(code, 200, body)
        return body

    def render_bytes(self, color='navy'):
        image = Image.new('RGB', (16, 12), color)
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        return stream.getvalue()

    def confirm(self, project, stage, document, note='客户微信确认此版图纸'):
        code, body = self.request('/api/projects/' + project['id'] + '/document-confirmations', {
            'stage': stage, 'document_id': document['id'], 'document_sha256': document['sha256'],
            'note': note, 'expected_confirmation_version': project['document_confirmation_version']})
        if code == 200:
            project.update(body['project'])
        return code, body

    def setup_stages(self):
        project = self.project()
        render = self.upload(project, '客户效果图.png', self.render_bytes(), purpose='render')['document']
        self.assertEqual(self.confirm(project, 'render', render)[0], 200)
        construction = self.upload(project, '客户确认施工图.dwg', b'AC1015\x00construction')['document']
        self.assertEqual(self.confirm(project, 'construction', construction)[0], 200)
        original = self.upload(project, '柜体工程总装.SLDASM', b'SOLIDWORKS ASSEMBLY PLACEHOLDER')['document']
        bom = b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\n'
        companion = self.upload(project, '柜体工程BOM.csv', bom, related_document_id=original['id'])
        part = companion['parts'][0]
        self.assertEqual(self.request('/api/parts/' + part['id'] + '/review', {'approved': True})[0], 200)
        self.assertEqual(self.request('/api/documents/' + original['id'] + '/resolve', {'note': '按同一总装的 BOM 核对构件'})[0], 200)
        self.assertEqual(self.confirm(project, 'engineering', original)[0], 200)
        return project, render, construction, original, part

    def test_bom_only_cannot_release_and_confirmation_requires_order(self):
        project = self.project()
        imported = self.upload(project, '仅有BOM.csv',
                               b'name,material,category,length,width,thickness,quantity,unit,finish\nPanel,Plywood,wood,1200,600,18,2,mm,clear\n')
        part = imported['parts'][0]
        self.assertEqual(self.request('/api/parts/' + part['id'] + '/review', {'approved': True})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)
        code, body = self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(code, 409, body)
        self.assertTrue(any('效果图' in message for message in body['details']))
        self.assertTrue(any('施工图' in message for message in body['details']))
        self.assertTrue(any('工程图' in message for message in body['details']))
        self.assertEqual(self.confirm(project, 'engineering', imported['document'])[0], 409)

    def test_sequential_approval_allows_release_and_changed_render_invalidates(self):
        project, render, construction, original, part = self.setup_stages()
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)
        code, released = self.request('/api/projects/' + project['id'] + '/release', {})
        self.assertEqual(code, 200, released)
        previous_revision = released['project']['revision']
        replacement = self.upload(project, '客户效果图.png', self.render_bytes('red'), purpose='render')['document']
        self.assertNotEqual(render['sha256'], replacement['sha256'])
        current = next(p for p in self.state()['projects'] if p['id'] == project['id'])
        self.assertGreater(current['revision'], previous_revision)
        self.assertEqual(current['status'], 'review')
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 409)
        self.assertEqual(self.confirm(project, 'engineering', original)[0], 409)
        project.update(current)
        self.assertEqual(self.confirm(project, 'render', replacement)[0], 200)
        self.assertNotIn('construction', project['document_confirmations'])
        self.assertNotIn('engineering', project['document_confirmations'])
        self.assertEqual(self.confirm(project, 'construction', construction)[0], 200)
        self.assertEqual(self.confirm(project, 'engineering', original)[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/generate', {})[0], 200)
        self.assertEqual(self.request('/api/projects/' + project['id'] + '/release', {})[0], 200)

    def test_stale_version_wrong_file_and_cross_project_are_rejected(self):
        project = self.project()
        other = self.project()
        render = self.upload(project, '客户效果图.png', self.render_bytes(), purpose='render')['document']
        construction = self.upload(project, '施工图.dwg', b'AC1015\x00drawing')['document']
        self.assertEqual(self.confirm(project, 'construction', construction)[0], 409)
        code, _ = self.request('/api/projects/' + other['id'] + '/document-confirmations', {
            'stage': 'render', 'document_id': render['id'], 'document_sha256': render['sha256'],
            'note': '别的项目', 'expected_confirmation_version': 0})
        self.assertEqual(code, 409)
        self.assertEqual(self.confirm(project, 'render', render)[0], 200)
        code, _ = self.request('/api/projects/' + project['id'] + '/document-confirmations', {
            'stage': 'construction', 'document_id': construction['id'], 'document_sha256': construction['sha256'],
            'note': '旧页面', 'expected_confirmation_version': 0})
        self.assertEqual(code, 409)


if __name__ == '__main__':
    unittest.main()
