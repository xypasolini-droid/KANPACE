import tempfile
import unittest
import app
import material_requirements as mr
import production

class MaterialPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=app.Store(self.temp.name,seed=False)
        with self.store.connect() as con:
            self.store.put(con,'projects',dict(id='p1',name='验收订单',factory_type='cabinet',revision=1,due_date='2026-09-20'))
            self.store.put(con,'parts',dict(id='a',project_id='p1',name='侧板',material='桦木板',category='wood',length=1000,width=500,thickness=18,quantity=4,finish='清漆',review_status='approved'))
    def tearDown(self):self.temp.cleanup()
    def row(self,p='p1'):
        with self.store.connect() as con:return mr.build(self.store,con,project_id=p)['requirements'][0]
    def stock(self,row=None,**kw):
        r=row or self.row();body=dict(project_id=r['project_id'],requirement_id=r['id'],snapshot=r['snapshot'],expected_version=r['inventory_version'],on_hand_quantity=1,reserved_quantity=0,note='仓库盘点');body.update(kw)
        with self.store.connect() as con:return mr.save_inventory(self.store,con,body)
    def purchase(self,row=None,**kw):
        r=row or self.row();body=dict(project_id=r['project_id'],requirement_id=r['id'],snapshot=r['snapshot'],expected_version=0);body.update(kw)
        with self.store.connect() as con:return mr.save_purchase(self.store,con,body)
    def test_net_bom_does_not_multiply_by_process_count_or_unknown_stock(self):
        r=self.row();self.assertEqual((r['required_quantity'],r['unit']),(2,'m²'));self.assertIsNone(r['shortage_quantity'])
        with self.assertRaises(production.ProductionError):self.purchase()
    def test_inventory_available_and_procurement_retry(self):
        self.stock(on_hand_quantity=1.5,reserved_quantity=.5);r=self.row();self.assertEqual((r['allocated_quantity'],r['shortage_quantity']),(1,1))
        p=self.purchase()['purchase'];again=self.purchase();self.assertTrue(again['duplicate']);self.assertEqual(again['purchase']['id'],p['id'])
    def test_changed_stock_and_bom_reject_stale_edit(self):
        old=self.row();self.stock();
        with self.assertRaises(production.ProductionError):self.stock(row=old)
        current=self.row()
        with self.store.connect() as con:
            p=self.store.get(con,'parts','a');p['quantity']=6;self.store.put(con,'parts',p)
        with self.assertRaises(production.ProductionError):self.purchase(row=current)
    def test_stock_not_reused_for_each_project(self):
        self.stock(on_hand_quantity=3)
        with self.store.connect() as con:
            self.store.put(con,'projects',dict(id='p2',name='第二单',factory_type='cabinet',revision=1,due_date='2026-09-21'))
            p=self.store.get(con,'parts','a');p.update(id='b',project_id='p2');self.store.put(con,'parts',p)
        self.assertEqual(self.row()['allocated_quantity'],2);self.assertEqual(self.row('p2')['allocated_quantity'],1)
        self.assertEqual(self.row('p2')['shortage_quantity'],1)
    def test_different_factory_spec_and_unit_do_not_share_stock(self):
        self.stock(on_hand_quantity=100)
        with self.store.connect() as con:
            self.store.put(con,'projects',dict(id='p2',name='其他工厂',factory_type='cabinet',factory_id='other',revision=1))
            p=self.store.get(con,'parts','a');p.update(id='b',project_id='p2');self.store.put(con,'parts',p)
        self.assertIsNone(self.row('p2')['inventory_total'])
    def test_unreviewed_part_and_zero_stock_do_not_authorize_purchase(self):
        self.stock(on_hand_quantity=0)
        with self.store.connect() as con:
            p=self.store.get(con,'parts','a');p['review_status']='pending';self.store.put(con,'parts',p)
        self.assertFalse(self.row()['reviewed'])
        with self.assertRaises(production.ProductionError):self.purchase()
    def test_missing_dimensions_and_negative_stock(self):
        with self.assertRaises(production.ProductionError):self.stock(on_hand_quantity=-1)
        with self.store.connect() as con:
            p=self.store.get(con,'parts','a');p['length']=None;self.store.put(con,'parts',p)
            result=mr.build(self.store,con,project_id='p1');self.assertEqual(result['requirements'],[]);self.assertEqual(len(result['warnings']),1)
    def test_current_draft_marked_stale_after_revision(self):
        self.stock();self.purchase()
        with self.store.connect() as con:
            p=self.store.get(con,'projects','p1');p['revision']=2;self.store.put(con,'projects',p)
            self.assertTrue(mr.build(self.store,con,project_id='p1')['purchases'][0]['stale'])
    def test_same_requirement_draft_can_be_edited_without_duplicate_purchase(self):
        self.stock();first=self.purchase()['purchase']
        with self.assertRaises(production.ProductionError):self.purchase(quantity=2,supplier='板材供应商')
        second=self.purchase(quantity=2,supplier='板材供应商',expected_version=first['version'])['purchase']
        self.assertEqual(second['id'],first['id']);self.assertEqual(second['quantity'],2);self.assertEqual(second['version'],2)
        retry=self.purchase(quantity=2,supplier='板材供应商',expected_version=first['version'])
        self.assertTrue(retry['duplicate'])
        with self.store.connect() as con:self.assertEqual(len(self.store.all(con,'purchase_drafts')),1)
    def test_old_drawing_revision_is_not_a_current_purchase_basis(self):
        with self.store.connect() as con:
            p=self.store.get(con,'parts','a');p['revision']=1;self.store.put(con,'parts',p)
            project=self.store.get(con,'projects','p1');project['revision']=2;self.store.put(con,'projects',project)
            result=mr.build(self.store,con,project_id='p1')
            self.assertEqual(result['requirements'],[]);self.assertIn('版次',result['warnings'][0]['message'])

if __name__=='__main__':unittest.main()
