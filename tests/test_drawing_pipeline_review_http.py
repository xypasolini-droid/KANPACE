"""Real HTTP authorization, ZIP validation and review-only persistence."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_access_http
import app


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tiny_png():
    def chunk(name, value):
        return struct.pack('>I', len(value)) + name + value + struct.pack('>I', zlib.crc32(name + value) & 0xffffffff)
    scanline = zlib.compress(b'\x00\xff\x88\x00\xff')
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', scanline) + chunk(b'IEND', b''))


def packet_files():
    root = 'drawing-pipeline/'
    base = root + 'chongqing-selection-r1/'
    source_sha = sha(b'private model not inside package')
    scene = encoded({'schema': 'kanpace.scene-index.v1', 'source_sha256': source_sha,
                     'nodes': [{'id': '23'}], 'scope': 'test scene'})
    native_scene = encoded({'schema': 'kanpace.scene-index.v1', 'source_sha256': source_sha,
                            'nodes': [{'id': '23'}], 'scope': 'extract scene'})
    catalog = encoded({'schema': 'kanpace.scope-catalog.v1', 'source_sha256': source_sha,
                       'index_sha256': sha(scene), 'coverage': 'one review cabinet only',
                       'items': [{'id': 'CQ-01', 'name': '直柜', 'kind': '柜体',
                                  'node_ids': ['23'], 'scope_confirmed': False}]})
    bundle = gzip.compress(encoded({'schema': 'kanpace.mesh-bundle.v1', 'origin': 'native_max',
                                    'source': {'sha256': source_sha}, 'units': 'mm',
                                    'units_confirmed': False,
                                    'meshes': [{'id': '23', 'vertices_mm': [[0,0,0]], 'faces': []}]}), mtime=0)
    native = encoded({'success': True, 'source_unchanged': True,
                      'source_sha256': source_sha, 'geometry_sha256': sha(bundle)})
    visual = encoded({'source_sha256': source_sha, 'catalog_sha256': sha(catalog),
                      'bundle_sha256': sha(bundle), 'items': []})
    selection = encoded({'schema': 'kanpace.round1-selection.v1',
                         'source_sha256': source_sha, 'catalog_sha256': sha(catalog),
                         'bundle_sha256': sha(bundle), 'scope_basis': 'main_display_arrangement_only',
                         'items': [{'id': 'CQ-01', 'node_ids': ['23'], 'quantity': 1,
                                    'scope_confirmed': True, 'orientation_confirmed': True,
                                    'rotation_z_degrees': 0, 'dimension_basis': 'model_only'}]})
    draft = root + 'chongqing-cq01-draft/'
    return {base + 'catalog.json': catalog,
            root + 'chongqing-index-003/scene_index.json': scene,
            base + 'native/scene_index.json': native_scene,
            base + 'native/geometry.json.gz': bundle,
            base + 'native/job_status.json': native,
            base + 'visual-data.json': visual,
            base + 'user-selection-001.json': selection,
            draft + 'review_manifest.json': encoded({'schema': 'kanpace.review-manifest.v1',
                                                      'project': 'CQ-01', 'release_status': 'blocked',
                                                      'evidence': {'bundle_sha256': sha(bundle),
                                                                   'dimensions_mm': {'width': 1200, 'depth': 550, 'height': 950}}}),
            draft + 'validation.json': encoded({'status': 'draft_only', 'input_bundle_sha256': sha(bundle)}),
            draft + 'preview.png': tiny_png(),
            draft + 'drawing.svg': b'<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="1" y2="1"/></svg>',
            draft + 'drawing.dxf': b'0\nSECTION\n0\nENDSEC\n0\nEOF\n'}


def make_zip(files):
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return sink.getvalue()


class DrawingPipelineReviewHTTPTests(unittest.TestCase):
    setUp = test_access_http.AccessHTTPTests.setUp
    tearDown = test_access_http.AccessHTTPTests.tearDown
    request = test_access_http.AccessHTTPTests.request
    setup_admin = test_access_http.AccessHTTPTests.setup_admin
    account = test_access_http.AccessHTTPTests.account

    def endpoint(self, project_id=None):
        return '/api/projects/' + (project_id or self.project['id']) + '/drawing-pipeline'

    def payload(self, contents=None):
        raw = make_zip(contents or packet_files())
        return {'filename': 'drawing-pipeline.zip', 'content_base64': base64.b64encode(raw).decode(),
                'expected_revision': self.project['revision']}

    def binary(self, path, cookie):
        request = urllib.request.Request(self.base + path, headers={'Origin': self.base,
                                                                     'Cookie': cookie.split(';', 1)[0]})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read(), dict(response.headers)

    def test_valid_archive_is_read_only_and_project_scoped(self):
        self.setup_admin()
        with self.store.connect() as con:
            before = (len(self.store.all(con, 'parts', self.project['id'])),
                      len(self.store.all(con, 'tasks', self.project['id'])))
            other = self.store.new_project(con, {'name':'其他项目', 'factory_type':'cabinet'})
        path = self.endpoint()
        code, created, _ = self.request(path + '/import', self.payload(), self.admin_cookie)
        self.assertEqual(code, 201, created)
        self.assertEqual((created['status'], created['review_only'], created['manufacturing_release'], created['can_dispatch']),
                         ('review_only', True, False, False))
        self.assertFalse(created['source']['model_file_present'])
        self.assertFalse(created['source_linked'])
        self.assertFalse(created['source']['source_match'])
        self.assertIn('未关联来源', created['warnings'][0])
        self.assertEqual(len(created['candidates']), 1)
        self.assertTrue(created['candidates'][0]['selected'])
        self.assertFalse(created['candidates'][0]['engineering_approved'])
        self.assertEqual(created['outputs'][0]['label'], 'CQ-01 早期外形核对草稿')
        self.assertEqual(self.request(path, cookie=self.admin_cookie)[1], created)
        self.assertEqual(self.request(self.endpoint(other['id']), cookie=self.admin_cookie)[1]['status'], 'empty')
        preview = created['outputs'][0]['preview_url']
        self.assertEqual(self.binary(preview, self.admin_cookie)[0:2], (200, tiny_png()))
        for kind in ('svg', 'dxf'):
            status, data, headers = self.binary(created['outputs'][0][kind + '_url'], self.admin_cookie)
            self.assertEqual(status, 200)
            self.assertIn('attachment', headers.get('Content-Disposition', ''))
            self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(self.binary(preview.replace('/' + self.project['id'] + '/', '/' + other['id'] + '/'), self.admin_cookie)[0], 404)
        with self.store.connect() as con:
            after = (len(self.store.all(con, 'parts', self.project['id'])),
                     len(self.store.all(con, 'tasks', self.project['id'])))
        self.assertEqual(before, after)
        self.assertEqual(self.request(path + '/import', self.payload(), self.admin_cookie)[0], 200)

    def test_source_link_requires_same_project_and_actual_max_bytes(self):
        self.setup_admin()
        path = self.endpoint()
        created = self.request(path + '/import', self.payload(), self.admin_cookie)[1]
        original = b'private model not inside package'
        wrong = b'changed source bytes'
        other_doc = {'id':'other-factory-model', 'project_id':'unrelated-project',
                     'filename':'original.max', 'sha256':sha(original), 'storage_name':'other-model.source'}
        (self.store.uploads / other_doc['storage_name']).write_bytes(original)
        with self.store.connect() as con:
            self.store.put(con, 'documents', other_doc)
        self.assertFalse(self.request(path, cookie=self.admin_cookie)[1]['source_linked'])
        doc = {'id':'same-project-model', 'project_id':self.project['id'],
               'filename':'original.max', 'sha256':sha(original), 'storage_name':'same-project-model.source'}
        (self.store.uploads / doc['storage_name']).write_bytes(wrong)
        with self.store.connect() as con:
            self.store.put(con, 'documents', doc)
        self.assertFalse(self.request(path, cookie=self.admin_cookie)[1]['source_linked'])
        (self.store.uploads / doc['storage_name']).write_bytes(original)
        linked = self.request(path, cookie=self.admin_cookie)[1]
        self.assertTrue(linked['source_linked'])
        self.assertEqual(linked['source']['source_document_id'], doc['id'])
        self.assertFalse(linked['can_dispatch'])
        self.assertEqual(linked['source']['model_sha256'], created['source']['model_sha256'])
        (self.store.uploads / doc['storage_name']).write_bytes(wrong)
        self.assertFalse(self.request(path, cookie=self.admin_cookie)[1]['source_linked'])

    def test_identical_project_id_in_another_factory_cannot_read_package(self):
        self.setup_admin()
        created = self.request(self.endpoint() + '/import', self.payload(), self.admin_cookie)[1]
        with tempfile.TemporaryDirectory() as private_factory:
            other_store = app.Store(private_factory, seed=False)
            with other_store.connect() as con:
                # An identical project ID is possible in a copied tenant database.
                other_store.put(con, 'projects', dict(self.project))
            other_server = app.Server(('127.0.0.1', 0), other_store)
            other_thread = threading.Thread(target=other_server.serve_forever, daemon=True)
            other_thread.start()
            try:
                origin = 'http://127.0.0.1:' + str(other_server.server_port)
                for suffix, expected in (('', 200),
                                         ('/assets/' + created['source']['id'] + '/preview', 404)):
                    request = urllib.request.Request(origin + self.endpoint() + suffix,
                                                     headers={'Origin': origin})
                    try:
                        response = urllib.request.urlopen(request, timeout=10)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        self.assertEqual(response.status, expected)
                        if expected == 200:
                            self.assertEqual(json.loads(response.read())['status'], 'empty')
            finally:
                other_server.shutdown(); other_server.server_close(); other_thread.join(timeout=2)

    def test_authorization_revision_and_closed_project(self):
        _, worker = self.account('worker', 'qa_dp_worker', 'qa_worker_a')
        _, technical = self.account('technical', 'qa_dp_technical')
        path = self.endpoint()
        self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request(path + '/import', self.payload(), worker)[0], 403)
        stale = self.payload(); stale['expected_revision'] += 1
        self.assertEqual(self.request(path + '/import', stale, technical)[0], 409)
        self.assertEqual(self.request(path + '/import', self.payload(), technical)[0], 201)
        self.assertEqual(self.request(path, cookie=worker)[0], 200)
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', self.project['id'])
            project['fulfillment_status'] = 'shipped'
            self.store.put(con, 'projects', project)
        self.assertEqual(self.request(path + '/import', self.payload(), technical)[0], 409)

    def test_tampering_member_paths_and_zip_bombs_are_rejected(self):
        self.setup_admin()
        base = packet_files()
        path = self.endpoint() + '/import'
        bad = dict(base); bad['../outside.txt'] = b'x'
        self.assertEqual(self.request(path, self.payload(bad), self.admin_cookie)[0], 422)
        bad = dict(base); bad['drawing-pipeline/evil.max'] = b'fake'
        self.assertEqual(self.request(path, self.payload(bad), self.admin_cookie)[0], 422)
        bad = dict(base); bad['drawing-pipeline/huge.txt'] = b'A' * (13 * 1024 * 1024)
        self.assertEqual(self.request(path, self.payload(bad), self.admin_cookie)[0], 413)
        bad = dict(base)
        key = 'drawing-pipeline/chongqing-selection-r1/user-selection-001.json'
        item = json.loads(bad[key]); item['source_sha256'] = '0' * 64; bad[key] = encoded(item)
        self.assertEqual(self.request(path, self.payload(bad), self.admin_cookie)[0], 422)
        bad = dict(base)
        key = 'drawing-pipeline/chongqing-selection-r1/user-selection-001.json'
        item = json.loads(bad[key]); item['items'][0]['node_ids'] = ['999']; bad[key] = encoded(item)
        self.assertEqual(self.request(path, self.payload(bad), self.admin_cookie)[0], 422)
        self.assertEqual(self.request(self.endpoint(), cookie=self.admin_cookie)[1]['status'], 'empty')


if __name__ == '__main__':
    unittest.main()
