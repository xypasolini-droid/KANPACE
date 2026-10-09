"""Provisioning tests: temporary customer stores and mocked launchd only."""
import copy
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import access_control as access
import factory_instances as instances

class FactoryInstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.parent=app.Store(Path(self.temp.name)/'controller',seed=False,empty=True)
        self.server=SimpleNamespace(store=self.parent)
        self.payload={'name':'独立测试工厂','factory_type':'cabinet','product':'展示柜',
          'admin':{'username':'factory_admin','name':'测试管理员','password':'test-unique-password-123'},'request_id':'request-test-0001'}
        access.clear_actor()
    def tearDown(self):
        access.clear_actor();self.temp.cleanup()
    def controller(self,role='admin'):
        if not access.authentication_enabled(self.parent):
            handler=SimpleNamespace(server=self.server,headers={})
            access.setup(self.parent,handler,{'username':'controller_admin','name':'临时主控管理员','password':'controller-test-password-123'})
        with self.parent.connect() as con:admin=access._users(self.parent,con)[0]
        actor={'role':role,'access_enabled':True,'id':admin['id'] if role=='admin' else None,'name':'测试','person_id':None}
        return patch.object(access,'get_actor',return_value=actor)
    def test_create_empty_independent_store_with_hashed_admin_and_private_directories(self):
        child,record=instances.create_store(self.parent,self.payload)
        self.assertNotEqual(child.db_path,self.parent.db_path)
        with child.connect() as con:
            for kind in ('people','projects','documents','parts','tasks','access_sessions'):
                self.assertEqual(child.all(con,kind),[])
            factories=child.all(con,'factories');self.assertEqual(len(factories),1)
            self.assertEqual(factories[0]['id'],record['factory_id'])
            self.assertEqual(factories[0]['name'],self.payload['name'])
            users=child.all(con,'access_users');self.assertEqual(len(users),1)
            self.assertTrue(access.password_matches(self.payload['admin']['password'],users[0]['password_hash']))
            self.assertTrue(access._config(child,con)['enabled'])
            self.assertEqual(child.settings(con)['material_rates'],{})
            self.assertEqual(child.settings(con)['hourly_rates'],{})
            self.assertNotIn('password',record);self.assertNotIn(self.payload['admin']['password'],json.dumps(record))
        for folder in (child.data_dir,child.uploads,child.data_dir/'cache',child.data_dir/'logs',instances.root_path(self.parent)):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode),0o700,str(folder))
        self.assertEqual(stat.S_IMODE(child.db_path.stat().st_mode),0o600)
        self.assertEqual(instances.assert_ready(child)['id'],record['id'])
    def test_secrets_cookie_names_and_database_are_distinct_even_with_same_username(self):
        a,_=instances.create_store(self.parent,self.payload)
        other=copy.deepcopy(self.payload);other['name']='第二个工厂'
        b,_=instances.create_store(self.parent,other)
        self.assertNotEqual(access.cookie_name(a),access.cookie_name(b))
        self.assertNotEqual(access.cookie_name(a),access.COOKIE)
        with a.connect() as con:secret_a=con.execute("SELECT value FROM config WHERE key='instance_secret'").fetchone()[0]
        with b.connect() as con:secret_b=con.execute("SELECT value FROM config WHERE key='instance_secret'").fetchone()[0]
        self.assertNotEqual(secret_a,secret_b)
        self.assertEqual(access.cookie_name(self.parent),access.COOKIE)
        reopened=app.Store(a.data_dir) # flags omitted must not seed a customer store
        self.assertEqual(access.cookie_name(reopened),access.cookie_name(a))
        with reopened.connect() as con:self.assertEqual(reopened.all(con,'people'),[]);self.assertEqual(reopened.all(con,'projects'),[])
    def test_controller_creation_requires_privileged_actor_and_child_cannot_provision(self):
        for role in ('worker','supervisor','owner','local_operator'):
            with self.controller(role),self.assertRaises(instances.InstanceError) as caught:instances.provision(self.server,self.payload)
            self.assertEqual(caught.exception.status,403)
        child,_=instances.create_store(self.parent,self.payload)
        with self.controller('admin'),self.assertRaises(instances.InstanceError):instances.provision(SimpleNamespace(store=child),self.payload)
        child_status=instances.status(child)
        self.assertTrue(child_status['isolated']);self.assertFalse(child_status['can_provision']);self.assertNotIn('instances',child_status)
    def test_provision_starts_only_after_auth_and_returns_no_secret(self):
        seen=[]
        def start(child,record):
            seen.append(instances.assert_ready(child));return 'http://127.0.0.1:19001'
        with self.controller(),patch.object(instances,'start_instance',side_effect=start):
            response=instances.provision(self.server,self.payload)
            self.assertEqual(len(seen),1)
            self.assertEqual(response['setup_url'],'http://127.0.0.1:19001/factory-setup/index.html')
            self.assertTrue(response['isolated'])
            again=instances.provision(self.server,self.payload)
            self.assertTrue(again['reused']);self.assertEqual(len(seen),2)
            self.assertEqual(response['factory_id'],again['factory_id'])
        self.assertNotIn(self.payload['admin']['password'],json.dumps(response))
        self.assertNotIn('instance_secret',json.dumps(response))
        registry=instances.root_path(self.parent)/'registry.json'
        self.assertNotIn(self.payload['admin']['password'],registry.read_text())
        self.assertEqual(stat.S_IMODE(registry.stat().st_mode),0o600)
    def test_failed_start_keeps_private_auth_and_never_returns_live_url(self):
        with self.controller(),patch.object(instances,'start_instance',side_effect=RuntimeError('private command output')):
            with self.assertRaises(instances.InstanceError) as caught:instances.provision(self.server,self.payload)
            self.assertEqual(caught.exception.status,503);self.assertNotIn('private',caught.exception.message)
        row=instances._read_registry(self.parent)[0]
        self.assertEqual(row['status'],'start_failed');self.assertIsNone(row['url'])
        child=app.Store(instances.root_path(self.parent)/row['id'],seed=False,empty=True)
        self.assertTrue(instances.assert_ready(child))
    def test_failed_start_retries_same_authenticated_store_without_duplicate_customer(self):
        with self.controller(),patch.object(instances,'start_instance',side_effect=instances.InstanceError(503,'暂时无法启动')):
            with self.assertRaises(instances.InstanceError):instances.provision(self.server,self.payload)
        previous=instances._read_registry(self.parent)[0]
        with self.controller(),patch.object(instances,'start_instance',return_value='http://127.0.0.1:19003') as starter:
            result=instances.provision(self.server,self.payload)
            self.assertTrue(result['reused']);self.assertEqual(result['instance']['id'],previous['id'])
            self.assertEqual(result['factory_id'],previous['factory_id']);self.assertEqual(starter.call_count,1)
            wrong=copy.deepcopy(self.payload);wrong['admin']['password']='different-password-123'
            with self.assertRaises(instances.InstanceError):instances.provision(self.server,wrong)
            self.assertEqual(starter.call_count,1)
        rows=instances._read_registry(self.parent);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'ready')
        self.assertEqual(len([p for p in instances.root_path(self.parent).iterdir() if p.is_dir()]),1)

    def test_payload_path_and_password_validation_happens_before_creation(self):
        invalid=[{**self.payload,'data_dir':'/tmp/injected'}, {**self.payload,'factory_type':[]},
                 {**self.payload,'admin':{**self.payload['admin'],'password':'short'}},
                 {**self.payload,'request_id':'../../path'}]
        for payload in invalid:
            with self.assertRaises((instances.InstanceError,access.AccessError)):instances.create_store(self.parent,payload)
        self.assertFalse(instances.root_path(self.parent).exists())
    def test_root_and_child_status_do_not_misrepresent_legacy_isolation(self):
        before=instances.status(self.parent);self.assertFalse(before['can_provision']);self.assertTrue(before['controller_auth_required'])
        with self.assertRaises(instances.InstanceError) as caught:instances.provision(self.server,self.payload)
        self.assertEqual(caught.exception.status,409)
        self.assertFalse(instances.root_path(self.parent).exists())
        with self.controller():
            root=instances.status(self.parent);self.assertFalse(root['isolated']);self.assertTrue(root['can_provision']);self.assertFalse(root['controller_auth_required'])
            self.assertFalse(instances.root_path(self.parent).exists())
        with self.controller('worker'):
            self.assertFalse(instances.status(self.parent)['can_provision'])
            self.assertEqual(instances.status(self.parent)['instances'],[])
    def test_launch_definition_has_separate_temp_cache_logs_and_loopback_program(self):
        child,record=instances.create_store(self.parent,self.payload)
        definition=instances.launch_definition(child,record,19002)
        self.assertEqual(definition['Umask'],0o077)
        self.assertIn('--isolated-instance',definition['ProgramArguments'])
        self.assertIn('--no-demo',definition['ProgramArguments'])
        self.assertIn(str(child.data_dir),definition['ProgramArguments'])
        self.assertTrue(definition['RunAtLoad']);self.assertTrue(definition['KeepAlive'])
        self.assertTrue(Path(definition['EnvironmentVariables']['TMPDIR']).is_relative_to(child.data_dir))
        self.assertTrue(Path(definition['StandardOutPath']).is_relative_to(child.data_dir))
        self.assertNotIn(self.payload['admin']['password'],repr(definition))
        with self.assertRaises(instances.InstanceError):app.Server(('0.0.0.0',0),child)
    def test_shared_static_allowlist_contains_application_but_no_customer_studies(self):
        for path in ('index.html','app.js','navigation-data.js','brand/brand.css','brand/KANPACE-Handoff-Black.svg','model/vendor/occt/occt-import-js.wasm','navigation-map/KANPACE-全部功能地图.svg','navigation-map/KANPACE-全部功能地图.png','navigation-map/KANPACE-全部功能地图.pdf','factory-setup/app.js'):
            self.assertTrue(instances.static_allowed(path),path)
        for path in ('studies/taiwan-jewelry/sources/pdf-1.pdf','studies/taiwan-jewelry/study.json','samples/client.csv','open-source/catalog.json','brand/provenance.json','model/../studies/private.pdf','data/private.db'):
            self.assertFalse(instances.static_allowed(path),path)
    def test_missing_auth_marker_cannot_start_as_an_isolated_service(self):
        with self.assertRaises(instances.InstanceError):instances.assert_ready(self.parent)
        child,_=instances.create_store(self.parent,self.payload)
        with child.connect() as con:con.execute("DELETE FROM entities WHERE kind='access_config'")
        with self.assertRaises(instances.InstanceError):app.Server(('127.0.0.1',0),child)

if __name__=='__main__':unittest.main()
