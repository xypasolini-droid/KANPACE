"""Independent two-customer isolation checks through real temporary HTTP servers.

Uses the actual provision-store helper but never starts launchd, touches the live
data directory, opens a serial port, or sends customer data outside loopback.
"""
import http.cookiejar
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import app
import access_control
import factory_instances


class FactoryInstanceIsolationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-isolation-qa-')
        self.addCleanup(self.temp.cleanup)
        self.parent = app.Store(Path(self.temp.name) / 'controller', seed=False, empty=True)
        with self.parent.connect() as con:
            self.parent.put(con, 'projects', {'id':'parent_private', 'name':'ROOT_PRIVATE_ORDER', 'revision':1})
            self.parent.put(con, 'people', {'id':'parent_person', 'name':'ROOT_PRIVATE_PERSON', 'demo':False})
        (self.parent.uploads / 'parent-private.txt').write_text('ROOT_PRIVATE_DRAWING', encoding='utf-8')
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar))
        self.plain_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.stores, self.records, self.servers, self.threads, self.bases = {}, {}, {}, {}, {}
        self.passwords = {'A':'qa-only-A-password-92831', 'B':'qa-only-B-password-72831'}
        self.cookies, self.images = {}, {}
        for label in ('A', 'B'):
            store, record = factory_instances.create_store(self.parent, {
                'name':label+'_PRIVATE_FACTORY', 'factory_type':'cabinet', 'product':'综合展柜',
                'admin':{'username':'qa_admin', 'name':label+'_PRIVATE_ADMIN', 'password':self.passwords[label]},
            })
            self.stores[label], self.records[label] = store, record
            with store.connect() as con:
                # Validate that provision does not copy demo or prior client data.
                self.assertEqual(store.all(con, 'projects'), [])
                self.assertEqual(store.all(con, 'people'), [])
                self.assertEqual(len(store.all(con, 'factories')), 1)
                self.assertEqual(store.all(con, 'access_sessions'), [])
            self._seed_customer(label)
            server = app.Server(('127.0.0.1', 0), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers[label], self.threads[label] = server, thread
            self.bases[label] = 'http://127.0.0.1:' + str(server.server_port)
            self.addCleanup(self._stop, server, thread)
            status, result, headers = self.request(label, '/api/access/login', {
                'username':'qa_admin', 'password':self.passwords[label]})
            self.assertEqual(status, 200, result)
            self.cookies[label] = headers['Set-Cookie'].split(';', 1)[0]

    @staticmethod
    def _stop(server, thread):
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    def _seed_customer(self, label):
        store = self.stores[label]
        buffer = io.BytesIO()
        Image.new('RGB', (16, 12), 'red' if label == 'A' else 'blue').save(buffer, 'PNG')
        self.images[label] = buffer.getvalue()
        (store.uploads / 'same-source.png').write_bytes(self.images[label])
        assets = store.data_dir / 'drawing-previews' / 'assets'; assets.mkdir(exist_ok=True)
        (assets / ('a' * 64 + '.png')).write_bytes(self.images[label])
        manifest = {'projects':{'shared_project':{'sources':[{'id':'source', 'filename':label+'_PRIVATE_SOURCE',
                    'url':'/api/drawing-media/assets/'+'a'*64+'.png'}], 'parts':{}, 'renders':[]}}}
        (store.data_dir / 'drawing-previews' / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        # Both customers deliberately use the same device ID and relative path.
        secrets = {'same-device':{'token':label+'_DEVICE_SECRET_NOT_PUBLIC', 'ssid':label+'_WiFi', 'host':None}}
        (store.data_dir / 'device-secrets.json').write_text(json.dumps(secrets), encoding='utf-8')
        with store.connect() as con:
            store.put(con, 'projects', {'id':'shared_project', 'name':label+'_PRIVATE_ORDER', 'client':label+'_PRIVATE_CUSTOMER',
                'factory_type':'cabinet', 'factory_id':self.records[label]['factory_id'], 'revision':1, 'status':'released',
                'released_revision':1, 'due_date':'2099-01-01', 'demo':False, 'fulfillment_status':'active'})
            store.put(con, 'tasks', {'id':'shared_task', 'project_id':'shared_project', 'title':label+'_PRIVATE_TASK',
                'trade':'木工', 'process':'cut', 'status':'ready', 'revision':1, 'quantity':2, 'completed_quantity':0,
                'hours':1, 'priority':0, 'dependencies':[], 'execution_version':0, 'demo':False, 'archived':False})
            store.put(con, 'documents', {'id':'shared_document', 'project_id':'shared_project', 'filename':label+'_PRIVATE_DRAWING.png',
                'storage_name':'same-source.png', 'purpose':'render', 'image':{'mime_type':'image/png','width':16,'height':12},
                'revision':1, 'demo':False, 'status':'parsed'})

    def request(self, label, path, data=None, *, cookie=None, anonymous=False, headers=None):
        request_headers = {'Origin':self.bases[label]}
        request_headers.update(headers or {})
        if cookie is not None:
            request_headers['Cookie'] = cookie
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8')
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.bases[label] + path, data=body, headers=request_headers)
        opener = self.plain_opener if anonymous or cookie is not None else self.opener
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw, headers = response.read(), dict(response.headers)
            result = json.loads(raw) if headers.get('Content-Type','').startswith('application/json') else raw
            return response.status, result, headers

    def test_two_instance_cookies_coexist_and_logout_only_clears_its_own_session(self):
        names = {cookie.name for cookie in self.jar}
        self.assertEqual(names, {access_control.cookie_name(store) for store in self.stores.values()})
        self.assertEqual(len(names), 2)
        for label in ('A','B'):
            status, data, _ = self.request(label, '/api/access')
            self.assertEqual(status, 200)
            self.assertEqual(data['user']['name'], label+'_PRIVATE_ADMIN')
            self.assertTrue(data['factory_data_isolation'])
        self.assertEqual(self.request('A', '/api/access/logout', {})[0], 200)
        self.assertEqual(self.request('A', '/api/state')[0], 401)
        self.assertEqual(self.request('B', '/api/state')[0], 200)
        self.assertEqual({cookie.name for cookie in self.jar}, {access_control.cookie_name(self.stores['B'])})

    def test_foreign_cookie_is_rejected_even_when_username_and_business_ids_match(self):
        for source, target in [('A','B'),('B','A')]:
            self.assertEqual(self.request(target, '/api/state', cookie=self.cookies[source])[0], 401)
            # Copying a token under the target's cookie name also fails its DB lookup.
            token = self.cookies[source].split('=',1)[1]
            disguised = access_control.cookie_name(self.stores[target])+'='+token
            self.assertEqual(self.request(target, '/api/state', cookie=disguised)[0], 401)
            self.assertEqual(self.request(target, '/api/agent/message', {'message':'今天先做什么'}, cookie=disguised)[0], 401)

    def test_same_project_and_task_ids_remain_separate_in_state_export_bi_and_agent(self):
        for label, other in [('A','B'),('B','A')]:
            for path in ['/api/state', '/api/projects/shared_project/export?format=json',
                         '/api/analytics?project_id=shared_project', '/api/exchange/export?entity_type=projects&format=csv',
                         '/api/tasks/queue?project_id=shared_project']:
                status, result, _ = self.request(label, path)
                self.assertEqual(status, 200, (path, result))
                text = result.decode('utf-8-sig') if isinstance(result, bytes) else json.dumps(result, ensure_ascii=False)
                self.assertNotIn(other+'_PRIVATE_', text, path)
                self.assertNotIn('ROOT_PRIVATE_', text, path)
                self.assertIn(label+'_PRIVATE_', text, path)
            status, result, _ = self.request(label, '/api/agent/message', {
                'message':'有哪些待办任务', 'project_id':'shared_project', 'factory_type':'cabinet'})
            self.assertEqual(status, 200, result)
            text = json.dumps(result, ensure_ascii=False)
            self.assertIn(label+'_PRIVATE_TASK', text)
            self.assertNotIn(other+'_PRIVATE_', text)
            self.assertNotIn('ROOT_PRIVATE_', text)

    def test_confirmed_task_action_with_colliding_id_only_updates_its_own_store(self):
        code, result, _ = self.request('B', '/api/tasks/shared_task/priority', {
            'priority':2, 'reason':'B 客户内的加急确认', 'expected_execution_version':0})
        self.assertEqual(code, 200, result)
        with self.stores['A'].connect() as con:
            a = self.stores['A'].get(con, 'tasks', 'shared_task')
        with self.stores['B'].connect() as con:
            b = self.stores['B'].get(con, 'tasks', 'shared_task')
        self.assertEqual((a['priority'],a['execution_version']), (0,0))
        self.assertEqual((b['priority'],b['execution_version']), (2,1))

    def test_same_document_and_cache_urls_return_only_own_bytes_and_manifest(self):
        for label, other in [('A','B'),('B','A')]:
            for path in ['/api/documents/shared_document/download','/api/documents/shared_document/image',
                         '/api/documents/shared_document/badge-image','/api/drawing-media/assets/'+'a'*64+'.png']:
                code, result, _ = self.request(label,path)
                self.assertEqual(code,200,(path,result));self.assertEqual(result,self.images[label]);self.assertNotEqual(result,self.images[other])
                self.assertEqual(self.request(label,path,anonymous=True)[0],401)
            code, result, _ = self.request(label,'/api/projects/shared_project/drawing-media')
            self.assertEqual(code,200)
            text=json.dumps(result,ensure_ascii=False)
            self.assertIn(label+'_PRIVATE_',text);self.assertNotIn(other+'_PRIVATE_',text)

    def test_document_and_cache_symlinks_cannot_read_sibling_customer_files(self):
        store=self.stores['A'];outside=self.stores['B'].uploads/'same-source.png'
        link=store.uploads/'cross-instance.png';link.symlink_to(outside)
        with store.connect() as con:
            doc=store.get(con,'documents','shared_document');doc['storage_name']=link.name;store.put(con,'documents',doc)
        for action in ['download','image','badge-image','preview','preview-image']:
            self.assertEqual(self.request('A','/api/documents/shared_document/'+action)[0],404,action)
        cache=store.data_dir/'drawing-previews'/'assets'/('b'*64+'.png');cache.symlink_to(outside)
        self.assertEqual(self.request('A','/api/drawing-media/assets/'+cache.name)[0],404)

    def test_child_cannot_serve_controller_private_static_studies_or_path_variants(self):
        private=['/studies/taiwan-jewelry/sources/pdf-1.pdf','/studies/taiwan-jewelry/study.json',
                 '/%73tudies/taiwan-jewelry/sources/pdf-1.pdf','/model/../studies/taiwan-jewelry/sources/pdf-1.pdf',
                 '/model/%2e%2e/studies/taiwan-jewelry/sources/pdf-1.pdf','/brand/provenance.json',
                 '/open-source/catalog.json','/integrations/catalog.json']
        for path in private:
            for anonymous in (True,False):
                self.assertEqual(self.request('A',path,anonymous=anonymous)[0],404,path)
        for path in ['/','/navigation-data.js','/navigation-map/index.html','/brand/KANPACE-Handoff-Black.svg']:
            self.assertEqual(self.request('A',path,anonymous=True)[0],200,path)

    def test_customer_admin_cannot_list_or_create_other_customer_instances(self):
        code,data,_=self.request('A','/api/factory-instances/status')
        self.assertEqual(code,200);self.assertTrue(data['isolated']);self.assertFalse(data['can_provision'])
        self.assertNotIn('instances',data)
        text=json.dumps(data)
        self.assertNotIn(self.records['B']['id'],text);self.assertNotIn('B_PRIVATE_FACTORY',text)
        self.assertEqual(self.request('A','/api/factory-instances/provision',{
            'name':'forbidden','factory_type':'cabinet','admin':{'username':'forbidden','password':'not-created-1234'}})[0],403)
        self.assertFalse((self.stores['A'].data_dir/'factory-instances').exists())

    def test_device_credentials_and_pending_transfers_are_per_customer_not_public(self):
        for label,other in [('A','B'),('B','A')]:
            bridge=self.servers[label].device_bridge
            self.assertEqual(bridge._secrets['same-device']['token'],label+'_DEVICE_SECRET_NOT_PUBLIC')
            self.assertEqual(bridge._secrets_path,self.stores[label].data_dir/'device-secrets.json')
            for path in ['/api/device','/api/device/images','/api/state','/api/access','/api/factory-instances/status']:
                code,data,_=self.request(label,path);self.assertEqual(code,200)
                text=json.dumps(data,ensure_ascii=False)
                self.assertNotIn('_DEVICE_SECRET_NOT_PUBLIC',text);self.assertNotIn(other+'_WiFi',text)
            self.assertEqual(self.request(label,'/device-secrets.json')[0],404)

    def test_provision_does_not_persist_cleartext_passwords_or_copy_parent_files(self):
        for label,store in self.stores.items():
            for file in store.data_dir.rglob('*'):
                if file.is_file():
                    content=file.read_bytes()
                    for password in self.passwords.values():self.assertNotIn(password.encode(),content,file.name)
                    self.assertNotIn(b'ROOT_PRIVATE_DRAWING',content,file.name)
            self.assertFalse((store.uploads/'parent-private.txt').exists())
        with self.stores['A'].connect() as con:
            secret_a=con.execute("SELECT value FROM config WHERE key='instance_secret'").fetchone()['value']
        with self.stores['B'].connect() as con:
            secret_b=con.execute("SELECT value FROM config WHERE key='instance_secret'").fetchone()['value']
        self.assertNotEqual(secret_a,secret_b)

    def test_cross_port_embedded_requests_fail_but_top_level_factory_navigation_can_open(self):
        code,_,_=self.request('A','/api/state',headers={'Origin':self.bases['B'],'Sec-Fetch-Site':'same-site','Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'empty'})
        self.assertEqual(code,403)
        # A user must be able to enter the new factory from a controller link.
        request=urllib.request.Request(self.bases['A']+'/factory-setup/index.html',headers={
            'Sec-Fetch-Site':'same-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Sec-Fetch-User':'?1'})
        try:response=self.plain_opener.open(request,timeout=5)
        except urllib.error.HTTPError as error:response=error
        with response:self.assertEqual(response.status,200)


if __name__ == '__main__':
    unittest.main()
