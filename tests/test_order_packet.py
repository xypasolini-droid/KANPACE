"""Order-folder regression cases use synthetic OOXML, never customer files."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import order_packet as packet
from kanpace.core.errors import APIError


def workbook(quantity='2', formula=False, floating=False, packing=False):
    out = io.BytesIO()
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def row(number, values):
        cells=[]
        for col,value in zip('ABCDEFG', values):
            cells.append(f'<c r="{col}{number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        if formula and number == 2:
            cells[-1] = '<c r="G2"><f>SUM(1,1)</f><v>2</v></c>'
        return f'<row r="{number}">'+''.join(cells)+'</row>'
    rows = row(1,['名称','尺寸','备注','图示','编号','单位','数量'])
    rows += row(2,['直柜','800*400*950','密度板烤漆 LED','', 'A','组',quantity])
    rows += row(3,['弧形柜','弧长2346*470*950','','','B','组','1'])
    rows += row(4,['独立柜','600*400*950','','','C','组','1'])
    if packing:
        rows += row(5,['包装要求','','外包装全封闭，底部预留叉车脚','','','项','1'])
        rows += row(6,['包装箱','500*400*300','瓦楞纸箱','','D','件','2'])
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="本订单" sheetId="1" r:id="r1"/><sheet name="旧订单" state="hidden" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        drawing = '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/>' if floating else ''
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData>{rows}</sheetData><mergeCells><mergeCell ref="C2:C3"/></mergeCells>{drawing}</worksheet>')
        if floating:
            from PIL import Image
            def png(color):
                image=Image.new('RGB',(4,4),color);content=io.BytesIO();image.save(content,format='PNG');return content.getvalue()
            z.writestr('xl/worksheets/_rels/sheet1.xml.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>'
                '</Relationships>')
            drawing_xml='<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            drawing_xml+='xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            for row_no,ref,anchor in ((1,'rId1','twoCellAnchor'),(2,'rId2','oneCellAnchor')):
                drawing_xml+=f'<xdr:{anchor}><xdr:from><xdr:col>3</xdr:col><xdr:row>{row_no}</xdr:row></xdr:from>'
                drawing_xml+=f'<xdr:pic><xdr:blipFill><a:blip r:embed="{ref}"/></xdr:blipFill></xdr:pic></xdr:{anchor}>'
            drawing_xml+='<xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:row>0</xdr:row></xdr:from>'
            drawing_xml+='<xdr:pic><xdr:blipFill><a:blip r:embed="rId3"/></xdr:blipFill></xdr:pic></xdr:oneCellAnchor>'
            drawing_xml+='</xdr:wsDr>'
            z.writestr('xl/drawings/drawing1.xml',drawing_xml)
            z.writestr('xl/drawings/_rels/drawing1.xml.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.png"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/>'
                '</Relationships>')
            z.writestr('xl/media/image1.png',png('red'))
            z.writestr('xl/media/image2.png',png('blue'))
            z.writestr('xl/media/logo.png',png('green'))
    return out.getvalue()


class OrderPacketParserTests(unittest.TestCase):
    def test_trade_scope_uses_identified_material_and_component_not_page_keywords(self):
        scopes, questions = packet._scopes(
            '整体拉丝不锈钢框架封釉',
            [{'name': '左侧板', 'note': '五金备料'}],
            [({'filename': '收银台.pdf'}, {'text': '免漆板 图框通用说明'})],
        )
        self.assertNotIn('木工', [scope['trade'] for scope in scopes])
        self.assertIn('五金', [scope['trade'] for scope in scopes])
        self.assertTrue(any('木工' in question and '需技术员核对' in question for question in questions))

    def test_mixed_cabinet_note_becomes_trade_specific_instructions(self):
        scopes, _ = packet._scopes(
            '高密度板基层，201拉丝不锈钢框架，10mm超白玻璃，LED灯带，白色烤漆；不含广告机', [], [])
        by_trade = {scope['trade']: scope for scope in scopes}
        self.assertEqual(set(by_trade), {'木工', '五金', '玻璃', '油漆', '电工', '装配', '质检', '包装'})
        self.assertIn('高密度板', by_trade['木工']['instructions'])
        for foreign in ('不锈钢', '玻璃', 'LED', '烤漆'):
            self.assertNotIn(foreign, by_trade['木工']['instructions'])
        self.assertIn('不锈钢', by_trade['五金']['instructions'])
        self.assertNotIn('密度板', by_trade['五金']['instructions'])
        self.assertIn('玻璃', by_trade['玻璃']['instructions'])
        self.assertIn('LED', by_trade['电工']['instructions'])

    def test_excluded_accessory_does_not_create_an_electrical_scope(self):
        scopes, _ = packet._scopes('高密度板基层，不含灯带。', [], [])
        self.assertNotIn('电工', [scope['trade'] for scope in scopes])

    def test_explicit_component_shop_note_is_enough_to_suggest_that_trade(self):
        scopes, _ = packet._scopes('', [{'name': '左侧板', 'note': '五金备料'}], [])
        self.assertIn('五金', [scope['trade'] for scope in scopes])
        self.assertNotIn('木工', [scope['trade'] for scope in scopes])

    def test_hidden_order_and_merged_material_are_not_extra_orders(self):
        r=packet.xlsx_orders(workbook())
        self.assertEqual([s['sheet'] for s in r['sheets']], ['本订单'])
        a,b,c=r['sheets'][0]['items']
        self.assertEqual((a['quantity'],b['quantity'],c['quantity']), (2,1,1))
        self.assertEqual(b['material_cell'],'C2')
        self.assertEqual(b['material'],a['material'])
        self.assertEqual(c['material'],'')
        self.assertEqual(a['overall_dimensions']['height_mm'],950)
        self.assertNotIn('thickness_mm', a['overall_dimensions'])
        self.assertEqual(b['overall_dimensions'],{})

    def test_formula_cache_never_becomes_order_quantity(self):
        a=packet.xlsx_orders(workbook(formula=True))['sheets'][0]['items'][0]
        self.assertIsNone(a['quantity'])
        self.assertTrue(a['questions'])

    def test_two_column_cutting_text_requires_an_explicit_name(self):
        rows=packet.page_bom('面板  963*461*15钛白=1  雕刻      抽面  347*147*15钛白=2  雕刻\n     451*53*9钛白=2\n架子 400*25*15钛白=4')
        self.assertEqual([r['name'] for r in rows],['面板','抽面','架子'])
        self.assertEqual([r['per_assembly_quantity'] for r in rows],[1,2,4])
        self.assertEqual(rows[0]['specification'],'963*461*15')

    def test_relative_paths_stay_inside_the_order(self):
        self.assertEqual(packet.relative_path('柜1/底板.SLDPRT','底板.SLDPRT'),'柜1/底板.SLDPRT')
        for p in ('../底板.SLDPRT','/底板.SLDPRT','C:/底板.SLDPRT','柜1/其他.SLDPRT'):
            with self.assertRaises(APIError):packet.relative_path(p,'底板.SLDPRT')

    def test_packaging_instruction_is_not_a_cabinet_and_real_box_stays_a_product(self):
        sheet=packet.xlsx_orders(workbook(packing=True))['sheets'][0]
        self.assertEqual([x['name'] for x in sheet['items']],['直柜','弧形柜','独立柜','包装箱'])
        self.assertEqual([(x['name'],x['kind'],x['row']) for x in sheet['handoff_rules']],
                         [('包装要求','packaging',5)])


class OrderPacketStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=app.Store(self.temp.name,seed=False)
        with self.store.connect() as con:
            self.project=self.store.new_project(con,{'name':'订单文件夹回归测试'})
        self.master=self.upload('下单清单.xlsx',workbook())['document']

    def tearDown(self):self.temp.cleanup()

    def upload(self,name,content,relative=None,project_id=None):
        with self.store.connect() as con:
            return self.store.import_file(con,{'project_id':project_id or self.project['id'],'filename':name,
                'relative_path':relative or name,'content_base64':base64.b64encode(content).decode()})

    def save(self,**extra):
        with self.store.connect() as con:
            p=self.store.get(con,'projects',self.project['id'])
            return packet.save(self.store,con,p['id'],{'expected_revision':p['revision'],'master_document_id':self.master['id'],**extra})

    def test_scopes_keep_unknown_hours_and_cannot_be_released(self):
        r=self.save()
        self.assertEqual(len(r['parts']),3)
        self.assertTrue(all(t['status']=='draft' and t['hours'] is None for t in r['tasks']))
        self.assertTrue(all(p['draft_only'] and p['thickness'] is None for p in r['parts']))
        with self.store.connect() as con:
            with self.assertRaises(APIError):self.store.release(con,self.project['id'])

    def test_saved_trade_tasks_do_not_repeat_whole_cabinet_material_note(self):
        result=self.save()
        part=result['parts'][0]
        self.assertEqual(part['material'],'密度板烤漆 LED')
        by_trade={task['trade']:task for task in result['tasks'] if task['part_id']==part['id']}
        self.assertIn('密度板',by_trade['木工']['instructions'])
        self.assertNotIn('LED',by_trade['木工']['instructions'])
        self.assertNotIn('烤漆',by_trade['木工']['instructions'])
        self.assertIn('LED',by_trade['电工']['instructions'])
        self.assertNotIn('密度板',by_trade['电工']['instructions'])

    def test_effect_pdf_is_retained_as_source_but_not_misread_as_cabinet_drawing(self):
        effect=self.upload('直柜视觉.pdf',b'%PDF-1.4 effect fixture','效果图/直柜视觉.pdf')['document']
        engineering=self.upload('直柜.pdf',b'%PDF-1.4 drawing fixture','工程图/直柜.pdf')['document']
        page={'page':1,'text':'直柜 结构说明','text_sha256':'engineering-page'}
        with patch.object(packet,'pdf_pages',return_value=[page]) as read_pages:
            result=self.save()
        self.assertEqual(read_pages.call_count,1)
        self.assertEqual(result['packet']['pdf_pages'],1)
        self.assertIn(effect['id'],[source['document_id'] for source in result['packet']['sources']])
        with self.store.connect() as con:
            images=packet.media_for_project(self.store,con,self.project['id'])['ORDER-001']
        self.assertEqual([image['document_id'] for image in images],[engineering['id']])
        self.assertTrue(packet._effect_only_pdf({'source_paths':['效果图\\直柜视觉.pdf']}))
        self.assertFalse(packet._effect_only_pdf({'source_paths':['效果图/直柜视觉.pdf','工程图/直柜视觉.pdf']}))

    def test_ordinary_floating_excel_images_follow_only_their_product_rows(self):
        raw=workbook(floating=True)
        items=packet.xlsx_orders(raw)['sheets'][0]['items']
        media=packet.workbook_pictures(raw,self.store,self.master,items)
        self.assertEqual(set(media),{'直柜','弧形柜'})
        self.assertEqual((media['直柜']['cell'],media['弧形柜']['cell']),('D2','D3'))
        self.assertNotEqual(media['直柜']['url'],media['弧形柜']['url'])
        self.assertTrue(all(m['width']==4 and m['height']==4 for m in media.values()))

    def test_packaging_requirement_is_visible_in_handoff_not_generated_parts(self):
        self.master=self.upload('包装清单.xlsx',workbook(packing=True))['document']
        result=self.save()
        self.assertEqual([p['name'] for p in result['parts']],['直柜','弧形柜','独立柜','包装箱'])
        rule=result['packet']['handoff_rules'][0]
        self.assertEqual((rule['kind'],rule['title'],rule['source']['row']),('packaging','包装要求',5))
        self.assertTrue(any('包装要求' in issue for issue in result['project']['order_draft']['issues']))

    def test_repeat_build_is_idempotent(self):
        a=self.save();b=self.save()
        self.assertTrue(b['unchanged'])
        self.assertEqual([p['id'] for p in a['parts']], [p['id'] for p in b['parts']])
        self.assertEqual(a['project']['revision'],b['project']['revision'])

    def test_legacy_packet_media_has_stable_ids_without_rebuilding_or_writing(self):
        self.save()
        legacy=[{'document_id':self.master['id'],'kind':'效果图','title':name,'sheet':'本订单','cell':cell,
                 'url':'/api/drawing-media/assets/'+filename}
                for name,cell,filename in [('直柜','C2','counter.png'),('形象板','C3','sign.png')]]
        with self.store.connect() as con:
            record=self.store.all(con,'order_packet_media',self.project['id'])[0]
            record['parts']={'直柜':legacy}
            self.store.put(con,'order_packet_media',record)
            with patch('drawing_media.project_media',return_value={'parts':{},'sources':[],'renders':[]}):
                result=packet.project_media(self.store,con,self.project['id'])
            ids={r['url']:r['id'] for r in result['renders']}
            self.assertEqual(len(set(ids.values())),2)
            self.assertTrue(all(ids.values()))
            self.assertEqual(self.store.get(con,'order_packet_media',record['id']),record)
            record['parts']['直柜']=list(reversed(legacy))
            record['parts']['直柜'][0]['title']='更正后的名称'
            self.store.put(con,'order_packet_media',record)
            again=packet.media_for_project(self.store,con,self.project['id'])['直柜']
            self.assertEqual({r['url']:r['id'] for r in again},ids)
            self.assertNotEqual(packet._identified_media(legacy[0],'other-project')['id'],ids[legacy[0]['url']])
            self.assertEqual(packet._identified_media({**legacy[0],'id':'existing-id'},self.project['id'])['id'],'existing-id')

    def test_generated_pdf_pages_have_distinct_stable_media_ids(self):
        doc={**self.master,'filename':'加工图.pdf'}
        first=packet._media(doc,1,'底板');second=packet._media(doc,2,'面板')
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(packet._media(doc,1,'更正后的标题')['id'],first['id'])

    def test_new_upload_can_rebuild_untouched_drafts_and_keep_review_findings(self):
        first=self.save(findings=[{'name':'直柜','note':'总高 950 与工程图待确认'}])
        self.upload('底板.SLDPRT',b'native-document-fixture', '柜1/底板.SLDPRT')
        second=self.save()
        self.assertFalse(second['unchanged'])
        self.assertIn('总高 950 与工程图待确认',second['parts'][0]['review_questions'])
        with self.store.connect() as con:
            self.assertTrue(all(self.store.get(con,'parts',p['id'])['archived'] for p in first['parts']))
            self.assertTrue(all(t['status']=='draft' for t in self.store.active_tasks(con,self.project['id'])))

    def test_started_task_never_overwritten(self):
        r=self.save()
        with self.store.connect() as con:
            t=r['tasks'][0];t.update(status='invalidated',previous_status='draft',started_at='2026-09-14T01:00:00Z')
            self.store.put(con,'tasks',t)
        with self.assertRaises(APIError):self.save()

    def test_same_basename_in_two_cabinets_preserves_each_drawing(self):
        a=self.upload('底板.SLDPRT',b'a','柜1/底板.SLDPRT')['document']
        b=self.upload('底板.SLDPRT',b'b','柜2/底板.SLDPRT')['document']
        self.upload('底板.SLDPRT',b'a2','柜1/底板.SLDPRT')
        with self.store.connect() as con:
            self.assertTrue(self.store.get(con,'documents',a['id'])['superseded'])
            self.assertFalse(self.store.get(con,'documents',b['id']).get('superseded'))

    def test_replacing_one_shared_alias_does_not_remove_other_cabinet(self):
        a=self.upload('底板.SLDPRT',b'a','柜1/底板.SLDPRT')['document']
        b=self.upload('底板.SLDPRT',b'a','柜2/底板.SLDPRT')
        self.assertTrue(b['duplicate'])
        self.upload('底板.SLDPRT',b'b','柜1/底板.SLDPRT')
        with self.store.connect() as con:
            previous=self.store.get(con,'documents',a['id'])
            self.assertFalse(previous.get('superseded'))
            self.assertEqual(previous['source_paths'],['柜2/底板.SLDPRT'])

    def test_foreign_project_master_and_stale_version_rejected(self):
        with self.store.connect() as con:other=self.store.new_project(con,{'name':'另一个订单'})
        other_doc=self.upload('下单清单.xlsx',workbook(),project_id=other['id'])['document']
        with self.assertRaises(APIError):self.save(master_document_id=other_doc['id'])
        with self.assertRaises(APIError):self.save(expected_revision=0)

    def test_larger_cad_limit_does_not_expand_image_or_workbook_limit(self):
        with patch('kanpace.application.engineering.MAX_UPLOAD',2), patch('kanpace.application.engineering.MAX_CAD_UPLOAD',10):
            self.assertEqual(self.upload('资料.dwg',b'123456')['parts'],[])
            for filename,content in [('资料.dwg',b'x'*11),('图片.png',b'123456'),('资料.xlsx',b'123456')]:
                with self.assertRaises(APIError) as ctx:self.upload(filename,content)
                self.assertEqual(ctx.exception.status,413)
