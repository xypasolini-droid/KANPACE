"""Control-plane target validation against temporary registered factory stores."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access_control as access
import app
import control_platform as control
import factory_config
import factory_instances as instances
import operations


class ControlPlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-control-test-')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(access.clear_actor)
        self.parent = app.Store(Path(self.temp.name) / 'controller', seed=False, empty=True)
        self.server = SimpleNamespace(store=self.parent)
        self.child, self.record = instances.create_store(self.parent, {'name': '目标测试工厂', 'factory_type': 'cabinet',
            'admin': {'username': 'child_admin', 'name': '本厂管理员', 'password': 'test-child-password-123'}})
        self.registry = instances.root_path(self.parent) / 'registry.json'
        instances._write_json(self.registry, [self.record])
        self.handler = SimpleNamespace(server=self.server, headers={})
        access.clear_actor()

    def authenticate(self):
        if not access.authentication_enabled(self.parent):
            access.setup(self.parent, self.handler, {'username': 'controller_admin', 'name': '中台测试管理员', 'password': 'test-controller-password-123'})
        with self.parent.connect() as con:
            admin = access._users(self.parent, con)[0]
        return patch.object(access, 'get_actor', return_value=access._actor(admin))

    def rows(self, store, kind):
        with store.connect() as con:
            return store.all(con, kind)

    def failure(self, function, *args, status=409):
        with self.assertRaises((instances.InstanceError, operations.OperationError)) as caught:
            function(*args)
        self.assertEqual(caught.exception.status, status, caught.exception.message)

    def test_local_controller_requires_enabled_authenticated_admin(self):
        self.failure(control.overview, self.parent)
        with self.authenticate():
            self.assertEqual(control.overview(self.parent)['factories'][0]['id'], self.record['id'])
        access.clear_actor()
        self.failure(control.overview, self.parent, status=403)
        with patch.object(access, 'get_actor', return_value={'id': 'pretend', 'role': 'admin'}):
            self.failure(control.overview, self.parent, status=403)
        with self.child.connect() as con:
            child_admin = access._users(self.child, con)[0]
        with patch.object(access, 'get_actor', return_value=access._actor(child_admin)):
            self.failure(control.overview, self.child, status=403)

    def test_registered_target_draft_update_preview_install_stays_in_child(self):
        with self.authenticate():
            target = self.record['id']
            plan = control.mutate(self.parent, target, 'plans', {'factory_id': self.record['factory_id']})['plan']
            plan = control.mutate(self.parent, target, 'plans', {'expected_version': plan['version'], 'object_label': '柜号'}, plan['id'])['plan']
            preview = control.mutate(self.parent, target, 'preview', {'plan_id': plan['id'], 'expected_version': plan['version']})
            data = {'plan_id': plan['id'], 'expected_version': plan['version'], 'preview_token': preview['preview_token'],
                    'reviewed': True, 'reviewer': '主管', 'review_note': '已核对节点和验收条件', 'request_id': 'control-install-001'}
            result = control.mutate(self.parent, target, 'install', data)
            self.assertTrue(control.mutate(self.parent, target, 'install', data)['replayed'])
            self.assertEqual(control.catalog(self.parent, target, self.record['factory_id'])['active_profile']['id'], result['profile']['id'])
        self.assertEqual(len(self.rows(self.child, 'workflow_templates')), 1)
        self.assertEqual(len(self.rows(self.child, factory_config.RECEIPT_KIND)), 1)
        for store in (self.parent, self.child):
            self.assertEqual(self.rows(store, 'projects'), [])
            self.assertEqual(self.rows(store, 'tasks'), [])
        self.assertEqual(self.rows(self.parent, factory_config.PLAN_KIND), [])

    def test_unknown_identifiers_and_path_injection_do_not_create_directories(self):
        before = sorted(p.name for p in instances.root_path(self.parent).iterdir())
        with self.authenticate():
            for identifier in ('../../elsewhere', 'inst_' + '0' * 32, self.record['id'] + '/..'):
                self.failure(control.catalog, self.parent, identifier, self.record['factory_id'], status=404)
        self.assertEqual(before, sorted(p.name for p in instances.root_path(self.parent).iterdir()))

    def test_factory_binding_blocks_wrong_input_and_existing_foreign_plan(self):
        with self.child.connect() as con:
            other = operations.save_factory(self.child, con, {'name': '伪造异厂', 'factory_type': 'cabinet'})['factory']
            # Inject an impossible-to-create record to exercise binding on read.
            self.child.put(con, factory_config.PLAN_KIND, {'id': 'foreign_plan', 'factory_id': other['id'], 'version': 1, 'status': 'draft'})
        with self.authenticate():
            self.failure(control.catalog, self.parent, self.record['id'], other['id'], status=403)
            self.failure(control.mutate, self.parent, self.record['id'], 'plans', {'factory_id': other['id']}, status=403)
            self.failure(control.mutate, self.parent, self.record['id'], 'preview', {'plan_id': 'foreign_plan', 'expected_version': 1}, status=403)
            self.failure(control.mutate, self.parent, self.record['id'], 'plans', {'expected_version': 1, 'name': 'bad'}, 'foreign_plan', status=403)

    def test_mismatched_registry_factory_id_or_scene_is_rejected(self):
        for changed in ({'factory_id': 'wrong_factory'}, {'factory_type': 'site'}):
            with self.subTest(changed=changed):
                instances._write_json(self.registry, [{**self.record, **changed}])
                with self.authenticate():
                    self.failure(control.catalog, self.parent, self.record['id'], self.record['factory_id'])

    def test_malformed_registry_is_a_controlled_error(self):
        for rows in ([None], ['not-a-record'], [{'id': self.record['id']}], [self.record, deepcopy(self.record)]):
            with self.subTest(rows=rows):
                instances._write_json(self.registry, rows)
                with self.authenticate():
                    self.failure(control.catalog, self.parent, self.record['id'], self.record['factory_id'])

    def test_symlinked_factory_folder_or_database_is_rejected(self):
        folder = self.child.data_dir
        moved = folder.with_name(folder.name + '-actual')
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        with self.authenticate():
            self.failure(control.catalog, self.parent, self.record['id'], self.record['factory_id'])
        folder.unlink()
        moved.rename(folder)
        db = folder / 'cabinet-flow.sqlite3'
        db_moved = folder / 'test-real.sqlite3'
        db.rename(db_moved)
        db.symlink_to(db_moved)
        with self.authenticate():
            self.failure(control.catalog, self.parent, self.record['id'], self.record['factory_id'])


if __name__ == '__main__':
    unittest.main()
