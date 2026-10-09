"""Industry discovery is generic/public; factory creation remains authenticated."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import access_control as access
import factory_instances as instances
import factory_config as configs
import industry_templates as industries

class IndustryPlatformHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=app.Store(Path(self.temp.name)/'control',seed=False,empty=True)
        self.server=app.Server(('127.0.0.1',0),self.store)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01),daemon=True);self.thread.start()
        self.addCleanup(self.stop);self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.opener=build_opener(ProxyHandler({}));self.quiet=patch.object(app.Handler,'log_message',lambda *_:None);self.quiet.start();self.addCleanup(self.quiet.stop)
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,data=None,cookie=None):
        headers={'Origin':self.base}
        if cookie:headers['Cookie']=cookie
        if data is not None:headers['Content-Type']='application/json'
        req=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:r=self.opener.open(req,timeout=5)
        except HTTPError as e:r=e
        with r:return r.status,json.load(r),dict(r.headers)
    def test_generic_catalog_browsable_before_and_after_auth_setup_but_customer_data_private(self):
        for stage in (0,1):
            code,data,_=self.request('/api/industry-templates');self.assertEqual(code,200)
            self.assertEqual(len(data['industries']),19)
            self.assertEqual(len(data['templates']),sum(len(i['variants']) for i in data['industries']))
            self.assertNotIn('factories',data);self.assertNotIn('plans',data)
            for i in data['industries']:
                code,item,_=self.request('/api/industry-templates/'+i['id']+'/'+i['variants'][0]['id']);self.assertEqual(code,200);self.assertEqual(item['template']['industry_id'],i['id'])
            if stage==0:
                code,_,_=self.request('/api/access/setup',{'name':'中台测试','username':'qa_admin','password':'qa-industry-2026-test'});self.assertEqual(code,200)
        self.assertEqual(self.request('/api/control')[0],401)
        self.assertEqual(self.request('/api/factory-instances/provision',{'name':'forbidden'})[0],401)
        self.assertEqual(self.request('/api/industry-templates/no-industry/no-route')[0],404)
        self.assertEqual(self.request('/api/industry-templates/rattan/no-route')[0],404)
    def test_industry_creation_derives_scene_and_persists_selection_without_orders(self):
        ref=industries.resolve('food',None)
        data={'name':'食品行业测试厂','industry_id':ref['industry_id'],'variant_id':ref['variant_id'],
              'admin':{'name':'工厂管理员','username':'factory_admin','password':'qa-child-industry-2026'}}
        child,record=instances.create_store(self.store,data)
        self.assertEqual(record['factory_type'],ref['factory_type'])
        self.assertEqual(record['industry_id'],'food');self.assertEqual(instances.instance_info(child)['variant_id'],ref['variant_id'])
        with child.connect() as con:
            self.assertEqual(child.all(con,'projects'),[]);self.assertEqual(child.all(con,'tasks'),[])
            factory=child.get(con,'factories',record['factory_id']);self.assertEqual(factory['industry_name'],ref['industry_name'])
            project=child.new_project(con,{'name':'首单工作包'})
            self.assertEqual(project['industry_id'],'food');self.assertEqual(project['factory_id'],record['factory_id'])
            with self.assertRaises(app.APIError) as exc:child.generate(con,project['id'])
            self.assertEqual(exc.exception.details['code'],'industry_workflow_required')
            quote=child.quote(con,project['id'])
            self.assertFalse(quote['complete']);self.assertIsNone(quote['labor_total']);self.assertIsNone(quote['total'])
            self.assertTrue(any('行业流程' in message for message in quote['missing']))
        with self.assertRaises(instances.InstanceError):instances._payload({**data,'factory_type':'site' if ref['factory_type']!='site' else 'cabinet'})
        with self.assertRaises(instances.InstanceError):instances._payload({**data,'industry_id':'unknown'})
        with self.assertRaises(instances.InstanceError):instances._payload({**data,'variant_id':'unknown'})
    def test_provision_retry_cannot_change_industry_with_same_request(self):
        ref=industries.resolve('rattan',None)
        data={'name':'测试厂','industry_id':ref['industry_id'],'variant_id':ref['variant_id'],'request_id':'fixed_industry_request',
              'admin':{'username':'factory_admin','password':'qa-child-industry-2026'}}
        child,record=instances.create_store(self.store,data)
        record['status']='ready';record['url']='http://127.0.0.1:9991'
        instances._write_json(instances.root_path(self.store)/'registry.json',[record])
        other=next(r for i in industries.catalog() for r in (industries.resolve(i['id'],None),) if r['factory_type']==ref['factory_type'] and r['industry_id']!=ref['industry_id'])
        with patch.object(instances,'_require_controller',lambda *_:None):
            with self.assertRaises(instances.InstanceError) as exc:instances.provision(self.server,{**data,'industry_id':other['industry_id'],'variant_id':other['variant_id']})
            self.assertEqual(exc.exception.status,409)

if __name__=='__main__':unittest.main()
