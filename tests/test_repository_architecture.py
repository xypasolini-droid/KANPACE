"""Persistence boundaries using temporary databases only, never factory records."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kanpace.core.constants import BASE
from kanpace.core.errors import APIError
from kanpace.core.validation import number, whole_number
from kanpace.domain.parts import part_blockers
from kanpace.infrastructure.sqlite import ClosingConnection, SQLiteRepository


class RepositoryArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = SQLiteRepository(Path(self.temp.name) / 'factory')

    def rows(self, kind='test_records'):
        with self.repository.read_transaction() as con:
            return self.repository.all(con, kind)

    def test_write_scope_commits_all_records_and_releases_connection(self):
        with self.repository.write_transaction() as con:
            self.assertIsInstance(con, ClosingConnection)
            self.assertTrue(con.in_transaction)
            self.assertEqual(con.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(con.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.repository.put(con, 'test_records', {'id': 'first', 'value': 1})
            self.repository.put(con, 'test_records', {'id': 'second', 'value': 2})
        self.assertEqual([row['id'] for row in self.rows()], ['first', 'second'])
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')

    def test_failed_command_rolls_back_all_records_and_releases_connection(self):
        with self.assertRaisesRegex(ValueError, 'failed after related writes'):
            with self.repository.write_transaction() as con:
                self.repository.put(con, 'test_records', {'id': 'task', 'value': 1})
                self.repository.put(con, 'test_records', {'id': 'event', 'value': 2})
                raise ValueError('failed after related writes')
        self.assertEqual(self.rows(), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')
        # A failed command must not leave the next request marked as nested.
        with self.repository.write_transaction() as next_con:
            self.repository.put(next_con, 'test_records', {'id': 'retry', 'value': 3})
        self.assertEqual(self.rows()[0]['id'], 'retry')

    def test_read_scope_rejects_writes_and_keeps_no_partial_record(self):
        with self.assertRaises(sqlite3.OperationalError):
            with self.repository.read_transaction() as con:
                self.assertTrue(con.in_transaction)
                self.repository.put(con, 'test_records', {'id': 'forbidden'})
        self.assertEqual(self.rows(), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')

    def test_snapshot_does_not_mix_before_and_after_another_request(self):
        def write_new_record():
            with self.repository.write_transaction() as writer:
                self.repository.put(writer, 'test_records', {'id': 'new'})

        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.repository.read_transaction() as con:
                self.assertEqual(self.repository.all(con, 'test_records'), [])
                executor.submit(write_new_record).result(timeout=5)
                self.assertEqual(self.repository.all(con, 'test_records'), [])
        self.assertEqual(self.rows(), [{'id': 'new'}])

    def test_concurrent_write_scopes_serialize_read_modify_write(self):
        with self.repository.write_transaction() as con:
            self.repository.put(con, 'test_records', {'id': 'counter', 'value': 0})
        barrier = threading.Barrier(2)

        def increment():
            barrier.wait(timeout=5)
            for _ in range(12):
                with self.repository.write_transaction() as con:
                    row = self.repository.get(con, 'test_records', 'counter')
                    row['value'] += 1
                    self.repository.put(con, 'test_records', row)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(increment) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.rows()[0]['value'], 24)

    def test_nested_scope_cannot_commit_a_partial_command(self):
        for nested in (self.repository.write_transaction, self.repository.read_transaction):
            with self.subTest(nested=nested.__name__):
                with self.assertRaisesRegex(RuntimeError, 'reuse the current connection'):
                    with self.repository.write_transaction() as con:
                        self.repository.put(con, 'test_records', {'id': 'must-rollback'})
                        with nested():
                            self.fail('Nested scopes must reject before opening another transaction')
                self.assertEqual(self.rows(), [])

    def test_another_repository_for_same_database_cannot_bypass_nested_guard(self):
        other = SQLiteRepository(self.repository.data_dir)
        with self.repository.read_transaction() as con:
            with self.assertRaisesRegex(RuntimeError, 'Nested transaction'):
                with other.write_transaction():
                    self.fail('The database, not the wrapper identity, is the boundary')
            self.assertEqual(con.execute('SELECT 1').fetchone()[0], 1)

    def test_separate_factory_databases_allow_same_record_id_without_sharing(self):
        other = SQLiteRepository(Path(self.temp.name) / 'another-factory')
        with self.repository.write_transaction() as own_con:
            self.repository.put(own_con, 'test_records', {'id': 'same', 'value': 'A'})
            with other.write_transaction() as other_con:
                other.put(other_con, 'test_records', {'id': 'same', 'value': 'B'})
        self.assertEqual(self.rows()[0]['value'], 'A')
        with other.read_transaction() as con:
            self.assertEqual(other.get(con, 'test_records', 'same')['value'], 'B')

    def test_legacy_read_projection_adds_defaults_without_writing_data_or_events(self):
        raw_task = {'id': 'legacy-task', 'project_id': 'legacy-project', 'title': '合成任务',
                    'trade': '木工', 'hours': 1, 'quantity': 4, 'status': 'done'}
        raw_project = {'id': 'legacy-project', 'name': '隔离测试'}
        encoded = json.dumps(raw_task, ensure_ascii=False)
        with self.repository.write_transaction() as con:
            con.execute('INSERT INTO entities VALUES (?,?,?,?)', ('tasks', raw_task['id'], raw_task['project_id'], encoded))
            con.execute('INSERT INTO entities VALUES (?,?,?,?)', ('projects', raw_project['id'], None, json.dumps(raw_project)))
        with self.repository.read_transaction() as con:
            task = self.repository.get(con, 'tasks', raw_task['id'])
            project = self.repository.get(con, 'projects', raw_project['id'])
            self.assertEqual(task['completed_quantity'], 4)
            self.assertEqual(task['remaining_quantity'], 0)
            self.assertFalse(task['progress_recorded'])
            self.assertEqual(task['execution_version'], 0)
            self.assertEqual(project['factory_type'], 'cabinet')
            self.assertEqual(con.execute('SELECT data FROM entities WHERE id=?', (raw_task['id'],)).fetchone()[0], encoded)
            self.assertEqual(self.repository.all(con, 'events'), [])

    def test_repository_loads_identity_without_creating_business_defaults(self):
        with self.repository.read_transaction() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM config').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 0)
        with self.repository.write_transaction() as con:
            con.execute('INSERT INTO config VALUES (?,?)', ('factory_instance', json.dumps({'id': 'isolated-test'})))
        reopened = SQLiteRepository(self.repository.data_dir)
        self.assertEqual(reopened.instance_id, 'isolated-test')
        with reopened.read_transaction() as con:
            self.assertEqual(reopened.all(con, 'people'), [])
            self.assertEqual(reopened.all(con, 'projects'), [])
            self.assertIsNone(con.execute("SELECT value FROM config WHERE key='settings'").fetchone())

    def test_repository_rejects_nonfinite_json_without_leaving_related_records(self):
        with self.assertRaises(ValueError):
            with self.repository.write_transaction() as con:
                self.repository.put(con, 'test_records', {'id': 'related'})
                self.repository.put(con, 'test_records', {'id': 'invalid', 'amount': float('nan')})
        self.assertEqual(self.rows(), [])

    def test_domain_input_rules_keep_integral_quantity_and_real_bom_requirements(self):
        for value in (True, float('inf'), float('nan'), -1):
            with self.subTest(value=value), self.assertRaises(APIError):
                number(value, '数量')
        with self.assertRaises(APIError):
            whole_number(0.5, '完成数量')
        self.assertEqual(whole_number(2.0, '完成数量'), 2)
        blockers = part_blockers({'name': '合成侧板', 'draft_only': True})
        self.assertEqual(len(blockers), 1)
        self.assertIn('生产 BOM', blockers[0])

    def test_core_and_persistence_modules_do_not_import_server_entrypoint(self):
        self.assertEqual(BASE, Path(__file__).resolve().parents[1])
        modules = [BASE / 'kanpace' / subdir / name for subdir, name in (
            ('core', 'errors.py'), ('core', 'constants.py'), ('core', 'validation.py'),
            ('core', 'records.py'), ('domain', 'parts.py'), ('infrastructure', 'sqlite.py'))]
        for module in modules:
            tree = ast.parse(module.read_text())
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module or '')
            self.assertFalse(any(name == 'app' or name.startswith('kanpace.http') for name in imports), str(module))


class ApplicationBootstrapTests(unittest.TestCase):
    def setUp(self):
        from kanpace.application.store import Store
        self.Store = Store
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_default_application_initializes_original_demo_and_reopen_is_idempotent(self):
        from kanpace.core.constants import DEFAULT_SETTINGS, ROLES
        store = self.Store(self.root)
        with store.read_transaction() as con:
            self.assertEqual(store.settings(con), DEFAULT_SETTINGS)
            people = store.all(con, 'people')
            self.assertEqual([p['role'] for p in people], ROLES)
            self.assertTrue(all(p['demo'] for p in people))
            projects = store.all(con, 'projects')
            self.assertEqual(len(projects), 1)
            self.assertTrue(projects[0]['demo'])
            self.assertEqual(projects[0]['status'], 'released')
            self.assertEqual(len(store.active_parts(con, projects[0]['id'])), 6)
            self.assertGreater(len(store.active_tasks(con, projects[0]['id'])), 0)
            before = [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY id')]
        reopened = self.Store(self.root)
        with reopened.read_transaction() as con:
            after = [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY id')]
            self.assertEqual(after, before)

    def test_seed_false_preserves_legacy_people_defaults_without_demo_order(self):
        from kanpace.core.constants import DEFAULT_SETTINGS, ROLES
        store = self.Store(self.root, seed=False)
        with store.read_transaction() as con:
            self.assertEqual(store.settings(con), DEFAULT_SETTINGS)
            self.assertEqual([p['role'] for p in store.all(con, 'people')], ROLES)
            for kind in ('projects', 'parts', 'tasks', 'events'):
                self.assertEqual(store.all(con, kind), [])

    def test_empty_application_has_no_demo_or_assumed_factory_prices(self):
        store = self.Store(self.root, empty=True)
        with store.read_transaction() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 0)
            settings = store.settings(con)
            self.assertEqual(settings['material_rates'], {})
            self.assertEqual(settings['hourly_rates'], {})
            self.assertFalse(settings['rates_confirmed'])

    def test_persisted_factory_marker_overrides_default_seed_and_keeps_local_settings(self):
        repository = SQLiteRepository(self.root)
        existing_settings = {'material_rates': {'wood': {'unit_price': 123}}, 'currency': 'CNY'}
        with repository.write_transaction() as con:
            con.execute('INSERT INTO config VALUES (?,?)', ('factory_instance', json.dumps({'id': 'isolated-test'})))
            con.execute('INSERT INTO config VALUES (?,?)', ('settings', json.dumps(existing_settings)))
        reopened = self.Store(self.root)
        self.assertEqual(reopened.instance_id, 'isolated-test')
        with reopened.read_transaction() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 0)
            self.assertEqual(reopened.settings(con), existing_settings)

    def test_marked_factory_without_settings_only_receives_empty_local_defaults(self):
        repository = SQLiteRepository(self.root)
        with repository.write_transaction() as con:
            con.execute('INSERT INTO config VALUES (?,?)', ('factory_instance', json.dumps({'id': 'isolated-test'})))
        store = self.Store(self.root)
        with store.read_transaction() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 0)
            self.assertEqual(store.settings(con)['material_rates'], {})
            self.assertEqual(store.settings(con)['hourly_rates'], {})

    def test_failed_seed_rolls_back_settings_people_orders_and_events_together(self):
        from kanpace.application.bootstrap import BootstrapService

        def fail_after_partial_seed(service, con):
            self.assertTrue(con.in_transaction)
            service.store.new_project(con, {'name': '必须回滚的合成项目'}, demo=True)
            raise RuntimeError('Synthetic seed failure')

        with patch.object(BootstrapService, 'seed', fail_after_partial_seed):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic seed failure'):
                self.Store(self.root)
        repository = SQLiteRepository(self.root)
        with repository.read_transaction() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM config').fetchone()[0], 0)
        # A recovered application starts normally after the atomic rollback.
        recovered = self.Store(self.root, empty=True)
        with recovered.read_transaction() as con:
            self.assertEqual(recovered.settings(con)['material_rates'], {})


if __name__ == '__main__':
    unittest.main()
