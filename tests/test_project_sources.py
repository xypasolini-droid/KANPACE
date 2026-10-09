"""Project overview selection is explicit, pinned and production-neutral."""
from pathlib import Path
import copy
import hashlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import project_sources


class ProjectSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '隔离测试装配'})
            self.other = self.store.new_project(con, {'name': '另一个项目'})
            self.document = self.document_fixture(con, 'overall', 'assembly.step')
            self.part = self.document_fixture(con, 'part', 'part.step')

    def tearDown(self):
        self.temp.cleanup()

    def document_fixture(self, con, identifier, filename, project=None, **fields):
        content = ('ISO-10303-21; /* ' + identifier + ' */ END-ISO-10303-21;').encode()
        storage_name = identifier + '.source'
        (self.store.uploads / storage_name).write_bytes(content)
        doc = {'id': identifier, 'project_id': (project or self.project)['id'], 'filename': filename,
               'purpose': 'drawing', 'sha256': hashlib.sha256(content).hexdigest(), 'revision': 1,
               'storage_name': storage_name, **fields}
        self.store.put(con, 'documents', doc)
        return doc

    def read(self):
        with self.store.connect() as con:
            return project_sources.get_sources(self.store, con, self.project['id'])

    def select(self, document=None, **overrides):
        doc = document or self.document
        payload = {'expected_selection_version': self.read()['selection_version'],
                   'main_model_document_id': doc['id'], 'document_sha256': doc['sha256'], 'role': 'assembly', **overrides}
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            return project_sources.save_selection(self.store, con, self.project['id'], payload)

    def test_unselected_even_when_a_single_model_exists_and_later_part_does_not_replace_choice(self):
        self.assertEqual(self.read()['selection']['status'], 'unselected')
        with self.store.connect() as con:
            con.execute('DELETE FROM entities WHERE id=?', (self.part['id'],))
        self.assertEqual(len(self.read()['candidates']), 1)
        self.assertIsNone(self.read()['selection']['document_id'])
        self.select()
        with self.store.connect() as con:
            self.document_fixture(con, 'latest-part', 'latest-part.step')
        self.assertEqual(self.read()['selection']['document_id'], self.document['id'])

    def test_selection_is_persistent_and_does_not_approve_or_change_engineering_revision(self):
        before = copy.deepcopy(self.read()['project'])
        result = self.select()
        after = result['project']
        for key, value in before.items():
            self.assertEqual(value, after[key], key)
        self.assertEqual(after['main_model_source']['document_sha256'], self.document['sha256'])
        with self.store.connect() as con:
            self.assertFalse(self.store.all(con, 'tasks'))
            self.assertFalse(self.store.all(con, 'parts'))
            events = len(self.store.all(con, 'events'))
        self.assertTrue(self.select()['unchanged'])
        with self.store.connect() as con:
            self.assertEqual(len(self.store.all(con, 'events')), events)
        reloaded = app.Store(self.temp.name, seed=False, empty=True)
        with reloaded.connect() as con:
            self.assertEqual(project_sources.get_sources(reloaded, con, self.project['id'])['selection']['status'], 'selected')

    def test_foreign_render_shared_reference_demo_and_original_native_files_cannot_be_main_model(self):
        with self.store.connect() as con:
            bad = [self.document_fixture(con, 'foreign', 'outside.step', project=self.other),
                   self.document_fixture(con, 'render', 'render.glb', purpose='render'),
                   self.document_fixture(con, 'reference', 'catalog.step', shared_reference=True),
                   self.document_fixture(con, 'reference-role', 'catalog2.step', source_role='shared_reference'),
                   self.document_fixture(con, 'demo', 'sample.step', demo=True),
                   self.document_fixture(con, 'native', 'assembly.sldasm'),
                   self.document_fixture(con, 'max', 'scene.max')]
        for doc in bad:
            with self.subTest(doc=doc['id']), self.assertRaises(project_sources.ProjectSourcesError):
                self.select(doc)
        self.assertEqual(len(self.read()['candidates']), 2)
        self.assertEqual(self.read()['selection']['status'], 'unselected')

    def test_removed_missing_superseded_or_changed_selected_document_is_stale_without_automatic_replacement(self):
        self.select()
        for change in ({'superseded': True}, {'sha256': 'f' * 64}, {'revision': 2}, {'archived': True}, {'purpose': 'render'}):
            with self.subTest(change=change):
                with self.store.connect() as con:
                    self.store.put(con, 'documents', {**self.document, **change})
                state = self.read()
                self.assertEqual(state['selection']['status'], 'stale')
                self.assertEqual(state['selection']['document_id'], self.document['id'])
        with self.store.connect() as con:
            self.store.put(con, 'documents', self.document)
        (self.store.uploads / self.document['storage_name']).unlink()
        self.assertEqual(self.read()['selection']['status'], 'stale')
        with self.store.connect() as con:
            con.execute('DELETE FROM entities WHERE id=?', (self.document['id'],))
        self.assertEqual(self.read()['selection']['status'], 'stale')
        self.assertEqual(self.read()['selection']['filename'], 'assembly.step')

    def test_source_bytes_and_preview_version_are_validated(self):
        self.select()
        with self.assertRaises(project_sources.ProjectSourcesError) as error:
            self.select(expected_selection_version=0)
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(project_sources.ProjectSourcesError):
            self.select(document_sha256='0' * 64)
        (self.store.uploads / self.document['storage_name']).write_bytes(b'changed bytes')
        with self.assertRaises(project_sources.ProjectSourcesError) as error:
            self.select()
        self.assertEqual(error.exception.status, 409)

    def test_clear_is_explicit_versioned_and_closed_projects_are_read_only(self):
        self.select()
        with self.store.connect() as con:
            result = project_sources.save_selection(self.store, con, self.project['id'], {'main_model_document_id': None, 'expected_selection_version': 1})
        self.assertEqual(result['selection']['status'], 'unselected')
        self.assertEqual(result['selection_version'], 2)
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', self.project['id'])
            project['fulfillment_status'] = 'shipped'
            self.store.put(con, 'projects', project)
        self.assertEqual(self.read()['selection']['status'], 'unselected')
        with self.assertRaises(app.APIError) as error:
            self.select()
        self.assertEqual(error.exception.status, 409)

    def test_malformed_selection_input_is_rejected(self):
        for change in ({'role': []}, {'role': 'guess'}, {'main_model_document_id': True},
                       {'expected_selection_version': True}, {'unexpected': 'field'}):
            with self.subTest(change=change), self.assertRaises(project_sources.ProjectSourcesError):
                self.select(**change)


if __name__ == '__main__':
    unittest.main()
