"""Architecture contracts and rollback/authorization behavior of the new facade.

The signatures below are the public contracts recorded before the refactor;
tests do not require the historical source tree or compare implementation lines.
All behavior fixtures use temporary factories and a loopback test server.
"""
import ast
from contextlib import contextmanager
import importlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
from kanpace.core.errors import APIError
from kanpace.domain import parts as domain_parts
from kanpace.infrastructure.sqlite import SQLiteRepository
from test_agent_assistant import fixture


# Public call signatures captured from the pre-refactor Store. Defaults and
# static descriptors matter to adapters, tests, CLI tools and device callbacks.
PUBLIC_CONTRACT = {
    '__init__': '(self, data_dir, seed=True, empty=False)',
    'connect': '(self)',
    'get': '(self, con, kind, identifier)',
    'put': '(self, con, kind, item)',
    'state': '(self, con)',
    'new_project': '(self, con, data, demo=False)',
    'require_project_open': '(project)',
    'set_fulfillment': '(self, con, project_id, data)',
    'create_part': '(self, con, data)',
    'review_part': '(self, con, identifier, data)',
    'generate': '(self, con, project_id)',
    'release': '(self, con, project_id)',
    'assign': '(self, con, task_id, person_id, data=None)',
    'auto_assign': '(self, con, project_id)',
    'bump_execution': '(task)',
    'check_execution_version': "(task, data, key='expected_execution_version')",
    'remaining_minutes': '(task)',
    'execution_task': '(self, con, task_id, data=None, allow_done=False)',
    'start_blockers': '(self, con, task, ignore_task_id=None, completing=False)',
    'progress_value': '(task, value)',
    'report_progress': '(self, con, task_id, data)',
    'pause_task': '(self, con, task_id, data, legacy=False)',
    'resume_task': '(self, con, task_id, data, to_ready=False)',
    'set_priority': '(self, con, task_id, data)',
    'switch_task': '(self, con, task_id, data)',
    'set_status': '(self, con, task_id, data)',
    'handle_device_execution': '(self, frame)',
    'save_person': '(self, con, data, person_id=None)',
    'quote': '(self, con, project_id)',
}
STATIC_CONTRACT = ('require_project_open', 'bump_execution', 'check_execution_version',
                   'remaining_minutes', 'progress_value')


def application_store():
    return importlib.import_module('kanpace.application.store').Store


def imported_modules(path):
    """Inspect normal imports and literal dynamic imports, including local ones."""
    relative = path.relative_to(ROOT).with_suffix('')
    names = list(relative.parts)
    package = '.'.join(names[:-1])
    result = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level:
                module = importlib.util.resolve_name('.' * node.level + module, package)
            result.append((module, node.lineno))
            result.extend((module + '.' + alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str) and (
                isinstance(node.func, ast.Name) and node.func.id == '__import__'
                or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'
            ):
                result.append((value, node.lineno))
    return result


class LayerBoundaryTests(unittest.TestCase):
    def test_new_store_is_the_same_public_entity_and_policy_as_legacy_imports(self):
        Store = application_store()
        self.assertIs(app.Store, Store)
        self.assertEqual(Store.__module__, 'kanpace.application.store')
        self.assertIs(app.APIError, APIError)
        self.assertIs(app.part_blockers, domain_parts.part_blockers)
        tree = ast.parse((ROOT / 'app.py').read_text())
        self.assertFalse(any(isinstance(node, ast.ClassDef) and node.name == 'Store' for node in tree.body),
                         'app.py must re-export the application facade, not keep a second Store implementation')

    def test_core_domain_and_storage_do_not_import_entrypoints_or_http(self):
        violations = []
        for layer in ('core', 'domain', 'infrastructure'):
            for path in (ROOT / 'kanpace' / layer).rglob('*.py'):
                for name, line in imported_modules(path):
                    if (name == 'app' or name.startswith(('app.', 'kanpace.http'))
                            or name.startswith('kanpace.') and 'bootstrap' in name.split('.')):
                        violations.append(f'{path.relative_to(ROOT)}:{line}: {name}')
        self.assertEqual(violations, [], 'Lower layers must not depend on transport or the entrypoint')

    def test_package_layers_do_not_reverse_import_the_app_compatibility_module(self):
        violations = []
        for path in (ROOT / 'kanpace').rglob('*.py'):
            for name, line in imported_modules(path):
                if name == 'app' or name.startswith('app.'):
                    violations.append(f'{path.relative_to(ROOT)}:{line}: {name}')
        self.assertEqual(violations, [])

    def test_public_signatures_and_staticmethod_descriptors_remain_compatible(self):
        Store = application_store()
        for name, signature in PUBLIC_CONTRACT.items():
            with self.subTest(method=name):
                self.assertEqual(str(inspect.signature(getattr(Store, name))), signature)
        for name in STATIC_CONTRACT:
            with self.subTest(static=name):
                self.assertIsInstance(inspect.getattr_static(Store, name), staticmethod)

    def test_sqlite_repository_does_not_expose_manufacturing_commands(self):
        for command in ('generate', 'release', 'assign', 'switch_task', 'handle_device_execution',
                        'set_fulfillment', 'review_part', 'new_project', 'save_person'):
            with self.subTest(command=command):
                self.assertFalse(hasattr(SQLiteRepository, command))

    def test_http_handler_composes_distinct_query_command_and_transport_owners(self):
        owners = {base.__name__: base for base in app.Handler.__mro__}
        for name in ('QueryRoutes', 'CommandRoutes', 'RequestHandlerBase'):
            self.assertIn(name, owners)
            self.assertTrue(owners[name].__module__.startswith('kanpace.http.'))
        self.assertIs(app.Handler.do_GET, owners['QueryRoutes'].do_GET)
        self.assertIs(app.Handler.do_POST, owners['CommandRoutes'].do_POST)
        self.assertTrue(issubclass(app.Handler, owners['RequestHandlerBase']))


class ApplicationBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = application_store()(self.temp.name, seed=False)
        fixture(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def rows(self):
        with self.store.connect() as con:
            return [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY kind,id')]

    @contextmanager
    def server(self):
        server = app.Server(('127.0.0.1', 0), self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield 'http://127.0.0.1:' + str(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def request(self, base, path, data=None, cookie=None):
        headers = {'Accept': 'application/json', 'Origin': base}
        if cookie:
            headers['Cookie'] = cookie.split(';', 1)[0]
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(base + path, data=body, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read()), dict(response.headers)

    def test_business_services_are_composed_and_bound_to_the_same_factory_store(self):
        services = ('projects', 'engineering', 'execution', 'device_execution', 'resources',
                    'queries', 'audit', 'bootstrap')
        bound = []
        for name in services:
            with self.subTest(service=name):
                service = getattr(self.store, name)
                self.assertTrue(type(service).__module__.startswith('kanpace.application.'))
                self.assertIs(service.store, self.store)
                self.assertNotIsInstance(self.store, type(service))
                bound.append(service)
        self.assertEqual(len({id(service) for service in bound}), len(services))

    def test_static_compatibility_methods_are_callable_without_a_store(self):
        Store = application_store()
        task = {'id': 'static-contract-task', 'execution_version': 4,
                'quantity': 5, 'completed_quantity': 1,
                'remaining_quantity': 4, 'estimated_minutes': 120}
        Store.check_execution_version(task, {'expected_execution_version': 4})
        with self.assertRaises(APIError):
            Store.check_execution_version(task, {'expected_execution_version': 3})
        self.assertEqual(Store.progress_value(task, 2), 2)
        self.assertEqual(Store.remaining_minutes(task), 96)
        Store.bump_execution(task)
        self.assertEqual(task['execution_version'], 5)
        Store.require_project_open({'id': 'static-contract-project', 'fulfillment_status': 'active'})
        with self.assertRaises(APIError):
            Store.require_project_open({'id': 'static-contract-project', 'fulfillment_status': 'shipped'})

    def test_switch_failure_after_first_write_rolls_back_tasks_versions_and_audit_together(self):
        with self.store.write_transaction() as con:
            source = self.store.get(con, 'tasks', 'task_ready')
            target = dict(source, id='task_target', title='插单目标任务')
            self.store.put(con, 'tasks', target)
            source.update(status='in_progress')
            self.store.put(con, 'tasks', source)
        request = {'target_task_id': 'task_target', 'reason': 'urgent', 'note': '插单',
                   'handover_note': '已完成一件，半成品在 A 架', 'completed_quantity': 1,
                   'expected_execution_version': 7, 'target_expected_execution_version': 7}
        before = self.rows()
        original_put = self.store.put
        reached = []

        def fail_target(con, kind, item):
            reached.append((kind, item['id']))
            if kind == 'tasks' and item['id'] == 'task_target':
                raise RuntimeError('injected target persistence failure')
            return original_put(con, kind, item)

        with patch.object(self.store, 'put', side_effect=fail_target):
            with self.assertRaisesRegex(RuntimeError, 'target persistence failure'):
                with self.store.write_transaction() as con:
                    self.store.switch_task(con, 'task_ready', request)
        self.assertIn(('tasks', 'task_ready'), reached)
        self.assertTrue(any(kind == 'events' for kind, _ in reached), 'The failure must occur after the first audit write')
        self.assertEqual(self.rows(), before)
        with self.store.write_transaction() as con:
            result = self.store.switch_task(con, 'task_ready', request)
        self.assertEqual(result['task']['status'], 'blocked')
        self.assertEqual(result['task']['completed_quantity'], 1)
        self.assertEqual(result['target_task']['status'], 'in_progress')
        with self.store.read_transaction() as con:
            actions = [event['action'] for event in self.store.all(con, 'events', 'prj_a')]
        self.assertEqual(actions.count('task_paused'), 1)
        self.assertEqual(actions.count('task_switched_in'), 1)

    def test_read_transaction_rejects_business_writes_and_keeps_records(self):
        import sqlite3
        before = self.rows()
        with self.assertRaises(sqlite3.OperationalError):
            with self.store.read_transaction() as con:
                self.store.put(con, 'events', {'id': 'forbidden-read-write', 'message': 'not allowed'})
        self.assertEqual(self.rows(), before)

    def test_http_routes_retain_login_ownership_version_and_readonly_agent_boundaries(self):
        with self.server() as base:
            status, _, headers = self.request(base, '/api/access/setup',
                {'username': 'architecture_admin', 'name': '架构测试管理员', 'password': 'isolated-architecture-admin'})
            self.assertEqual(status, 200)
            admin_cookie = headers['Set-Cookie']
            status, _, _ = self.request(base, '/api/access/users',
                {'username': 'architecture_worker', 'name': '架构测试工人', 'role': 'worker',
                 'person_id': 'person_a', 'password': 'isolated-architecture-worker'}, admin_cookie)
            self.assertEqual(status, 200)
            self.assertEqual(self.request(base, '/api/state')[0], 401)
            self.assertEqual(self.request(base, '/api/tasks/task_ready/status', {'status': 'in_progress'})[0], 401)
            status, _, headers = self.request(base, '/api/access/login',
                {'username': 'architecture_worker', 'password': 'isolated-architecture-worker'})
            self.assertEqual(status, 200)
            worker_cookie = headers['Set-Cookie']
            before = self.rows()
            status, proposal, _ = self.request(base, '/api/agent/message',
                {'message': '开工 task_ready', 'context': {'role': 'admin', 'person_id': 'person_b'}}, worker_cookie)
            self.assertEqual(status, 200, proposal)
            self.assertTrue(proposal['scope']['ownTasksOnly'])
            self.assertTrue(any(action['type'] == 'task_start' for action in proposal['actions']))
            self.assertEqual(self.rows(), before, 'Agent proposal must remain read-only')
            self.assertEqual(self.request(base, '/api/tasks/task_other/status',
                {'status': 'in_progress', 'expected_execution_version': 7}, worker_cookie)[0], 403)
            self.assertEqual(self.request(base, '/api/projects/prj_a/quote', cookie=worker_cookie)[0], 403)
            self.assertEqual(self.request(base, '/api/tasks/task_ready/status',
                {'status': 'in_progress', 'expected_execution_version': 6}, worker_cookie)[0], 409)
            self.assertEqual(self.rows(), before)
            status, result, _ = self.request(base, '/api/tasks/task_ready/status',
                {'status': 'in_progress', 'expected_execution_version': 7}, worker_cookie)
            self.assertEqual(status, 200, result)
            with self.store.read_transaction() as con:
                self.assertEqual(self.store.get(con, 'tasks', 'task_ready')['status'], 'in_progress')
                self.assertEqual(self.store.get(con, 'tasks', 'task_other')['status'], 'ready')


if __name__ == '__main__':
    unittest.main()
