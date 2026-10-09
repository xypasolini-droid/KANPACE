"""Worker boundary tests. No learned model is installed or mocked as verified."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

from workers.docling_service import Runtime, WorkerError, create_server, load_config, top_left_bbox


class DoclingWorkerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-docling-boundary-')
        root = Path(self.temp.name)
        models = root / 'models'; models.mkdir()
        entries = []
        for name in ('det.onnx', 'rec.onnx', 'cls.onnx', 'keys.txt', 'layout.bin'):
            raw = ('not-a-model-boundary-fixture:' + name).encode()
            (models / name).write_bytes(raw)
            entries.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest()})
        manifest = root / 'models.json'; manifest.write_text(json.dumps({'files': entries}))
        self.config_path = root / 'worker.json'
        self.body = {'schema_version': 1, 'engine_version': '2.133.0', 'artifacts_path': str(models),
            'model_manifest_path': str(manifest), 'model_revision': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'license': 'boundary-fixture-not-a-license-clearance', 'token_env': 'KANPACE_TEST_WORKER_TOKEN',
            'ocr': {'det_model_path': 'det.onnx', 'rec_model_path': 'rec.onnx', 'cls_model_path': 'cls.onnx', 'rec_keys_path': 'keys.txt'}}
        self.config_path.write_text(json.dumps(self.body))
        self.env = patch.dict(os.environ, {'KANPACE_TEST_WORKER_TOKEN': 'a' * 40}); self.env.start()
    def tearDown(self):
        self.env.stop(); self.temp.cleanup()
    def test_manifest_hashes_paths_unlisted_files_and_missing_token_fail(self):
        good = load_config(self.config_path)
        self.assertEqual(good['engine_version'], '2.133.0')
        model = Path(good['artifacts_path']) / 'rec.onnx'
        original = model.read_bytes(); model.write_bytes(b'tampered')
        with self.assertRaises(WorkerError): load_config(self.config_path)
        model.write_bytes(original)
        (Path(good['artifacts_path']) / 'untracked.bin').write_bytes(b'untracked')
        with self.assertRaises(WorkerError): load_config(self.config_path)
        with patch.dict(os.environ, {'KANPACE_TEST_WORKER_TOKEN': ''}):
            with self.assertRaises(WorkerError): load_config(self.config_path)
    def test_bbox_origin_is_converted_once_and_invalid_geometry_rejected(self):
        self.assertEqual(top_left_bbox({'l': 10, 't': 180, 'r': 20, 'b': 160, 'coord_origin': 'BOTTOMLEFT'}, [100, 200]), [10, 20, 20, 40])
        self.assertEqual(top_left_bbox({'l': 10, 't': 20, 'r': 20, 'b': 40, 'coord_origin': 'TOPLEFT'}, [100, 200]), [10, 20, 20, 40])
        for box in ({'l': 10, 't': 20, 'r': 10, 'b': 40, 'coord_origin': 'TOPLEFT'},
                    {'l': 10, 't': 20, 'r': 110, 'b': 40, 'coord_origin': 'TOPLEFT'},
                    {'l': 10, 't': 20, 'r': float('nan'), 'b': 40, 'coord_origin': 'TOPLEFT'}):
            with self.assertRaises(WorkerError): top_left_bbox(box, [100, 200])
    def test_real_authenticated_http_no_autoload_never_reports_ready(self):
        runtime = Runtime(load_config(self.config_path))
        with self.assertRaises(WorkerError): create_server(runtime, '0.0.0.0', 0)
        server = create_server(runtime, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path, data=None, token=None):
            headers = {'Content-Type': 'application/json'}
            if token: headers['Authorization'] = 'Bearer ' + token
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path, headers=headers,
                data=json.dumps(data).encode() if data is not None else None)
            try: response = urllib.request.urlopen(req, timeout=3)
            except urllib.error.HTTPError as error: response = error
            with response: return response.status, json.loads(response.read())
        try:
            self.assertEqual(request('/health')[0], 401)
            self.assertEqual(request('/health', token='wrong')[0], 401)
            status, body = request('/health', token='a' * 40)
            self.assertEqual(status, 200); self.assertFalse(body['ready']); self.assertIsNone(body['selftest'])
            self.assertEqual(request('/recognize', {}, 'a' * 40)[0], 503)
            self.assertEqual(request('/load', {}, 'a' * 40)[0], 404)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
    def test_cli_drycheck_does_not_load_models_or_claim_readiness(self):
        run = subprocess.run([sys.executable, '-m', 'workers.docling_service', '--config', str(self.config_path), '--drycheck'],
                             capture_output=True, timeout=5)
        result = json.loads(run.stdout)
        self.assertTrue(result['config_valid']); self.assertFalse(result['ready']); self.assertFalse(result['models_loaded'])


if __name__ == '__main__': unittest.main()
