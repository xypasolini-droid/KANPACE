"""Model associations persist without inventing quantities or changing approval."""
import unittest
import test_api


class ModelWorkspaceTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project
    imported = test_api.APITests.imported

    def fixture(self, filename='one.stl'):
        project, source = self.imported()
        _, model = self.imported(project, filename, b'solid one\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid one')
        return project, source['parts'][0], model['document']

    def test_binding_persists_and_does_not_approve_or_create_work(self):
        project, part, doc = self.fixture()
        path = '/api/documents/' + doc['id'] + '/model-links'
        before = self.state()
        code, body = self.request(path, {'mesh_key': 'mesh-0', 'part_id': part['id']})
        self.assertEqual(code, 200, body)
        self.assertEqual(body['links']['mesh-0']['part_id'], part['id'])
        self.assertFalse(body['links']['mesh-0']['stale'])
        self.assertEqual(self.request(path)[1]['links'], body['links'])
        after = self.state()
        self.assertEqual(before['parts'], after['parts'])
        self.assertEqual(before['projects'], after['projects'])
        self.assertFalse(after['tasks'])
        event_count = len(after['events'])
        self.assertEqual(self.request(path, {'mesh_key': 'mesh-0', 'part_id': part['id']})[0], 200)
        self.assertEqual(len(self.state()['events']), event_count)
        self.assertEqual(self.request(path, {'mesh_key': 'mesh-0', 'part_id': None})[1]['links'], {})

    def test_foreign_project_and_invalid_mesh_keys_are_rejected(self):
        _, part, doc = self.fixture()
        _, foreign = self.imported()
        path = '/api/documents/' + doc['id'] + '/model-links'
        for body in [{'mesh_key': 'mesh-0', 'part_id': foreign['parts'][0]['id']},
                     {'mesh_key': '../model', 'part_id': part['id']},
                     {'mesh_key': 'mesh-01', 'part_id': part['id']},
                     {'unit': 'mm', 'mesh_key': 'mesh-0'}, {'mesh_key': 'mesh-0', 'part_id': True}]:
            self.assertEqual(self.request(path, body)[0], 400, body)
        self.assertEqual(self.request(path)[1]['links'], {})

    def test_mesh_units_are_explicit_and_fixed_formats_cannot_be_overridden(self):
        project, _, doc = self.fixture()
        path = '/api/documents/' + doc['id'] + '/model-links'
        self.assertIsNone(self.request(path)[1]['unit'])
        self.assertEqual(self.request(path, {'unit': 'inch'})[1]['unit'], 'inch')
        self.assertEqual(self.request(path, {'unit': 'pixels'})[0], 400)
        _, step = self.imported(project, 'metric.step', b'ISO-10303-21; HEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;')
        step_path = '/api/documents/' + step['document']['id'] + '/model-links'
        self.assertEqual(self.request(step_path)[1]['unit'], 'mm')
        self.assertEqual(self.request(step_path, {'unit': 'inch'})[0], 400)

    def test_changed_part_is_marked_stale_and_can_be_explicitly_relinked(self):
        _, part, doc = self.fixture()
        path = '/api/documents/' + doc['id'] + '/model-links'
        self.request(path, {'mesh_key': 'mesh-0', 'part_id': part['id']})
        code, _ = self.request('/api/parts/' + part['id'] + '/review', {'approved': False, 'edits': {'length': 1300}})
        self.assertEqual(code, 200)
        self.assertTrue(self.request(path)[1]['links']['mesh-0']['stale'])
        self.assertFalse(self.request(path, {'mesh_key': 'mesh-0', 'part_id': part['id']})[1]['links']['mesh-0']['stale'])

    def test_nonmodel_document_and_missing_document_are_rejected(self):
        _, source = self.imported()
        self.assertEqual(self.request('/api/documents/' + source['document']['id'] + '/model-links')[0], 400)
        self.assertEqual(self.request('/api/documents/doc_missing/model-links')[0], 404)


if __name__ == '__main__':
    unittest.main()
