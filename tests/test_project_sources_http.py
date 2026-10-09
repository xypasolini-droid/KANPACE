"""HTTP authorization and persistence for the main model selector, isolated DB."""
import hashlib
import unittest
import test_access_http


class ProjectSourcesHTTPTests(unittest.TestCase):
    setUp = test_access_http.AccessHTTPTests.setUp
    tearDown = test_access_http.AccessHTTPTests.tearDown
    request = test_access_http.AccessHTTPTests.request
    setup_admin = test_access_http.AccessHTTPTests.setup_admin
    account = test_access_http.AccessHTTPTests.account

    def fixture(self):
        content = b'ISO-10303-21; END-ISO-10303-21;'
        doc = {'id': 'source-overall', 'project_id': self.project['id'], 'filename': 'overall.step',
               'sha256': hashlib.sha256(content).hexdigest(), 'revision': 1, 'format': 'STEP',
               'purpose': 'drawing', 'storage_name': 'source-overall.source'}
        (self.store.uploads / doc['storage_name']).write_bytes(content)
        with self.store.connect() as con:
            self.store.put(con, 'documents', doc)
        return '/api/projects/' + self.project['id'] + '/sources', {
            'expected_selection_version': 0, 'main_model_document_id': doc['id'],
            'document_sha256': doc['sha256'], 'role': 'assembly'}

    def test_worker_and_readonly_owner_cannot_change_selection_technical_can(self):
        path, payload = self.fixture()
        _, worker_cookie = self.account('worker', 'qa_model_worker', 'qa_worker_a')
        _, owner_cookie = self.account('owner', 'qa_model_owner')
        _, technical_cookie = self.account('technical', 'qa_model_technical')
        self.assertEqual(self.request(path)[0], 401)
        for cookie in (worker_cookie, owner_cookie):
            self.assertEqual(self.request(path, cookie=cookie)[0], 200)
            self.assertEqual(self.request(path, payload, cookie)[0], 403)
        code, result, _ = self.request(path, payload, technical_cookie)
        self.assertEqual(code, 200, result)
        self.assertEqual(result['selection']['status'], 'selected')
        self.assertNotIn('quote_settings', result['project'])
        self.assertEqual(result['project']['revision'], 1)
        self.assertEqual(result['project']['released_revision'], 1)
        self.assertEqual(self.request(path, payload, technical_cookie)[0], 409)
        self.assertEqual(self.request(path, {'expected_selection_version': 1, 'main_model_document_id': None}, technical_cookie)[1]['selection']['status'], 'unselected')


if __name__ == '__main__':
    unittest.main()
