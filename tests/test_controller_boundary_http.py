"""Controller must be protected before any new customer can be provisioned."""
import json
from pathlib import Path
import sys,tempfile,threading,unittest
from types import SimpleNamespace
from urllib.request import build_opener,ProxyHandler,Request
from urllib.error import HTTPError
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,access_control as access,factory_instances as instances

class ControllerBoundaryHTTP(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.parent=app.Store(root/'controller',seed=False,empty=True)
        self.static=root/'static';(self.static/'studies'/'customer').mkdir(parents=True)
        (self.static/'index.html').write_text('<!doctype html><title>Test app</title>')
        (self.static/'studies'/'customer'/'private.pdf').write_bytes(b'%PDF-TEMPORARY-CONTROLLER-PRIVATE')
        self.server=app.Server(('127.0.0.1',0),self.parent,self.static)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.opener=build_opener(ProxyHandler({}));self.admin_cookie=None
        self.payload={'name':'新的客户空间','factory_type':'cabinet','admin':{'username':'client_admin','name':'客户管理员','password':'client-password-123'}}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.temp.cleanup();access.clear_actor()
    def request(self,path,data=None,cookie=None,extra=None,expected=200):
        headers={'Cookie':cookie} if cookie else {}
        if data is not None:headers.update({'Content-Type':'application/json','Origin':self.base})
        headers.update(extra or {})
        request=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:
            with self.opener.open(request,timeout=10) as response:status=response.status;body=response.read();cookie=response.headers.get('Set-Cookie')
        except HTTPError as error:status=error.code;body=error.read();cookie=None;error.close()
        self.assertEqual(status,expected,(path,body[:120]))
        return body,cookie
    def enable(self):
        _,self.admin_cookie=self.request('/api/access/setup',{'username':'controller_admin','name':'管理账号','password':'controller-password-123'})
        self.admin_cookie=self.admin_cookie.split(';')[0]
    def test_local_unprotected_mode_cannot_provision_or_list_new_customers(self):
        body,_=self.request('/api/factory-instances/status');status=json.loads(body)
        self.assertTrue(status['controller_auth_required']);self.assertFalse(status['can_provision']);self.assertEqual(status['instances'],[])
        self.request('/api/factory-instances/provision',self.payload,expected=409)
        self.assertFalse(instances.root_path(self.parent).exists())
    def test_enabled_controller_anonymous_state_and_private_static_require_own_login(self):
        self.enable()
        for path in ('/api/state','/api/factory-instances/status','/studies/customer/private.pdf','/%73tudies/customer/private.pdf','/model/../studies/customer/private.pdf'):
            self.request(path,expected=401)
        self.request('/')
        body,_=self.request('/studies/customer/private.pdf',cookie=self.admin_cookie)
        self.assertEqual(body,b'%PDF-TEMPORARY-CONTROLLER-PRIVATE')
    def test_child_admin_cookie_does_not_authenticate_controller(self):
        self.enable();child,_=instances.create_store(self.parent,self.payload)
        handler=SimpleNamespace(server=SimpleNamespace(store=child),headers={})
        _,cookie=access.login(child,handler,self.payload['admin']);cookie=cookie.split(';')[0]
        for path in ('/api/state','/api/factory-instances/status','/studies/customer/private.pdf'):
            self.request(path,cookie=cookie,expected=401)
        self.request('/api/factory-instances/provision',self.payload,cookie=cookie,expected=401)
    def test_only_real_controller_admin_may_create_and_cross_origin_fetch_is_denied(self):
        self.enable()
        body,_=self.request('/api/factory-instances/status',cookie=self.admin_cookie);status=json.loads(body)
        self.assertTrue(status['can_provision']);self.assertFalse(status['controller_auth_required'])
        self.request('/api/access/users',{'username':'supervisor','name':'主管','role':'supervisor','password':'supervisor-password-123'},cookie=self.admin_cookie)
        _,cookie=self.request('/api/access/login',{'username':'supervisor','password':'supervisor-password-123'});cookie=cookie.split(';')[0]
        self.request('/api/factory-instances/provision',self.payload,cookie=cookie,expected=403)
        self.request('/api/state',cookie=self.admin_cookie,extra={'Sec-Fetch-Site':'same-site','Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'empty'},expected=403)
        self.request('/',extra={'Sec-Fetch-Site':'same-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        self.request('/studies/customer/private.pdf',cookie=self.admin_cookie,extra={'Sec-Fetch-Site':'same-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'},expected=403)
        with patch.object(instances,'start_instance',return_value='http://127.0.0.1:19991'):
            body,_=self.request('/api/factory-instances/provision',self.payload,cookie=self.admin_cookie,expected=201)
            self.assertTrue(json.loads(body)['isolated'])

if __name__=='__main__':unittest.main()
