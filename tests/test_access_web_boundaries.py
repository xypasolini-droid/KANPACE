"""New Web cookies and whole-order observation scope, using isolated accounts."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import access_control as access
from app import Store

class AccessWebBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name,seed=False)
        self.h=SimpleNamespace(server=SimpleNamespace(store=self.store),headers={},command='POST',path='/api/access/setup')
        _,self.cookie=access.setup(self.store,self.h,{'username':'qaadmin','name':'QA','password':'synthetic-admin-password'})
        self.admin=SimpleNamespace(server=self.h.server,headers={'Cookie':self.cookie.split(';')[0]},command='POST',path='/api/access/users')
        with self.store.connect() as con:
            for role in ('worker','quality'):
                self.store.put(con,'people',{'id':'qa_'+role,'name':'合成人员 '+role,'demo':False,'skills':[]})
    def tearDown(self):
        access.clear_actor();self.tmp.cleanup()
    def test_secure_cookie_is_server_configuration_not_forwarded_header(self):
        self.h.headers={'X-Forwarded-Proto':'https'}
        _,local=access.login(self.store,self.h,{'username':'qaadmin','password':'synthetic-admin-password'})
        self.assertNotIn('; Secure',local)
        self.store.web_origin='https://kanpace.example.com'
        _,web=access.login(self.store,self.h,{'username':'qaadmin','password':'synthetic-admin-password'})
        self.assertIn('; Secure',web);self.assertIn('HttpOnly',web);self.assertIn('SameSite=Strict',web)
        _,logout=access.logout(self.store,self.h);self.assertIn('; Secure',logout)
    def test_own_task_roles_cannot_read_whole_order_workflow_or_recognition(self):
        for role in ('worker','quality'):
            access.save_user(self.store,self.admin,{'username':role,'name':'合成账号','role':role,'person_id':'qa_'+role,'password':'synthetic-user-password'})
            _,cookie=access.login(self.store,self.h,{'username':role,'password':'synthetic-user-password'})
            for endpoint in ('workflow','recognition','recognition/rec_'+'a'*32):
                handler=SimpleNamespace(server=self.h.server,headers={'Cookie':cookie.split(';')[0]},command='GET',path='/api/projects/prj_test/'+endpoint)
                with self.assertRaises(access.AccessError) as caught:access.authorize(handler)
                self.assertEqual(caught.exception.status,403)
