"""Business-boundary HTTP tests with synthetic OCR evidence.

Native engines have separate real-engine tests. These controlled job responses
exercise authorization, evidence ownership, stale sources and durable writes.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import intelligence


class IntelligenceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kanpace-intelligence-http-')
        self.store = app.Store(self.temp.name, seed=False)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '隔离工程测试'})
            self.other = self.store.new_project(con, {'name': '另一隔离项目'})
            self.store.put(con, 'people', {'id':'worker_a','name':'测试木工','skills':['木工'],'role':'木工'})
            self.doc = {'id':'drawing_a','project_id':self.project['id'],'filename':'工程图.png',
                        'storage_name':'drawing-a.png','sha256':hashlib.sha256(b'fixture source').hexdigest()}
            self.store.put(con, 'documents', self.doc)
        (self.store.uploads / self.doc['storage_name']).write_bytes(b'fixture source')
        self.job = {'id':'eng_'+'a'*32,'kind':'ocr','status':'completed',
                    'metadata':{'project_id':self.project['id'],'document_id':self.doc['id'],'source_id':'doc:'+self.doc['id']},
                    'source':{'filename':self.doc['filename'],'sha256':self.doc['sha256']},
                    'result':{'engine':'synthetic-boundary-fixture','pages':[{'page':1,'preview_filename':'page-1.jpg',
                               'regions':[{'page':1,'text':'侧板 18mm','bbox':[10,20,90,50],'polygon':[[10,20],[90,50]],'score':.96}]}]}}
        self.fake = Mock()
        self.fake.get.side_effect = lambda _: deepcopy(self.job)
        self.fake.list.side_effect = lambda: [deepcopy(self.job)]
        self.fake.status.return_value = {'local_only':True,'ocr':{'ready':True},'cad':{'ready':True}}
        self.fake.submit.return_value = {**self.job,'status':'queued'}
        self.mock = patch('intelligence.jobs', return_value=self.fake)
        self.mock.start()
        self.server = app.Server(('127.0.0.1',0),self.store)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.pid = self.project['id']
        self.path = f'/api/projects/{self.pid}/engineering'
        self.payload = {'source_id':'doc:'+self.doc['id'],'kind':'ocr','expected_revision':self.project['revision']}
        self.admin = None

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.mock.stop(); self.temp.cleanup()

    def request(self,path,data=None,cookie=None):
        headers={'Origin':self.base,'Accept':'application/json'}
        if cookie: headers['Cookie']=cookie.split(';')[0]
        if data is not None: headers['Content-Type']='application/json'
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try: response=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as err: response=err
        with response:
            raw=response.read()
            body=json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
            return response.status,body,response.headers

    def account(self,role):
        if not self.admin:
            code,body,headers=self.request('/api/access/setup',{'username':'qa_admin','name':'隔离管理员','password':'isolated-admin-password'})
            self.assertEqual(code,200,body);self.admin=headers['Set-Cookie']
        payload={'username':'qa_'+role,'name':'隔离'+role,'password':'isolated-user-password','role':role}
        if role=='worker': payload['person_id']='worker_a'
        code,body,_=self.request('/api/access/users',payload,self.admin)
        self.assertEqual(code,200,body)
        code,body,headers=self.request('/api/access/login',{'username':'qa_'+role,'password':'isolated-user-password'})
        self.assertEqual(code,200,body)
        return headers['Set-Cookie']

    def draft(self):
        return {'project_id':self.pid,'name':'已核对侧板','material':'多层板','category':'wood','quantity':2,
                'length_mm':600,'width_mm':450,'thickness_mm':18,'expected_revision':self.project['revision'],
                'engineering_evidence':{'job_id':self.job['id'],'regions':[{'page':1,'index':0}],
                                        'text':'client-forged-evidence-must-not-be-used'}}

    def cad_fixture(self):
        old=self.store.uploads/self.doc['storage_name']
        new=self.store.uploads/'assembly.step'
        old.rename(new)
        self.doc.update(filename='assembly.step',storage_name=new.name,status='needs_conversion',resolved=True)
        with self.store.connect() as con:self.store.put(con,'documents',self.doc)
        self.job.update(kind='cad',source={'filename':'assembly.step','sha256':self.doc['sha256']},
                        result={'engine':'Open CASCADE / OCP','format':'STEP','output_length_unit':'mm',
                                'source_length_units':['MM'],'parts':[
                            {'definition_id':'0:1:4','instance_path':'0:1:1/0:1:2','name':'Panel-A',
                             'valid':True,'solid_count':1,'bbox_extents_mm':[600,450,18]},
                            {'definition_id':'0:1:4','instance_path':'0:1:1/0:1:3','name':'Panel-A',
                             'valid':True,'solid_count':1,'bbox_extents_mm':[600,450,18]},
                            {'definition_id':'0:1:4','instance_path':'0:1:1/0:1:4','name':'右侧板',
                             'valid':True,'solid_count':1,'bbox_extents_mm':[600,450,18]}]})
        path=self.path+'/'+self.job['id']+'/proposals'
        code,body,_=self.request(path)
        self.assertEqual(code,200,body)
        panel=next(p for p in body['proposals'] if p['name']=='Panel-A')
        payload={'project_id':self.pid,'expected_revision':self.project['revision'],
                 'name':'Panel-A','material':'多层板','category':'wood','finish':'免漆',
                 'quantity':2,'length':598,'width':448,'thickness':18,
                 'engineering_evidence':{'job_id':self.job['id'],'proposal_id':panel['id'],
                    'part_indices':panel['instance_indices'],'quantity_confirmed':True,
                    'manufacturing_dimensions_confirmed':True}}
        return path,body,payload

    def test_step_proposals_are_scoped_to_current_source_and_keep_named_instances_separate(self):
        path,body,_=self.cad_fixture()
        self.assertEqual(body['source_length_units'],['mm'])
        self.assertTrue(body['units_confirmed'])
        self.assertEqual(len(body['proposals']),2)
        self.assertEqual(sorted(p['suggested_quantity'] for p in body['proposals']),[1,2])
        self.assertFalse(body['manufacturing_release'])
        self.assertTrue(all(p['manufacturing_dimensions'] is None and p['material'] is None for p in body['proposals']))
        self.assertEqual(self.request(f'/api/projects/{self.other["id"]}/engineering/{self.job["id"]}/proposals')[0],404)
        (self.store.uploads/self.doc['storage_name']).write_bytes(b'changed source')
        self.assertEqual(self.request(path)[0],409)

    def test_drawing_matches_only_current_bound_same_project_ocr_without_writing_parts(self):
        self.cad_fixture()
        ocr_bytes = b'current engineering drawing'
        ocr_doc = {'id':'drawing_match','project_id':self.pid,'filename':'柜体工程图.pdf',
                   'storage_name':'drawing-match.pdf','purpose':'engineering',
                   'sha256':hashlib.sha256(ocr_bytes).hexdigest()}
        cached_bytes=b'old page still present in media cache'
        cached_name=hashlib.sha256(cached_bytes).hexdigest()+'.jpg'
        cached = {'id':'eng_'+'c'*32,'kind':'ocr','status':'completed',
                  'metadata':{'project_id':self.pid,'source_id':'asset:'+cached_name,'source_label':'旧图页'},
                  'source':{'filename':cached_name,'sha256':hashlib.sha256(cached_bytes).hexdigest()},
                  'result':{'pages':[{'page':1,'regions':[{'text':'Panel-A','bbox':[0,0,20,20],'score':.9}]}]}}
        current = {'id':'eng_'+'b'*32,'kind':'ocr','status':'completed',
                   'metadata':{'project_id':self.pid,'document_id':ocr_doc['id'],
                               'source_id':'doc:'+ocr_doc['id'],'source_label':ocr_doc['filename']},
                   'source':{'filename':ocr_doc['filename'],'sha256':ocr_doc['sha256']},
                   'result':{'pages':[{'page':2,'width':1200,'height':900,'regions':[
                       {'page':2,'text':'Panel-A 598×448×18mm','bbox':[10,20,400,60],
                        'score':.98,'coordinate_system':'pixels_top_left'}]}]}}
        foreign = deepcopy(current)
        foreign['id']='eng_'+'d'*32
        foreign['metadata']['project_id']=self.other['id']
        with self.store.connect() as con:self.store.put(con,'documents',ocr_doc)
        (self.store.uploads/ocr_doc['storage_name']).write_bytes(ocr_bytes)
        cache_root=self.store.data_dir/'drawing-previews'
        (cache_root/'assets').mkdir(parents=True)
        (cache_root/'assets'/cached_name).write_bytes(cached_bytes)
        (cache_root/'manifest.json').write_text(json.dumps({'projects':{self.pid:{'sources':[
            {'url':'/api/drawing-media/assets/'+cached_name,'source_file':'旧图页','page':7}]}}}))
        with self.store.connect() as con:
            self.assertIsNone(intelligence._current_job_source(self.store,con,self.pid,cached))
        self.fake.get.side_effect=lambda identifier: deepcopy({
            self.job['id']:self.job,current['id']:current,cached['id']:cached,foreign['id']:foreign}[identifier])
        def summary(job):
            result=deepcopy(job)
            result.pop('result',None)
            return result
        self.fake.list.side_effect=lambda: [summary(self.job),summary(current),summary(cached),summary(foreign)]
        path=self.path+'/'+self.job['id']+'/drawing-matches'
        code,body,_=self.request(path)
        self.assertEqual(code,200,body)
        self.assertEqual(body['status'],'evidence_only')
        self.assertEqual(body['ocr_job_count'],1)
        self.assertEqual(body['excluded_unbound_ocr_job_count'],1)
        panel=next(row for row in body['matches'] if row['name']=='Panel-A')
        self.assertEqual(panel['match_status'],'matched')
        self.assertEqual(len(panel['drawing_evidence']),1)
        self.assertEqual(panel['drawing_evidence'][0]['region_index'],0)
        self.assertEqual(panel['drawing_evidence'][0]['page_width'],1200)
        self.assertFalse(body['manufacturing_release'])
        with self.store.connect() as con:
            self.assertEqual(self.store.all(con,'parts',self.pid),[])
            self.assertEqual(self.store.all(con,'tasks',self.pid),[])
        self.assertEqual(self.request(f'/api/projects/{self.other["id"]}/engineering/{self.job["id"]}/drawing-matches')[0],404)
        (self.store.uploads/ocr_doc['storage_name']).write_bytes(b'replaced engineering drawing')
        code,body,_=self.request(path)
        self.assertEqual(code,200,body)
        self.assertEqual(body['ocr_job_count'],0)
        self.assertEqual(body['excluded_stale_ocr_job_count'],1)
        self.assertEqual(next(row for row in body['matches'] if row['name']=='Panel-A')['match_status'],'unmatched')

    def test_unknown_step_source_unit_warns_but_does_not_block_manual_drawing_dimensions(self):
        path,_,payload=self.cad_fixture()
        self.job['result']['source_length_units']=[]
        code,snapshot,_=self.request(path)
        self.assertEqual(code,200,snapshot)
        self.assertEqual(snapshot['source_length_units'],[])
        self.assertFalse(snapshot['units_confirmed'])
        self.assertTrue(any('源长度单位' in warning for warning in snapshot['warnings']))
        code,body,_=self.request('/api/parts',payload)
        self.assertEqual(code,200,body)
        self.assertEqual(body['part']['review_status'],'pending')
        self.assertEqual(body['part']['length'],598)

    def test_step_proposal_creates_one_pending_part_only_after_explicit_confirmation(self):
        _,_,payload=self.cad_fixture()
        legacy=deepcopy(payload)
        legacy['engineering_evidence']={'job_id':self.job['id'],'part_index':0}
        self.assertEqual(self.request('/api/parts',legacy)[0],400)
        bad=deepcopy(payload);bad['engineering_evidence']['part_indices']=[0]
        self.assertEqual(self.request('/api/parts',bad)[0],400)
        bad=deepcopy(payload);bad['engineering_evidence']['quantity_confirmed']=False
        self.assertEqual(self.request('/api/parts',bad)[0],400)
        bad=deepcopy(payload);bad['length']=None
        self.assertEqual(self.request('/api/parts',bad)[0],400)
        code,body,_=self.request('/api/parts',payload)
        self.assertEqual(code,200,body)
        part=body['part']
        self.assertEqual(part['review_status'],'pending')
        self.assertEqual(part['length'],598)
        self.assertEqual(part['source']['step_proposal']['suggested_quantity'],2)
        self.assertEqual(len(part['source']['entries']),2)
        self.assertEqual(self.request('/api/parts',payload)[1]['part']['id'],part['id'])
        changed=deepcopy(payload);changed['quantity']=3
        self.assertEqual(self.request('/api/parts',changed)[0],409)
        with self.store.connect() as con:
            self.assertEqual(len(self.store.all(con,'parts',self.pid)),1)
            self.assertEqual(self.store.all(con,'tasks',self.pid),[])

    def test_step_proposal_approval_and_release_require_separate_engineering_confirmation(self):
        _,_,payload=self.cad_fixture()
        code,body,_=self.request('/api/parts',payload)
        self.assertEqual(code,200,body)
        part=body['part'];review='/api/parts/'+part['id']+'/review'
        self.assertEqual(self.request(review,{'approved':True,'review_note':'核对施工图 A-01'})[0],409)
        confirm={'quantity_confirmed':True,'manufacturing_dimensions_confirmed':True}
        self.assertEqual(self.request(review,{'approved':True,'engineering_confirmation':confirm})[0],409)
        code,body,_=self.request(review,{'approved':True,'engineering_confirmation':confirm,
                                         'review_note':'按施工图 A-01 核对数量及加工尺寸'})
        self.assertEqual(code,200,body)
        self.assertEqual(body['part']['review_status'],'approved')
        self.assertEqual(body['part']['source']['step_proposal']['approved_values']['length'],598)
        self.assertEqual(self.request('/api/projects/'+self.pid+'/generate',{})[0],200)
        with self.store.connect() as con:
            saved=self.store.get(con,'parts',part['id'])
            saved['source']['step_proposal'].pop('approved_values')
            self.store.put(con,'parts',saved)
        self.assertEqual(self.request('/api/projects/'+self.pid+'/release',{})[0],409)

    def test_registered_sources_only_and_no_filesystem_paths(self):
        code,body,_=self.request(self.path)
        self.assertEqual(code,200,body)
        self.assertEqual(body['sources'][0]['id'],'doc:drawing_a')
        self.assertNotIn(self.temp.name,json.dumps(body))
        for source in ('/etc/passwd','doc:another-project','asset:../private.png'):
            self.assertEqual(self.request(self.path,{**self.payload,'source_id':source})[0],404)
        self.assertEqual(self.request(self.path,{**self.payload,'kind':'cad'})[0],400)
        self.assertEqual(self.request(self.path,{**self.payload,'expected_revision':True})[0],409)
        self.assertEqual(self.request(self.path,self.payload)[0],202)
        self.fake.submit.assert_called_once()

    def test_cross_project_job_and_page_not_readable(self):
        root=self.store.data_dir/'engineering-jobs'/self.job['id'];root.mkdir(parents=True)
        (root/'page-1.jpg').write_bytes(b'private-page')
        code,body,_=self.request(self.path+'/'+self.job['id']+'/pages/1')
        self.assertEqual((code,body),(200,b'private-page'))
        for suffix in ('','/pages/1'):
            code,_,_=self.request(f'/api/projects/{self.other["id"]}/engineering/{self.job["id"]}'+suffix)
            self.assertEqual(code,404)
        self.assertEqual(self.request(self.path+'/'+self.job['id']+'/pages/2')[0],404)
        self.assertEqual(self.request(self.path+'/not-a-job')[0],404)

    def test_part_uses_server_evidence_is_pending_and_retry_idempotent(self):
        code,body,_=self.request('/api/parts',self.draft())
        self.assertEqual(code,200,body)
        part=body['part']
        self.assertEqual(part['review_status'],'pending')
        self.assertEqual(part['source']['entries'][0]['text'],'侧板 18mm')
        self.assertEqual(part['source']['entries'][0]['bbox'],[10,20,90,50])
        self.assertFalse(part['source']['manufacturing_dimensions_confirmed'])
        self.assertNotIn('client-forged',json.dumps(part))
        code,second,_=self.request('/api/parts',self.draft())
        self.assertEqual(code,200,second)
        self.assertEqual(second['part']['id'],part['id'])
        with self.store.connect() as con:
            self.assertEqual(len(self.store.all(con,'parts',self.pid)),1)
            self.assertEqual(self.store.all(con,'tasks',self.pid),[])

    def test_replaced_source_or_invalid_selection_rejected(self):
        draft=self.draft();draft['engineering_evidence']['regions'][0]['index']=100
        self.assertEqual(self.request('/api/parts',draft)[0],400)
        (self.store.uploads/self.doc['storage_name']).write_bytes(b'changed under same name')
        self.assertEqual(self.request('/api/parts',self.draft())[0],409)
        with self.store.connect() as con: self.assertEqual(self.store.all(con,'parts',self.pid),[])

    def test_cached_original_page_requires_current_project_manifest(self):
        name=hashlib.sha256(b'cached').hexdigest()+'.jpg'
        root=self.store.data_dir/'drawing-previews';(root/'assets').mkdir(parents=True)
        (root/'assets'/name).write_bytes(b'cached')
        manifest={'projects':{self.pid:{'sources':[{'url':'/api/drawing-media/assets/'+name,'source_file':'原施工图.pdf','page':7}]}}}
        (root/'manifest.json').write_text(json.dumps(manifest))
        self.job['metadata']={'project_id':self.pid,'source_id':'asset:'+name,'source_label':'原施工图.pdf','source_page':7}
        self.job['source']={'filename':name,'sha256':hashlib.sha256(b'cached').hexdigest()}
        with self.store.connect() as con:
            source,_=intelligence.evidence(self.store,con,self.pid,self.draft())
            self.assertEqual(source['original_page'],7)
        (root/'manifest.json').write_text(json.dumps({'projects':{}}))
        self.assertEqual(self.request('/api/parts',self.draft())[0],409)

    def test_render_references_excluded_and_drawing_pages_ordered(self):
        root=self.store.data_dir/'drawing-previews';(root/'assets').mkdir(parents=True)
        sources=[]
        for i,(kind,page) in enumerate([('产品参考',None),('施工图',11),('效果图',None),('施工图',2),('共用参考图',None)]):
            name=hashlib.sha256(str(i).encode()).hexdigest()+'.jpg'
            (root/'assets'/name).write_bytes(b'cached')
            sources.append({'url':'/api/drawing-media/assets/'+name,'source_file':'施工图.pdf','kind':kind,'page':page})
        (root/'manifest.json').write_text(json.dumps({'projects':{self.pid:{'sources':sources}}}))
        code,body,_=self.request(self.path)
        self.assertEqual(code,200,body)
        pages=[s['source_page'] for s in body['sources'] if s['id'].startswith('asset:')]
        self.assertEqual(pages,[2,11])
        for reference in (sources[0],sources[2],sources[4]):
            name=reference['url'].rsplit('/',1)[-1]
            self.assertEqual(self.request(self.path,{**self.payload,'source_id':'asset:'+name})[0],404)

    def test_closed_project_cannot_launch_or_derive_part(self):
        with self.store.connect() as con:
            p=self.store.get(con,'projects',self.pid);p['fulfillment_status']='shipped';self.store.put(con,'projects',p)
        self.assertEqual(self.request(self.path,self.payload)[0],409)
        self.assertEqual(self.request('/api/parts',self.draft())[0],409)
        self.fake.submit.assert_not_called()

    def test_roles_enforce_engineering_and_packing_financial_boundary(self):
        worker=self.account('worker');technical=self.account('technical');owner=self.account('owner')
        self.assertEqual(self.request(self.path,self.payload,worker)[0],403)
        self.assertEqual(self.request(self.path,self.payload,technical)[0],202)
        packing=f'/api/projects/{self.pid}/packing'
        for cookie in (worker,technical):
            self.assertEqual(self.request(packing,cookie=cookie)[0],403)
            self.assertEqual(self.request(packing,{},cookie)[0],403)
        self.assertEqual(self.request(packing,{},owner)[0],403)
        with patch('optimization_engines.status',return_value={'packingsolver':{'available':True}}):
            self.assertEqual(self.request(packing,cookie=owner)[0],200)

    def test_packing_solves_without_writer_lock_then_rechecks_revision(self):
        def change_during_calculation(_):
            with self.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                p=self.store.get(con,'projects',self.pid);p['revision']+=1;self.store.put(con,'projects',p)
            return {'summary':{'sheet_count':1}}
        with patch('optimization_engines.packing_preview',side_effect=change_during_calculation):
            code,body,_=self.request(f'/api/projects/{self.pid}/packing',{'expected_revision':self.project['revision']})
            self.assertEqual(code,409,body)
        with self.store.connect() as con:self.assertEqual(self.store.all(con,'packing_previews',self.pid),[])


if __name__=='__main__':unittest.main()
