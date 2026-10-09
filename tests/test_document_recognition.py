"""Real native parsing/process/HTTP tests; service fixture is a protocol test.

The fixture never claims to run a learned model. External model accuracy remains
unverified until an actual pinned worker is deployed and evaluated.
"""
import base64
import hashlib
import importlib.util
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

import app
import document_recognition as recognition


def pdf_bytes(rotate=0, text='600 x 450 +/-0.5'):
    stream = ('BT /F1 12 Tf 20 50 Td (' + text + ') Tj ET').encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Rotate {rotate} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>').encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    body, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(str(i).encode() + b' 0 obj\n' + value + b'\nendobj\n')
    start = len(body)
    body.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        body.extend(f'{offset:010d} 00000 n \n'.encode())
    body.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(body)


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-recognition-')
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '识别隔离订单'})
            self.other = self.store.new_project(con, {'name': '另一订单'})
        self.pid = self.project['id']
        self.env = patch.dict(os.environ, {'KANPACE_RECOGNITION_SERVICE_CONFIG': ''})
        self.env.start()

    def tearDown(self):
        for proc in list(recognition._LIVE.values()):
            proc.wait(timeout=10)
        self.env.stop()
        self.temp.cleanup()

    def register(self, filename, content):
        # Register through the real upload application boundary. Upload may
        # create baseline draft parts; recognition must leave those untouched.
        with self.store.connect() as con:
            uploaded = self.store.import_file(con, {'project_id': self.pid, 'filename': filename,
                'content_base64': base64.b64encode(content).decode()})
            self.project = self.store.get(con, 'projects', self.pid)
        return uploaded['document']

    def submit(self, docs, **extra):
        with self.store.read_transaction() as con:
            return recognition.submit(self.store, con, self.pid, {
                'source_ids': ['doc:' + doc['id'] for doc in docs],
                'expected_revision': self.project['revision'], **extra})

    def wait(self, job):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.store.connect() as con:
                current = recognition.get_job(self.store, con, self.pid, job['id'])
            if current['status'] not in ('queued', 'running'):
                return current
            time.sleep(.03)
        self.fail('worker did not complete')

    def test_real_csv_preserves_symbols_quotes_multiline_cells_and_business_unchanged(self):
        content = '柜号,名称,尺寸\nC-01,"左,侧板","600×450×18 ±0.5"\nC-02,"跨行\n说明",\n'.encode()
        doc = self.register('清单.csv', content)
        with self.store.connect() as con:
            before = {k: self.store.all(con, k, self.pid) for k in ('parts', 'tasks', 'projects')}
        result = self.wait(self.submit([doc]))
        self.assertEqual(result['status'], 'completed', result)
        refs = result['result']['evidence_refs']
        self.assertIn('600×450×18 ±0.5', [r['raw_text'] for r in refs])
        multiline = next(r for r in refs if r['raw_text'] == '跨行\n说明')
        self.assertEqual(multiline['locator']['row'], 3)
        self.assertIsNone(multiline['locator']['bbox_pdf_points'])
        self.assertTrue(all(r['source_sha256'] == doc['sha256'] and r['review_status'] == 'unreviewed' for r in refs))
        with self.store.connect() as con:
            after = {k: self.store.all(con, k, self.pid) for k in before}
        self.assertEqual(before, after)
        # Real generated refs must survive the shared draft normalizer. This
        # checks the integration schema without importing production parts.
        import order_drafts
        ref = order_drafts.evidence(multiline)
        self.assertEqual(ref['locator']['row'], 3)
        self.assertEqual(ref['source_id'], 'doc:' + doc['id'])
        self.assertEqual(ref['review_status'], 'unreviewed')

    def test_duplicate_json_never_silently_overwrites_and_partial_job_can_resume(self):
        good = self.register('notes.txt', '数量未知\nL/R别合并'.encode())
        bad = self.register('bad.json', b'{"quantity":2,"quantity":9}')
        result = self.wait(self.submit([good, bad]))
        self.assertEqual(result['status'], 'partial')
        self.assertIn('重复键', result['result']['documents'][1]['error']['message'])
        saved = result['result']['evidence_refs']
        with self.store.connect() as con:
            retry = recognition.submit(self.store, con, self.pid, {
                'resume_job_id': result['id'], 'expected_revision': self.project['revision']})
        retried = self.wait(retry)
        self.assertEqual(retried['id'], result['id'])
        self.assertEqual(retried['result']['evidence_refs'], saved)

    def test_json_types_and_pointer_escaping_not_coerced_to_quantity(self):
        doc = self.register('fields.json', b'{"a/b":{"x~y":null},"quantity":0,"label":"O01"}')
        result = self.wait(self.submit([doc]))
        refs = result['result']['evidence_refs']
        self.assertEqual(next(r for r in refs if r['locator']['pointer'] == '/a~1b/x~0y')['candidate']['value'], None)
        self.assertEqual(next(r for r in refs if r['locator']['pointer'] == '/quantity')['candidate']['value'], 0)
        self.assertFalse(result['result']['manufacturing_release'])

    def test_cross_project_stale_hash_revision_and_client_paths_rejected(self):
        doc = self.register('input.txt', b'known source')
        job = self.wait(self.submit([doc]))
        with self.store.connect() as con:
            with self.assertRaises(recognition.RecognitionError) as caught:
                recognition.get_job(self.store, con, self.other['id'], job['id'])
            self.assertEqual(caught.exception.status, 404)
            with self.assertRaises(recognition.RecognitionError):
                recognition.submit(self.store, con, self.pid, {'source_ids': ['/etc/passwd'], 'expected_revision': self.project['revision']})
            with self.assertRaises(recognition.RecognitionError):
                recognition.submit(self.store, con, self.pid, {'source_ids': ['doc:' + doc['id']], 'expected_revision': True})
        (self.store.uploads / doc['storage_name']).write_bytes(b'changed')
        with self.store.connect() as con:
            self.assertFalse(recognition.get_job(self.store, con, self.pid, job['id'])['source_integrity']['current'])
        with self.assertRaises(recognition.RecognitionError):
            self.submit([doc])

    def test_durable_restart_detects_interruption_and_reuses_checkpoint(self):
        doc = self.register('input.txt', b'original note')
        job = self.wait(self.submit([doc]))
        folder = self.store.data_dir / 'recognition-jobs' / job['id']
        summary = json.loads((folder / 'job.json').read_text())
        summary['status'] = 'running'
        (folder / 'job.json').write_text(json.dumps(summary))
        (folder / 'process.json').write_text(json.dumps({'pid': 2147483647, 'started': time.time()}))
        restarted = app.Store(self.temp.name, seed=False)
        with restarted.connect() as con:
            interrupted = recognition.get_job(restarted, con, self.pid, job['id'])
            self.assertEqual(interrupted['status'], 'interrupted')
            retry = recognition.submit(restarted, con, self.pid, {'resume_job_id': job['id'], 'expected_revision': self.project['revision']})
        resumed = self.wait(retry)
        self.assertEqual(resumed['result']['evidence_refs'], job['result']['evidence_refs'])

    @unittest.skipUnless(shutil.which('pdftotext'), 'Poppler is not installed')
    def test_real_rotated_pdf_poppler_fallback_and_empty_scan_are_honest(self):
        doc = self.register('rotated.pdf', pdf_bytes(90))
        result = self.wait(self.submit([doc], options={'parser': 'native'}))
        self.assertEqual(result['status'], 'completed', result)
        refs = result['result']['evidence_refs']
        self.assertIn('600', [r['raw_text'] for r in refs])
        self.assertEqual(refs[0]['locator']['page_size_pdf_points'], [100, 200])
        self.assertEqual(refs[0]['locator']['rotation'], 90)
        import order_drafts
        normalized = order_drafts.evidence(refs[0])
        self.assertEqual(normalized['locator']['page_size_pdf_points'], [100, 200])
        self.assertEqual(normalized['raw_text'], '600')
        self.assertEqual(normalized['method'], 'poppler_native_bbox')
        for ref in refs:
            self.assertEqual(ref['locator']['page'], 1)
            self.assertEqual(len(ref['locator']['bbox_pdf_points']), 4)
            self.assertLessEqual(ref['locator']['bbox_pdf_points'][3], 200)
        empty = self.register('blank.pdf', pdf_bytes(text=''))
        blank = self.wait(self.submit([empty]))
        self.assertEqual(blank['result']['evidence_refs'], [])
        self.assertTrue(any(w['code'] == 'ocr_required' for w in blank['result']['warnings']))

    @unittest.skipUnless(importlib.util.find_spec('pypdfium2'), 'PDFium is not installed in this interpreter')
    def test_real_pdfium_native_business_job_lifecycle_and_retry(self):
        import importlib.metadata
        doc = self.register('pdfium.pdf', pdf_bytes())
        first = self.wait(self.submit([doc], options={'parser': 'native'}))
        self.assertEqual(first['status'], 'completed', first)
        result = first['result']['documents'][0]['result']
        self.assertEqual(result['engine'], 'pdfium-native-char')
        refs = result['evidence_refs']
        self.assertEqual(''.join(ref['raw_text'] for ref in refs), '600x450+/-0.5')
        self.assertTrue(all(ref['engine_version'] == importlib.metadata.version('pypdfium2') for ref in refs))
        # Exercise the actual business parser repeatedly after document closure,
        # including an exception path and replacing/deleting the source file.
        copied = Path(self.temp.name) / 'closed-retry.pdf'
        copied.write_bytes(pdf_bytes())
        source = first['sources'][0]
        opts = {'parser': 'native', 'pages': None, 'max_pages': 20}
        with self.assertRaises(recognition.RecognitionError):
            recognition.parse(copied, source, {**opts, 'pages': [2]})
        for _ in range(3):
            observed = recognition.parse(copied, source, opts)
            self.assertEqual(observed['engine'], 'pdfium-native-char')
            self.assertEqual(observed['evidence_refs'], refs)
            copied.unlink(); copied.write_bytes(pdf_bytes())
        # Cover the PDFium-only geometry adapter too, with actual PDFium rather
        # than an emulated document; hiding pdfinfo selects that real branch.
        with patch('document_recognition.shutil.which', return_value=None):
            geometry, count = recognition._pdf_geometry(copied, opts)
        self.assertEqual(count, 1); self.assertEqual(geometry[0]['page_size_pdf_points'], [200, 100])
        from workers.docling_service import Runtime
        rendered = Runtime({}).pdf_geometry(copied, [1])
        self.assertEqual(rendered[0]['page_size_pdf_points'], [200, 100])
        # Reuse a completed checkpoint in a resumed durable job. The child must
        # use this same interpreter and remain independent of context managers.
        folder = self.store.data_dir / 'recognition-jobs' / first['id']
        summary = json.loads((folder / 'job.json').read_text()); summary['status'] = 'failed'
        (folder / 'job.json').write_text(json.dumps(summary))
        with self.store.read_transaction() as con:
            retry = recognition.submit(self.store, con, self.pid, {'resume_job_id': first['id'], 'expected_revision': self.project['revision']})
        resumed = self.wait(retry)
        self.assertEqual(resumed['status'], 'completed', resumed)
        self.assertEqual(resumed['result']['evidence_refs'], first['result']['evidence_refs'])

    def test_unconfigured_models_are_not_claimed_ready(self):
        doc = self.register('input.txt', b'native')
        caps = recognition.capabilities()
        self.assertFalse(caps['docling']['available'])
        self.assertFalse(caps['paddleocr_vl']['available'])
        with self.assertRaises(recognition.RecognitionError) as caught:
            self.submit([doc], options={'parser': 'docling'})
        self.assertEqual(caught.exception.status, 503)

    def test_trusted_real_http_adapter_pins_identity_and_rejects_forged_bbox(self):
        class Worker(BaseHTTPRequestHandler):
            invalid = False
            invalid_size = False
            forged_source = False
            seen_source = None
            def do_GET(self):
                self.send({'ready': True, 'schema_version': 'document_evidence.v1', 'engine_version': 'fixture-protocol-1', 'model_revision': 'fixture-not-a-model'})
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.__class__.seen_source = base64.b64decode(payload['input']['content_base64'])
                geometry = dict(payload['source_geometry'][0])
                if self.invalid_size:
                    geometry['page_size_pdf_points'] = [201, 100]
                returned_source = dict(payload['source'])
                if self.forged_source:
                    returned_source['source_sha256'] = '0' * 64
                bbox_key = 'bbox_pdf_points' if geometry['coordinate_system'] == 'pdf_points' else 'bbox_pixels'
                self.send({'schema_version': 'document_evidence.v1', 'source': returned_source,
                           'engine_version': 'fixture-protocol-1', 'model_revision': 'fixture-not-a-model',
                           'pages': [{**geometry,
                                      'regions': [{'text_raw': 'fixture observation', bbox_key: [10, 10, 250 if self.invalid else 100, 30]}]}]})
            def send(self, value):
                body = json.dumps(value).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Worker)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        manifest = Path(self.temp.name) / 'trusted-services.json'
        service = {
            'url': f'http://127.0.0.1:{server.server_port}', 'protocol': 'kanpace-document-v1',
            'engine_version': 'fixture-protocol-1', 'model_revision': 'fixture-not-a-model', 'license': 'protocol-test', 'timeout_seconds': 5}
        manifest.write_text(json.dumps({'schema_version': 1, 'services': {'docling': service, 'paddleocr': service}}))
        try:
            with patch.dict(os.environ, {'KANPACE_RECOGNITION_SERVICE_CONFIG': str(manifest)}):
                doc = self.register('native.pdf', pdf_bytes())
                result = self.wait(self.submit([doc], options={'parser': 'docling'}))
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(Worker.seen_source, pdf_bytes())
                self.assertEqual(result['result']['evidence_refs'][0]['model_revision'], 'fixture-not-a-model')
                Worker.invalid = True
                invalid = self.wait(self.submit([doc], options={'parser': 'docling'}))
                self.assertEqual(invalid['status'], 'failed')
                self.assertEqual(invalid['result']['evidence_refs'], [])
                Worker.invalid, Worker.invalid_size = False, True
                forged = self.wait(self.submit([doc], options={'parser': 'docling'}))
                self.assertEqual(forged['status'], 'failed')
                self.assertIn('不守恒', forged['result']['documents'][0]['error']['message'])
                Worker.invalid_size, Worker.forged_source = False, True
                wrong_source = self.wait(self.submit([doc], options={'parser': 'docling'}))
                self.assertEqual(wrong_source['status'], 'failed')
                self.assertIn('来源或模型版本', wrong_source['result']['documents'][0]['error']['message'])
                Worker.forged_source = False
                if importlib.util.find_spec('PIL'):
                    from PIL import Image
                    content = io.BytesIO()
                    Image.new('RGB', (200, 100), 'white').save(content, format='PNG')
                    image = self.register('原图.png', content.getvalue())
                    observed = self.wait(self.submit([image], options={'parser': 'paddleocr'}))
                    self.assertEqual(observed['status'], 'completed', observed)
                    loc = observed['result']['evidence_refs'][0]['locator']
                    self.assertEqual(loc['kind'], 'image_region')
                    self.assertEqual(loc['bbox_pixels'], [10, 10, 100, 30])
                    self.assertEqual(loc['page_size_pixels'], [200, 100])
                    self.assertIsNone(loc['bbox_pdf_points'])
                    import order_drafts
                    normalized = order_drafts.evidence(observed['result']['evidence_refs'][0])
                    self.assertEqual(normalized['locator']['bbox_pixels'], [10, 10, 100, 30])
                    self.assertEqual(normalized['model_revision'], 'fixture-not-a-model')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_malformed_manifest_does_not_crash_status_and_scalar_json_retains_type(self):
        manifest = Path(self.temp.name) / 'malformed.json'
        manifest.write_text('[]')
        with patch.dict(os.environ, {'KANPACE_RECOGNITION_SERVICE_CONFIG': str(manifest)}):
            self.assertFalse(recognition.capabilities()['docling']['available'])
        doc = self.register('scalar.json', b'0')
        result = self.wait(self.submit([doc]))
        self.assertEqual(result['result']['evidence_refs'][0]['candidate']['value'], 0)

    def test_http_native_request_authenticated_roles_and_cross_project_job(self):
        doc = self.register('api.txt', '真实HTTP资料×18 ±0.5'.encode())
        with self.store.connect() as con:
            self.store.put(con, 'people', {'id': 'recognition_worker', 'name': '工人', 'role': '木工', 'skills': ['木工']})
        server = app.Server(('127.0.0.1', 0), self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, data=None, cookie=None):
            headers = {'Origin': base, 'Accept': 'application/json'}
            if cookie:
                headers['Cookie'] = cookie.split(';')[0]
            if data is not None:
                headers['Content-Type'] = 'application/json'
            req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.loads(response.read()), response.headers
        try:
            code, body, headers = request('/api/access/setup', {'username': 'recognition_admin', 'name': '管理员', 'password': 'isolated-recognition-admin'})
            self.assertEqual(code, 200, body)
            admin = headers['Set-Cookie']
            code, body, _ = request('/api/access/users', {'username': 'recognition_worker', 'name': '工人', 'password': 'isolated-recognition-worker', 'role': 'worker', 'person_id': 'recognition_worker'}, admin)
            self.assertEqual(code, 200, body)
            code, body, headers = request('/api/access/login', {'username': 'recognition_worker', 'password': 'isolated-recognition-worker'})
            self.assertEqual(code, 200, body)
            worker = headers['Set-Cookie']
            path = f'/api/projects/{self.pid}/recognition'
            payload = {'source_ids': ['doc:' + doc['id']], 'expected_revision': self.project['revision'], 'options': {'parser': 'native'}}
            self.assertEqual(request(path, payload)[0], 401)
            self.assertEqual(request(path, payload, worker)[0], 403)
            self.assertEqual(request(path, cookie=worker)[0], 403)
            code, body, _ = request(path, payload, admin)
            self.assertEqual(code, 202, body)
            job = self.wait(body['job'])
            code, body, _ = request(path + '/' + job['id'], cookie=admin)
            self.assertEqual(code, 200, body)
            self.assertEqual(body['job']['result']['evidence_refs'][0]['raw_text'], '真实HTTP资料×18 ±0.5')
            self.assertEqual(request(path + '/' + job['id'], cookie=worker)[0], 403)
            code, body, _ = request(f'/api/projects/{self.other["id"]}/recognition/{job["id"]}', cookie=admin)
            self.assertEqual(code, 404, body)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__':
    unittest.main()
