"""Local account tests on temporary SQLite; no real accounts or passwords created."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import access_control as access


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)
        self.handler = self.handler_for()
        access.clear_actor()
        with self.store.connect() as con:
            for identifier in ('person_a', 'person_b'):
                self.store.put(con, 'people', {'id':identifier,'name':identifier,'demo':False,'skills':['装配']})
            self.store.put(con, 'people', {'id':'demo_person','name':'测试档案','demo':True})
            self.store.put(con, 'tasks', {'id':'task_own','assignee':'person_a','quantity':2,'status':'ready'})
            self.store.put(con, 'tasks', {'id':'task_other','assignee':'person_b','quantity':2,'status':'ready'})
        self.admin_cookie = None

    def tearDown(self):
        access.clear_actor()
        self.temp.cleanup()

    def handler_for(self, path='/api/state', method='GET', cookie=None):
        handler = SimpleNamespace(server=SimpleNamespace(store=self.store), path=path, command=method, headers={})
        if cookie:
            handler.headers['Cookie'] = cookie.split(';')[0]
        handler.send_bytes = lambda status, body, mime, headers=None: setattr(handler, 'response', (status,json.loads(body),headers or {}))
        return handler

    def enable(self):
        if self.admin_cookie: return
        _, self.admin_cookie = access.setup(self.store, self.handler, {'username':'admin','name':'本地管理员','password':'example-admin-password'})
        self.admin = self.handler_for(cookie=self.admin_cookie)

    def create(self, role='worker', person='person_a', username=None):
        self.enable()
        result = access.save_user(self.store, self.admin, {'username':username or role, 'name':'测试'+role,
            'role':role,'person_id':person,'password':'example-user-password'})
        _, cookie = access.login(self.store, self.handler, {'username':username or role, 'password':'example-user-password'})
        return result['user'], cookie

    def assertDenied(self, code, action):
        with self.assertRaises(access.AccessError) as caught: action()
        self.assertEqual(caught.exception.status, code)

    def rows(self, kind):
        with self.store.connect() as con: return self.store.all(con, kind)

    def test_default_mode_is_explicit_and_keeps_local_working(self):
        actor = access.authorize(self.handler_for('/api/projects','POST'))
        self.assertEqual(actor['role'], 'local_operator')
        self.assertFalse(access.status(self.store,self.handler)['enabled'])
        self.assertIn('尚未启用', access.status(self.store,self.handler)['notice'])
        self.assertEqual(self.rows('access_users'), [])

    def test_setup_hashes_password_and_session_and_is_atomic(self):
        self.assertDenied(400, lambda:access.setup(self.store,self.handler,{'username':'admin','name':'管理员','password':'short'}))
        self.assertEqual(self.rows('access_users'), [])
        self.assertEqual(self.rows('access_config'), [])
        self.enable()
        user = self.rows('access_users')[0]
        self.assertTrue(user['password_hash'].startswith('pbkdf2_sha256$600000$'))
        self.assertTrue(access.password_matches('example-admin-password',user['password_hash']))
        raw_token = self.admin_cookie.split(';')[0].split('=',1)[1]
        session = self.rows('access_sessions')[0]
        self.assertEqual(session['id'], hashlib.sha256(raw_token.encode()).hexdigest())
        self.assertNotIn(raw_token, json.dumps(session))
        self.assertNotIn('example-admin-password', json.dumps(self.rows('access_users')))
        self.assertIn('HttpOnly',self.admin_cookie); self.assertIn('SameSite=Strict',self.admin_cookie)
        self.assertDenied(409,lambda:access.setup(self.store,self.handler,{'username':'other','name':'其他','password':'example-password'}))
        self.assertEqual(len(self.rows('access_users')),1)

    def test_anonymous_production_is_denied_but_login_assets_work(self):
        self.enable()
        for path in ('/api/state','/api/projects','/api/production','/api/documents/doc/download'):
            self.assertDenied(401, lambda p=path:access.authorize(self.handler_for(p)))
        for path in ('/','/app.js','/access-control.js','/api/access','/api/health'):
            self.assertIsNone(access.authorize(self.handler_for(path)))

    def test_encoded_and_repeated_slash_paths_cannot_bypass_login(self):
        self.enable()
        for path in ('/%61pi/state','/api//state','/%61pi///projects','/api/%70roduction', '/api/tasks/task_own/%73tatus'):
            self.assertDenied(401,lambda p=path:access.authorize(self.handler_for(p,'POST')))
        handler=self.handler_for('/%61pi//access')
        self.assertTrue(access.handle(handler))
        self.assertTrue(handler.response[1]['enabled'])

    def test_worker_can_only_report_own_assigned_tasks(self):
        _,cookie=self.create()
        for action in ('status','progress','pause','resume'):
            self.assertEqual(access.authorize(self.handler_for('/api/tasks/task_own/'+action,'POST',cookie))['person_id'],'person_a')
            self.assertDenied(403,lambda a=action:access.authorize(self.handler_for('/api/tasks/task_other/'+a,'POST',cookie)))
        for path in ('/api/tasks/task_own/assign','/api/tasks/task_own/priority','/api/projects/prj/release','/api/production/checks','/api/access/users'):
            self.assertDenied(403,lambda p=path:access.authorize(self.handler_for(p,'POST',cookie)))
        access.authorize(self.handler_for('/%61pi//tasks/task_own/%73tatus','POST',cookie))
        self.assertDenied(403,lambda:access.authorize(self.handler_for('/%61pi//tasks/task_other/%73tatus','POST',cookie)))

    def test_worker_requires_real_unique_person_binding(self):
        self.enable()
        for person in (None,'missing','demo_person'):
            self.assertDenied(400,lambda p=person:access.save_user(self.store,self.admin,{'username':'worker','name':'工人','role':'worker','person_id':p,'password':'example-password'}))
        self.create()
        self.assertDenied(409,lambda:access.save_user(self.store,self.admin,{'username':'worker2','name':'工人','role':'worker','person_id':'person_a','password':'example-password'}))

    def test_role_write_permissions_and_owner_read_only(self):
        samples = {
            'warehouse':('/api/production/materials','/api/production/inspections'),
            'quality':('/api/production/inspections','/api/production/materials'),
            'technical':('/api/projects/prj/workflow','/api/projects/prj/costs'),
            'supervisor':('/api/production/changes','/api/access/users')}
        for role,(allowed,denied) in samples.items():
            with self.subTest(role=role):
                user,cookie=self.create(role,person='person_a' if role=='quality' else None)
                access.authorize(self.handler_for(allowed,'POST',cookie))
                self.assertDenied(403,lambda:access.authorize(self.handler_for(denied,'POST',cookie)))
        _,cookie=self.create('owner',person=None)
        access.authorize(self.handler_for('/api/projects/prj/quote','GET',cookie))
        self.assertDenied(403,lambda:access.authorize(self.handler_for('/api/projects','POST',cookie)))

    def test_nonfinancial_engineering_cannot_set_or_clear_part_pricing(self):
        _,cookie=self.create('technical',person=None)
        for key in ('unit_price','pricing_unit'):
            for value in (None,'',10):
                for path,data in (('/api/parts',{key:value}), ('/%61pi//parts/part_a/review',{'edits':{key:value}})):
                    self.assertDenied(403,lambda p=path,d=data:access.authorize(self.handler_for(p,'POST',cookie),data=d))
        access.authorize(self.handler_for('/api/parts/part_a/review','POST',cookie),data={'edits':{'quantity':3,'length':250}})
        access.authorize(self.handler_for('/api/parts/part_a/review','POST',self.admin_cookie),data={'edits':{'unit_price':12}})

    def test_bom_import_drops_structured_prices_only_for_restricted_roles(self):
        import engine
        parsed=engine.parse_document('priced.csv', '名称,材料,类别,长,宽,厚,数量,表面处理,单价,计价单位\n侧板,木板,木,100,200,18,2,免漆,12,piece\n'.encode())
        original=parsed['parts'][0]
        self.assertEqual(original['unit_price'],12)
        self.assertEqual(access.filter_imported_part_prices(original),original)
        _,cookie=self.create('technical',person=None)
        access.authorize(self.handler_for('/api/import','POST',cookie),data={})
        filtered=access.filter_imported_part_prices(original)
        self.assertNotIn('unit_price',filtered);self.assertNotIn('pricing_unit',filtered)
        self.assertEqual(filtered['quantity'],original['quantity']);self.assertEqual(filtered['source'],original['source'])
        self.assertIn('unit_price',original)
        access.authorize(self.admin)
        self.assertEqual(access.filter_imported_part_prices(original),original)

    def test_financial_routes_are_denied_with_encoded_paths_and_export_formats(self):
        _,cookie=self.create()
        for path in ('/api/projects/prj/quote','/%61pi//projects/prj/%63osts','/api/production/financials',
                     '/api/projects/prj/export','/api/projects/prj/export?format=json', '/api/projects/prj/export?exportfmt=json', '/api/projects/prj/export?exportfmt=csv'):
            self.assertDenied(403,lambda p=path:access.authorize(self.handler_for(p,cookie=cookie)))
        for fmt in ('csv','bom_csv'):
            access.authorize(self.handler_for('/api/projects/prj/export?format='+fmt,cookie=cookie))

    def test_exchange_import_permission_follows_entity_including_existing_preview(self):
        _, technical = self.create('technical', person=None)
        _, warehouse = self.create('warehouse', person=None)
        _, worker = self.create()
        with self.store.connect() as con:
            for kind in ('projects', 'people', 'materials', 'progress'):
                self.store.put(con, 'exchange_previews', {'id':'preview_' + kind, 'entity_type':kind})
        for cookie,allowed in ((technical, ('projects','progress')), (warehouse, ('materials',)), (worker, ())):
            for kind in ('projects','people','materials','progress'):
                for path,data in (('/api/exchange/preview', {'entity_type':kind}), ('/%61pi//exchange/preview_'+kind+'/apply', {'entity_type':'projects'})):
                    with self.subTest(role=cookie[:20], kind=kind, path=path):
                        action=lambda:access.authorize(self.handler_for(path,'POST',cookie), data=data)
                        if kind in allowed: action()
                        else: self.assertDenied(403,action)

    def test_status_never_discloses_secret_material_or_other_users_to_worker(self):
        _,cookie=self.create()
        for handler in (self.handler,self.handler_for(cookie=cookie),self.admin):
            body=access.status(self.store,handler)
            text=json.dumps(body)
            for forbidden in ('password_hash','access_sessions','example-user-password','example-admin-password'):
                self.assertNotIn(forbidden,text)
        self.assertNotIn('users',access.status(self.store,self.handler_for(cookie=cookie)))
        self.assertIn('users',access.status(self.store,self.admin))
        self.assertFalse(access.status(self.store,self.admin)['factory_data_isolation'])

    def test_structured_finance_redaction_does_not_mutate_store_result(self):
        _,cookie=self.create()
        payload={'settings':{'hourly_rates':{'装配':85}},'projects':[{'id':'p','quote_settings':{'outsourcing_cost':20}}],
                 'parts':[{'id':'part','name':'件','quantity':2,'unit_price':12}],
                 'events':[{'action':'task_started','title':'开始'},{'action':'project_costs_updated','title':'成本 123'},
                           {'action':'access_login','title':'管理员登录'}]}
        original=copy.deepcopy(payload)
        handler=self.handler_for('/%61pi//state',cookie=cookie);access.authorize(handler)
        result=access.filter_response(handler,payload)
        self.assertEqual(payload,original)
        self.assertEqual(result['settings'],{})
        self.assertNotIn('unit_price',result['parts'][0]);self.assertEqual(result['parts'][0]['quantity'],2)
        self.assertEqual(len(result['events']),1)
        self.assertFalse(result['financial_access'])
        handler=self.handler_for('/%61pi//production',cookie=cookie);access.authorize(handler)
        result=access.filter_response(handler,{'costs':[{'amount':99}],'financials':[{'contract_amount':9}], 'economics':[{'forecast_profit':1}],
                                               'milestones':[{'amount':99}], 'changes':[{'amount':20,'estimated_cost':10,'title':'改尺寸'}]})
        for key in ('costs','financials','economics','milestones'): self.assertEqual(result[key],[])
        self.assertEqual(result['changes'],[{'title':'改尺寸'}])
        access.authorize(self.admin)
        self.assertEqual(access.filter_response(self.admin,original),original)

    def test_session_logout_expiry_and_password_reset_revoke_access(self):
        user,cookie=self.create()
        worker=self.handler_for(cookie=cookie)
        access.authorize(worker)
        _,expired_cookie=access.logout(self.store,worker)
        self.assertIn('Max-Age=0',expired_cookie)
        self.assertDenied(401,lambda:access.authorize(worker))
        _,cookie=access.login(self.store,self.handler,{'username':'worker','password':'example-user-password'})
        worker=self.handler_for(cookie=cookie)
        with patch.object(access.time,'time',return_value=time.time()+access.SESSION_SECONDS+1):
            self.assertDenied(401,lambda:access.authorize(worker))
        access.save_user(self.store,self.admin,dict(user,expected_version=user['version'],password='new-example-password'))
        self.assertDenied(401,lambda:access.authorize(worker))
        self.assertDenied(401,lambda:access.login(self.store,self.handler,{'username':'worker','password':'example-user-password'}))
        self.assertTrue(access.login(self.store,self.handler,{'username':'worker','password':'new-example-password'})[0]['user'])

    def test_departure_disables_linked_web_account_and_sessions_without_auto_rehire(self):
        with self.store.connect() as con:
            self.store.put(con, 'people', {'id': 'person_departing', 'name': '待离职工人',
                                           'skills': ['装配'], 'demo': False})
        user, cookie = self.create(role='worker', person='person_departing', username='departing')
        worker = self.handler_for('/api/state', cookie=cookie)
        access.authorize(worker)
        with self.store.connect() as con:
            self.store.save_person(con, {'employment_status': 'left'}, 'person_departing')
        saved = next(u for u in self.rows('access_users') if u['id'] == user['id'])
        self.assertFalse(saved['active'])
        self.assertTrue(all(s['revoked'] for s in self.rows('access_sessions') if s['user_id'] == user['id']))
        self.assertDenied(401, lambda: access.authorize(worker))
        self.assertDenied(401, lambda: access.login(self.store, self.handler,
                          {'username': 'departing', 'password': 'example-user-password'}))
        self.assertTrue(any(e['action'] == 'access_user_departed' for e in self.rows('events')))
        with self.store.connect() as con:
            self.store.save_person(con, {'employment_status': 'active'}, 'person_departing')
        self.assertFalse(next(u for u in self.rows('access_users') if u['id'] == user['id'])['active'])
        self.assertDenied(401, lambda: access.login(self.store, self.handler,
                          {'username': 'departing', 'password': 'example-user-password'}))
        access.save_user(self.store, self.admin, {'id': user['id'], 'expected_version': saved['version'], 'active': True})
        self.assertTrue(access.login(self.store, self.handler,
                        {'username': 'departing', 'password': 'example-user-password'})[0]['user'])

    def test_departed_person_is_denied_even_if_legacy_account_was_not_disabled(self):
        user, cookie = self.create(role='worker', person='person_a', username='legacyworker')
        with self.store.connect() as con:
            person = self.store.get(con, 'people', 'person_a')
            person['employment_status'] = 'left'
            self.store.put(con, 'people', person)
        self.assertTrue(next(u for u in self.rows('access_users') if u['id'] == user['id'])['active'])
        self.assertDenied(401, lambda: access.authorize(self.handler_for('/api/state', cookie=cookie)))
        self.assertDenied(401, lambda: access.login(self.store, self.handler,
                          {'username': 'legacyworker', 'password': 'example-user-password'}))
        self.assertDenied(409, lambda: access.save_user(self.store, self.admin,
                          {'id': user['id'], 'expected_version': user['version'], 'active': True}))

    def test_last_admin_must_be_handed_over_before_linked_person_leaves(self):
        self.enable()
        admin = access.status(self.store, self.admin)['user']
        linked = access.save_user(self.store, self.admin, {'id': admin['id'],
            'expected_version': admin['version'], 'person_id': 'person_b'})['user']
        with self.store.connect() as con:
            with self.assertRaises(access.AccessError) as blocked:
                self.store.save_person(con, {'employment_status': 'left'}, 'person_b')
        self.assertEqual(blocked.exception.status, 409)
        self.assertIsNone(next(p for p in self.rows('people') if p['id'] == 'person_b').get('employment_status'))
        access.save_user(self.store, self.admin, {'username': 'backupadmin', 'name': '备用管理员',
            'role': 'admin', 'password': 'backup-admin-password'})
        with self.store.connect() as con:
            self.store.save_person(con, {'employment_status': 'left'}, 'person_b')
        self.assertFalse(next(u for u in self.rows('access_users') if u['id'] == linked['id'])['active'])

    def test_last_admin_and_stale_updates_are_rejected(self):
        self.enable();user=access.status(self.store,self.admin)['user']
        self.assertDenied(409,lambda:access.save_user(self.store,self.admin,dict(user,expected_version=user['version'],active=False)))
        self.assertDenied(409,lambda:access.save_user(self.store,self.admin,dict(user,expected_version=user['version']-1)))
        for changes in ({'role':[]},{'username':None},{'active':'true'}):
            self.assertDenied(400,lambda c=changes:access.save_user(self.store,self.admin,dict(user,expected_version=user['version'],**c)))
        self.assertEqual(self.rows('access_users')[0]['version'],user['version'])

    def test_login_failure_limit_commits_and_does_not_create_session(self):
        self.enable()
        for _ in range(6):
            self.assertDenied(401,lambda:access.login(self.store,self.handler,{'username':'admin','password':'wrong-password'}))
        self.assertDenied(429,lambda:access.login(self.store,self.handler,{'username':'admin','password':'example-admin-password'}))
        self.assertEqual(self.rows('access_login_limits')[0]['failures'],6)
        self.assertEqual(len(self.rows('access_sessions')),1)
        with patch.object(access.time,'time',return_value=time.time()+901):
            self.assertTrue(access.login(self.store,self.handler,{'username':'admin','password':'example-admin-password'})[0]['user'])

    def test_actor_context_is_thread_local_and_cleared_for_anonymous(self):
        self.enable();access.authorize(self.admin)
        self.assertEqual(access.get_actor()['role'],'admin')
        other=[]
        thread=threading.Thread(target=lambda:other.append(access.get_actor()));thread.start();thread.join()
        self.assertEqual(other,[None])
        self.assertDenied(401,lambda:access.authorize(self.handler))
        self.assertIsNone(access.get_actor())

    def test_login_setup_handle_sends_cookie_and_safe_json(self):
        handler=self.handler_for('/%61pi//access/setup','POST')
        self.assertTrue(access.handle(handler,{'username':'admin','name':'管理员','password':'example-admin-password'}))
        self.assertEqual(handler.response[0],200)
        self.assertIn('HttpOnly',handler.response[2]['Set-Cookie'])
        self.assertNotIn('password_hash',json.dumps(handler.response[1]))
        self.assertFalse(access.handle(self.handler_for('/api/state')))


class AccessHTTPIntegrationTests(unittest.TestCase):
    def test_real_server_login_task_ownership_finance_and_bom_price_boundary(self):
        import base64
        import http.cookiejar
        import urllib.request
        import urllib.error
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_operations_e2e
        flow = test_operations_e2e.OperationsEndToEndTests()
        flow.setUp()
        self.addCleanup(flow.tearDown)
        fixture = flow.fixture(nodes=flow.simple_nodes())
        task = fixture['tasks'][0]
        flow.confirm_checks(task)
        other = flow.fixture(nodes=flow.simple_nodes())['tasks'][0]
        def client():
            return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        anonymous, admin, worker, technical = client(), client(), client(), client()
        def request(opener, path, data=None, expected=200):
            req=urllib.request.Request(flow.url+path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
            try:
                with opener.open(req,timeout=10) as response: code,payload=response.status,json.load(response)
            except urllib.error.HTTPError as error:
                with error: code,payload=error.code,json.load(error)
            self.assertEqual(code,expected,(path,payload));return payload
        request(admin,'/api/access/setup',{'username':'admin','name':'HTTP管理员','password':'integration-password'})
        request(anonymous,'/%61pi/state',expected=401)
        request(anonymous,'/api/access')['enabled']
        request(admin,'/api/access/users',{'username':'worker','name':'HTTP工人','role':'worker','person_id':fixture['person']['id'],'password':'integration-worker-password'})
        request(admin,'/api/access/users',{'username':'technical','name':'HTTP技术','role':'technical','password':'integration-technical-password'})
        request(worker,'/api/access/login',{'username':'worker','password':'integration-worker-password'})
        state=request(worker,'/api/state')
        self.assertEqual(state['settings'],{})
        request(worker,'/%61pi//projects/'+task['project_id']+'/quote',expected=403)
        request(worker,'/api/tasks/'+other['id']+'/status',{'status':'in_progress','expected_execution_version':other['execution_version']},expected=403)
        result=request(worker,'/api/tasks/'+task['id']+'/status',{'status':'in_progress','expected_execution_version':task['execution_version']})
        self.assertEqual(result['task']['status'],'in_progress')
        audits=flow.rows('events')
        actor_events=[event for event in audits if event.get('task_id')==task['id'] or event.get('details',{}).get('task_id')==task['id']]
        self.assertTrue(any('HTTP工人' in json.dumps(event,ensure_ascii=False) for event in actor_events))
        request(technical,'/api/access/login',{'username':'technical','password':'integration-technical-password'})
        request(technical,'/api/parts',{'project_id':other['project_id'],'name':'禁止价格','unit_price':None},expected=403)
        content='名称,材料,类别,长,宽,厚,数量,表面处理,单价,计价单位\n侧板,木板,木,100,200,18,2,免漆,12,piece\n'.encode()
        result=request(technical,'/api/import',{'project_id':other['project_id'],'filename':'priced.csv','content_base64':base64.b64encode(content).decode()})
        self.assertEqual(len(result['parts']),1)
        stored=flow.row('parts',result['parts'][0]['id'])
        self.assertNotIn('unit_price',stored);self.assertNotIn('pricing_unit',stored)
        request(worker,'/api/access/logout',{})
        request(worker,'/api/state',expected=401)


if __name__ == '__main__': unittest.main()
