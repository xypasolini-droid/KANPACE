"""HTTP cross-source matching with actual EngineeringJobs summary/result files."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class RealJobFileDrawingMatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-drawing-match-files-')
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '合成跨源图纸项目'})
            for identifier, filename, content in (
                    ('cad_doc', '柜体.step', b'synthetic-step-registered-source'),
                    ('ocr_doc', '柜体施工图.pdf', b'synthetic-pdf-registered-source')):
                doc = {'id': identifier, 'project_id': self.project['id'],
                       'filename': filename, 'storage_name': filename,
                       'purpose': 'drawing', 'sha256': hashlib.sha256(content).hexdigest()}
                self.store.put(con, 'documents', doc)
                (self.store.uploads / filename).write_bytes(content)
        self.cad_id = 'eng_' + 'a' * 32
        self.ocr_id = 'eng_' + 'b' * 32
        self._job(self.cad_id, 'cad', 'cad_doc', '柜体.step', {
            'engine': 'synthetic Open CASCADE fixture', 'format': 'STEP',
            'output_length_unit': 'mm', 'source_length_units': ['MM'],
            'parts': [{'definition_id': '0:1:4', 'instance_path': '0:1:1/0:1:4',
                       'name': 'L-01', 'valid': True, 'solid_count': 1,
                       'bbox_extents_mm': [600, 450, 18]}]})
        self._job(self.ocr_id, 'ocr', 'ocr_doc', '柜体施工图.pdf', {
            'engine': 'synthetic PaddleOCR fixture',
            'pages': [{'page': 3, 'width': 1400, 'height': 1000, 'regions': [
                {'page': 3, 'text': 'L-01 左侧板 598×448×18mm', 'score': .97,
                 'bbox': [100, 200, 500, 245], 'coordinate_system': 'pixels_top_left'}]}]})
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _job(self, identifier, kind, doc_id, filename, result):
        with self.store.connect() as con:
            doc = self.store.get(con, 'documents', doc_id)
        root = self.store.data_dir / 'engineering-jobs' / identifier
        root.mkdir(parents=True)
        job = {'id': identifier, 'kind': kind, 'status': 'completed',
               'created_at': '2026-09-23T00:00:00Z', 'updated_at': '2026-09-23T00:01:00Z',
               'metadata': {'project_id': self.project['id'], 'document_id': doc_id,
                            'source_id': 'doc:' + doc_id, 'source_label': filename},
               'source': {'filename': filename, 'sha256': doc['sha256']}}
        (root / 'job.json').write_text(json.dumps(job, ensure_ascii=False))
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def test_real_list_summary_then_full_ocr_result_produces_evidence(self):
        from engineering_engines import EngineeringJobs
        manager = EngineeringJobs(self.store.data_dir)
        self.assertTrue(all('result' not in summary for summary in manager.list()))
        url = (f'http://127.0.0.1:{self.server.server_port}/api/projects/{self.project["id"]}'
               f'/engineering/{self.cad_id}/drawing-matches')
        with urllib.request.urlopen(url, timeout=10) as response:
            self.assertEqual(response.status, 200)
            body = json.load(response)
        self.assertEqual(body['ocr_job_count'], 1)
        row = body['matches'][0]
        self.assertEqual(row['name'], 'L-01')
        self.assertEqual(row['match_status'], 'matched')
        evidence = row['drawing_evidence'][0]
        self.assertEqual(evidence['job_id'], self.ocr_id)
        self.assertEqual((evidence['page'], evidence['region_index']), (3, 0))
        self.assertEqual(evidence['dimension_candidates'][0]['values'], [598.0, 448.0, 18.0])
        with self.store.connect() as con:
            self.assertEqual(self.store.all(con, 'parts', self.project['id']), [])
            self.assertEqual(self.store.all(con, 'tasks', self.project['id']), [])


if __name__ == '__main__':
    unittest.main()
