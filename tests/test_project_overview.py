"""Real HTTP whole-project page selection; all fixtures are synthetic."""
import base64
from unittest.mock import patch
import unittest
import test_api
from test_upload_preview import pdf_bytes
from test_render_upload import image_bytes


class ProjectOverviewTests(unittest.TestCase):
    setUp=test_api.APITests.setUp
    tearDown=test_api.APITests.tearDown
    request=test_api.APITests.request
    project=test_api.APITests.project
    imported=test_api.APITests.imported
    state=test_api.APITests.state

    def test_selected_original_pages_and_cover_do_not_change_production(self):
        project,result=self.imported(filename='整体方案.pdf',content=pdf_bytes())
        doc=result['document'];pid=project['id'];before=self.state()
        status,result=self.request(f'/api/projects/{pid}/overview',{'expected_version':0,'document_id':doc['id'],'document_sha256':doc['sha256'],'pages':[2]})
        self.assertEqual(status,200,result)
        self.assertEqual(result['project']['revision'],before['projects'][0]['revision'])
        self.assertEqual(self.state()['tasks'],before['tasks'])
        self.assertEqual(self.state()['parts'],before['parts'])
        status,media=self.request(f'/api/projects/{pid}/drawing-media')
        self.assertEqual(status,200)
        selected=media['renders'][0]
        self.assertEqual(selected['page'],2)
        self.assertEqual(selected['source_role'],'overview_pdf_page')
        self.assertEqual(self.request(selected['url'],raw=True)[0],200)
        self.assertEqual(result['project']['overview_cover']['id'],selected['id'])

    def test_foreign_pdf_stale_revision_and_invalid_pages_are_rejected(self):
        first,a=self.imported(filename='A.pdf',content=pdf_bytes())
        second,b=self.imported(filename='B.pdf',content=pdf_bytes())
        url=f'/api/projects/{first["id"]}/overview'
        base={'expected_version':0,'document_id':a['document']['id'],'document_sha256':a['document']['sha256'],'pages':[1]}
        for changes in ({'document_id':b['document']['id']},{'pages':[0]},{'pages':[3]},{'pages':[True]},{'pages':[1,1]},{'document_sha256':'wrong'},{'expected_version':99}):
            self.assertIn(self.request(url,{**base,**changes})[0],(400,409))
        self.assertEqual(self.request(url,base)[0],200)
        self.assertEqual(self.request(url,base)[0],409)

    def test_replaced_source_is_removed_from_overview(self):
        project,result=self.imported(filename='方案.pdf',content=pdf_bytes())
        doc=result['document'];url=f'/api/projects/{project["id"]}/overview'
        self.assertEqual(self.request(url,{'expected_version':0,'document_id':doc['id'],'document_sha256':doc['sha256'],'pages':[1]})[0],200)
        with self.store.connect() as con:
            saved=self.store.get(con,'documents',doc['id']);saved['superseded']=True;self.store.put(con,'documents',saved)
        self.assertEqual(self.request(url)[1]['media'],[])

    def test_panorama_only_accepts_known_original_https_tour_urls(self):
        project=self.project();url=f'/api/projects/{project["id"]}/overview'
        for value in ('javascript:alert(1)','http://127.0.0.1/private','https://vr.3d66.com.evil.test/vr/index_detail_1.html','https://vr.3d66.com/vr/index_detail_1.html?token=abc'):
            self.assertEqual(self.request(url,{'expected_version':0,'panorama_url':value})[0],400)
        good='https://vr.3d66.com/vr/index_detail_123.html'
        status,result=self.request(url,{'expected_version':0,'panorama_url':good})
        self.assertEqual(status,200,result)
        self.assertEqual(result['project']['overview_panorama'],good)
        self.assertIsNone(result['project']['overview_cover'])
        self.assertEqual(self.request(url,{'expected_version':1,'panorama_url':''})[0],200)

    def test_large_pdf_limit_does_not_expand_images_or_workbooks(self):
        project=self.project()
        with patch('kanpace.application.engineering.MAX_UPLOAD',2),patch('kanpace.application.engineering.MAX_PDF_UPLOAD',len(pdf_bytes())+1):
            data={'project_id':project['id'],'filename':'大方案.pdf','content_base64':base64.b64encode(pdf_bytes()).decode()}
            self.assertEqual(self.request('/api/import',data)[0],200)
            for filename in ('图.png','表.xlsx'):
                self.assertEqual(self.request('/api/import',{**data,'filename':filename})[0],413)

    def test_cabinet_originals_remain_separate_from_overall_cover(self):
        project=self.project();pid=project['id']
        data={'project_id':pid,'filename':'柜体彩色图.png','purpose':'render','render_scope':'cabinet','content_base64':base64.b64encode(image_bytes()).decode()}
        status,result=self.request('/api/import',data);self.assertEqual(status,200,result)
        self.assertEqual(result['document']['render_scope'],'cabinet')
        self.assertEqual(result['render']['kind'],'柜体效果图')
        self.assertEqual(self.request(f'/api/projects/{pid}/overview',{'expected_version':0,'cover_id':result['document']['id']})[0],400)
        self.assertEqual(self.request('/api/import',{**data,'render_scope':'foreign'})[0],400)

    def test_native_cad_has_its_own_larger_limit(self):
        project=self.project()
        raw=b'AC1032'+b'\x00'*64
        with patch('kanpace.application.engineering.MAX_UPLOAD',2),patch('kanpace.application.engineering.MAX_PDF_UPLOAD',2),patch('kanpace.application.engineering.MAX_CAD_UPLOAD',100):
            data={'project_id':project['id'],'filename':'原始.dwg','content_base64':base64.b64encode(raw).decode()}
            status,result=self.request('/api/import',data)
            self.assertEqual(status,200,result)
            self.assertEqual(self.request('/api/import',{**data,'filename':'方案.pdf'})[0],413)
