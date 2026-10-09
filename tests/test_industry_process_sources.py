"""Industry process-file upload → work-package review → source verification → release."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import factory_config
import operations


class IndustryProcessSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        with self.store.connect() as con:
            self.factory = operations.save_factory(self.store, con, {'name': '合成食品厂', 'factory_type': 'cabinet'})['factory']
            plan = factory_config.save_plan(self.store, con, {'factory_id': self.factory['id'], 'industry_id': 'food', 'variant_id': 'powder'})['plan']
            preview = factory_config.preview(self.store, con, {'plan_id': plan['id'], 'expected_version': plan['version']})
            self.template = factory_config.install(self.store, con, {'plan_id': plan['id'], 'expected_version': plan['version'],
                'preview_token': preview['preview_token'], 'reviewed': True, 'reviewer': '测试工艺员',
                'review_note': '本厂流程核对', 'request_id': 'process_source_install_01'})['template']
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.project = self.request('/api/projects', {'name': '合成配粉订单', 'factory_id': self.factory['id']})['project']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, path, data=None, status=200):
        req = urllib.request.Request(self.url + path, None if data is None else json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=10) as response:
                actual, result = response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                actual, result = exc.code, json.load(exc)
        self.assertEqual(actual, status, (path, result))
        return result

    def row(self, kind, identifier):
        with self.store.connect() as con:
            return self.store.get(con, kind, identifier)

    def upload(self, content='批号,配方版本,目标重量kg\nB01,R3,10.5\n', purpose='process', filename='确认工艺单.csv', status=200):
        result = self.request('/api/import', {'project_id': self.project['id'], 'filename': filename,
                             'purpose': purpose, 'content_base64': base64.b64encode(content.encode()).decode()}, status=status)
        self.project = self.row('projects', self.project['id'])
        return result

    def draft(self, document_ids, workflow=None):
        values = {f['id']: 1.25 if f['type'] == 'decimal' else '人工确认版本 R3' for f in self.template['object_fields']}
        return self.request('/api/projects/' + self.project['id'] + '/workflow', {
            'template_id': self.template['id'], 'factory_id': self.factory['id'], 'expected_revision': self.project['revision'],
            'expected_version': (workflow or {}).get('version', 0), 'scope_note': '已确认配粉批次范围，不执行配方设备参数',
            'objects': [{'code': 'B01', 'name': '配粉批次', 'quantity': 1, 'unit': '批', 'instructions': '依据工艺单 R3 核对物料及交接要求',
                         'industry_fields': values, 'document_ids': document_ids}]})['workflow']

    def review(self, workflow):
        return self.request('/api/projects/' + self.project['id'] + '/workflow/review', {
            'expected_version': workflow['version'], 'acknowledge_manual_scope': True,
            'reviewer': '测试工艺员', 'review_note': '逐对象核对本订单工艺单和对应版本'})['workflow']

    def verification(self, workflow):
        return {'note': '已在原工艺单中核对本批次、配方版本、工序边界和质量交接要求', 'workflow_id': workflow['id'],
                'expected_workflow_version': workflow['version'], 'expected_revision': self.project['revision'],
                'acknowledge_process_basis': True}

    def resolve(self, doc, workflow, status=200, **changes):
        result = self.request('/api/documents/' + doc['id'] + '/resolve', {**self.verification(workflow), **changes}, status=status)
        return result['document'] if status == 200 else result

    def release(self, status=200):
        return self.request('/api/projects/' + self.project['id'] + '/release', {}, status=status)

    def test_process_csv_does_not_become_cabinet_parts_and_complete_http_flow_can_release(self):
        result = self.upload()
        doc = result['document']
        self.assertTrue(result['archive_only'])
        self.assertEqual(result['parts'], [])
        self.assertEqual(doc['purpose'], 'process')
        self.assertFalse(doc['resolved'])
        workflow = self.draft([doc['id']])
        self.resolve(doc, workflow, status=409)
        workflow = self.review(workflow)
        blocked = self.release(status=409)
        self.assertIn('工艺依据待核验', str(blocked))
        self.resolve(doc, workflow, status=409, acknowledge_process_basis=False)
        verified = self.resolve(doc, workflow)
        self.assertTrue(verified['resolved'])
        self.assertEqual(verified['process_verification']['document_sha256'], doc['sha256'])
        self.assertEqual(verified['process_verification']['workflow_version'], workflow['version'])
        self.assertTrue(all(t['status'] == 'ready' for t in self.release()['tasks']))
        with self.store.connect() as con:
            self.assertFalse(self.store.active_parts(con, self.project['id']))

    def test_changed_file_invalidates_only_unexecuted_draft_and_requires_rebuild_recheck(self):
        doc = self.upload()['document']
        workflow = self.review(self.draft([doc['id']]))
        verified = self.resolve(doc, workflow)
        old_revision = self.project['revision']
        duplicate = self.upload()
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(self.project['revision'], old_revision)
        updated = self.upload('批号,配方版本,目标重量kg\nB01,R4,12.5\n')['document']
        self.assertEqual(self.project['revision'], old_revision + 1)
        self.assertTrue(self.row('documents', doc['id'])['superseded'])
        self.release(status=409)
        self.resolve(doc, workflow, status=409)
        draft = self.draft([updated['id']], workflow=workflow)
        reviewed = self.review(draft)
        self.resolve(updated, reviewed, status=409, expected_workflow_version=workflow['version'])
        self.resolve(updated, reviewed)
        self.assertEqual(self.release()['project']['status'], 'released')
        self.assertEqual(verified['process_verification']['document_sha256'], doc['sha256'])

    def test_work_package_must_explicitly_reference_document_and_current_version(self):
        doc = self.upload()['document']
        workflow = self.review(self.draft([]))
        blocked = self.resolve(doc, workflow, status=409)
        self.assertEqual(blocked['details']['code'], 'process_document_unlinked')
        workflow = self.review(self.draft([doc['id']], workflow=workflow))
        self.resolve(doc, workflow, status=409, expected_revision=self.project['revision'] - 1)
        self.resolve(doc, workflow, status=400, expected_workflow_version=True)
        self.resolve(doc, workflow)
        # Editing and reviewing the same objects is still a new reviewed version.
        later = self.review(self.draft([doc['id']], workflow=workflow))
        self.release(status=409)
        self.resolve(doc, later)
        self.release()

    def test_released_source_cannot_be_silently_replaced(self):
        doc = self.upload()['document']
        workflow = self.review(self.draft([doc['id']]))
        self.resolve(doc, workflow)
        self.release()
        before = deepcopy(self.row('projects', self.project['id']))
        rejected = self.upload('changed content', status=409)
        self.assertEqual(rejected['details']['code'], 'process_source_in_use')
        self.assertEqual(before, self.row('projects', self.project['id']))
        self.assertFalse(self.row('documents', doc['id']).get('superseded'))

    def test_legacy_drawing_resolution_does_not_gain_industry_archive_bypass(self):
        doc = self.upload('批号,配方版本,目标重量kg\nB01,R3,10.5\n', purpose='drawing')['document']
        result = self.request('/api/documents/' + doc['id'] + '/resolve', {'note': '仅填写说明不能替代 BOM'}, status=409)
        self.assertIn('审核部件', result['error'])
        self.assertFalse(self.row('documents', doc['id'])['resolved'])

    def test_process_purpose_requires_industry_context(self):
        legacy = self.request('/api/projects', {'name': '旧展柜项目'})['project']
        self.request('/api/import', {'project_id': legacy['id'], 'filename': '工艺.csv', 'purpose': 'process',
                     'content_base64': base64.b64encode(b'fake,process').decode()}, status=409)


if __name__ == '__main__':
    unittest.main()
