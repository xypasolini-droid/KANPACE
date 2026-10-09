"""Temporary DB/XLSX tests for edited flow, precise reimport and live plans."""
import copy
import io
import unittest
import test_api
import test_schedule_reference as reference_fixture
import test_planning as planning_fixture
xlsx, worksheet, order = reference_fixture.xlsx, reference_fixture.worksheet, reference_fixture.order
import schedule_reference as ref


class WorkingScheduleTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    state = test_api.APITests.state
    project = test_api.APITests.project
    imported = test_api.APITests.imported
    prepared = test_api.APITests.prepared
    execution_prepared = test_api.APITests.execution_prepared
    task_action = test_api.APITests.task_action
    upload = reference_fixture.ReferenceTests.upload
    grid = reference_fixture.ReferenceTests.grid
    fixture = planning_fixture.PlanningTests.fixture

    def draft(self, two=False):
        self.upload(xlsx([('8.13', worksheet({4:order(), **({5:order(单号='商务二部-002',店铺信息='第二订单')} if two else {})}))]))
        return self.grid()['working']

    def payload(self, working, **changes):
        return {'source_id':working['source_id'],'sheet':working['sheet'],'expected_version':working['version'],
                'order_key':working['orders'][0]['key'],'changes':changes}

    def save(self, working, **changes):
        code, body=self.request('/api/schedule-reference/working', self.payload(working, **changes))
        self.assertEqual(code,200,body)
        return body['working']

    def test_import_derives_parallel_proposal_without_writing_production(self):
        before=self.state();working=self.draft();self.assertEqual(self.state(),before)
        nodes={n['id']:n for n in working['orders'][0]['nodes']}
        self.assertEqual(nodes['metal']['predecessors'],['technical'])
        self.assertEqual(nodes['wood']['predecessors'],['technical'])
        self.assertEqual(nodes['assembly']['predecessors'],['paint','metal','outsourcing'])
        self.assertFalse(working['orders'][0]['confirmed'])
        self.assertEqual(nodes['wood']['days'],3)
        self.assertNotIn('photography',nodes)

    def test_exact_name_binds_project_and_exposes_render_plus_drawing(self):
        project=self.project('北区综合展示柜')
        self.project('北区综合展示柜扩建')
        with self.store.connect() as con:
            self.store.put(con,'documents',{'id':'doc_schedule_render','project_id':project['id'],'purpose':'render',
                'render_scope':'project','filename':'整体效果.png','image_url':'/api/documents/doc_schedule_render/image',
                'created_at':'2026-09-29T10:00:00+00:00','demo':False})
            self.store.put(con,'documents',{'id':'doc_schedule_drawing','project_id':project['id'],'purpose':'drawing',
                'format':'PDF','filename':'施工图.pdf','created_at':'2026-09-29T11:00:00+00:00','demo':False})
        working=self.draft();order=working['orders'][0]
        self.assertEqual(order['project_id'],project['id'])
        self.assertEqual(order['match_status'],'matched')
        self.assertEqual(order['project']['render_image_url'],'/api/documents/doc_schedule_render/image')
        self.assertEqual(order['project']['drawing_name'],'施工图.pdf')
        self.assertEqual(order['project']['drawing_image_url'],'/api/documents/doc_schedule_drawing/preview-image?page=1&thumb=1')
        self.assertEqual(len([candidate for candidate in order['suggestions'] if candidate['exact']]),1)

    def test_fuzzy_name_never_auto_binds_but_unique_order_code_does(self):
        project=self.project('北区综合展示柜扩建')
        working=self.draft();order=working['orders'][0]
        self.assertFalse(order['project_id'])
        self.assertEqual(order['match_status'],'review')
        self.assertTrue(order['suggestions'])
        self.assertFalse(order['suggestions'][0]['exact'])
        with self.store.connect() as con:
            project=self.store.get(con,'projects',project['id'])
            project['external_order_no']='商务二部-001'
            self.store.put(con,'projects',project)
        bound=self.grid()['working']['orders'][0]
        self.assertEqual(bound['project_id'],project['id'])
        self.assertEqual(bound['match_basis'],'order_no')
        second=self.project('另一工程项目')
        with self.store.connect() as con:
            second=self.store.get(con,'projects',second['id'])
            second['external_order_no']='商务二部-001'
            self.store.put(con,'projects',second)
        ambiguous=self.grid()['working']['orders'][0]
        self.assertFalse(ambiguous['project_id'])
        self.assertEqual(ambiguous['match_status'],'review')

    def test_uploaded_image_drawing_is_available_as_project_preview(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is required to validate drawing images')
        project=self.project('北区综合展示柜')
        image=io.BytesIO()
        Image.new('RGB',(8,6),'white').save(image,'PNG')
        (self.store.uploads/'doc_schedule_png.source').write_bytes(image.getvalue())
        with self.store.connect() as con:
            self.store.put(con,'documents',{'id':'doc_schedule_png','project_id':project['id'],'purpose':'drawing',
                'format':'PNG','filename':'施工详图.png','storage_name':'doc_schedule_png.source',
                'created_at':'2026-09-29T10:00:00+00:00','demo':False})
        card=ref.project_reference(project,self.state()['documents'])
        self.assertEqual(card['drawing_name'],'施工详图.png')
        self.assertEqual(card['drawing_image_url'],'/api/documents/doc_schedule_png/badge-image')
        self.assertEqual(self.request(card['drawing_image_url'],raw=True),(200,image.getvalue()))

    def test_priority_position_persists_and_stale_save_does_not_overwrite(self):
        working=self.draft(two=True);saved=self.save(working,priority=3,position=1,confirmed=True)
        self.assertEqual(saved['version'],1)
        reread=self.grid()['working'];self.assertEqual(reread['orders'][0]['priority'],3)
        code,_=self.request('/api/schedule-reference/working',self.payload(working,priority=0))
        self.assertEqual(code,409);self.assertEqual(self.grid()['working']['orders'][0]['priority'],3)

    def test_cycles_rejected_and_unknown_duration_not_zero(self):
        working=self.draft();nodes=[{k:n[k] for k in ('id','enabled','days','predecessors')} for n in working['orders'][0]['nodes']]
        nodes[0]['predecessors']=['packing']
        code,body=self.request('/api/schedule-reference/working',self.payload(working,nodes=nodes))
        self.assertEqual(code,422,body);self.assertIn('循环',body['error'])
        nodes[0]['predecessors']=[];nodes[1]['days']=None
        saved=self.save(working,nodes=nodes)
        self.assertIsNone(saved['orders'][0]['estimate']['total_days'])
        self.assertEqual(self.grid()['working']['version'],1)

    def test_reimport_precise_selected_scope_and_manual_guard(self):
        working=self.draft(two=True);working=self.save(working,priority=3,start_date='2026-09-14',confirmed=True)
        old_key=working['orders'][0]['key'];other=copy.deepcopy(working['orders'][1])
        incoming=self.upload(xlsx([('8.14',worksheet({4:order(木作='2026-08-09')}))]),'生产排程20260814.xlsx')
        payload={**self.payload(working),'incoming_source_id':incoming['source']['id'],'incoming_sheet':'8.14'};payload.pop('changes')
        code,preview=self.request('/api/schedule-reference/replace-preview',payload);self.assertEqual(code,200,preview)
        self.assertTrue(next(r for r in preview['rows'] if r['order_key']==old_key)['has_manual'])
        missing=next(r for r in preview['rows'] if r['order_key']==other['key']);self.assertFalse(missing['selectable'])
        code,_=self.request('/api/schedule-reference/replace',{**payload,'selected_order_keys':[old_key]});self.assertEqual(code,409)
        code,changed=self.request('/api/schedule-reference/replace',{**payload,'selected_order_keys':[old_key],'overwrite_manual':True});self.assertEqual(code,200,changed)
        preserved=next(r for r in changed['working']['orders'] if r['key']==other['key']);self.assertEqual(preserved,other)
        updated=next(r for r in changed['working']['orders'] if r['key']==old_key)
        self.assertEqual(updated['priority'],3);self.assertFalse(updated['confirmed'])
        self.assertEqual(next(n for n in updated['nodes'] if n['id']=='wood')['milestone_date'],'2026-08-09')

    def test_finished_bound_history_cannot_be_replaced_or_edited(self):
        working=self.draft();working=self.save(working,priority=1)
        with self.store.connect() as con:
            value=self.store.get(con,ref.WORKING_KIND,working['id'])
            value['orders'][0]['task_mappings']=[{'task_id':'finished-test'}]
            self.store.put(con,'tasks',{'id':'finished-test','status':'done'})
            self.store.put(con,ref.WORKING_KIND,value)
        code,body=self.request('/api/schedule-reference/working',self.payload(working,priority=3))
        self.assertEqual(code,409,body)

    def test_apply_creates_real_plan_and_reorder_preserves_reservations(self):
        project,task,person,_=self.fixture();working=self.save(self.draft(),confirmed=True,priority=2,position=1)
        data={**self.payload(working),'project_id':project['id'],'task_mappings':[{'node_id':'wood','task_id':task['id'],'expected_task_version':task['execution_version'],'start_date':'2026-09-14','end_date':'2026-09-14','planned_minutes':120}]};data.pop('changes')
        code,result=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,200,result)
        plan=result['plans'][0]
        current=next(t for t in self.state()['tasks'] if t['id']==task['id'])
        self.assertEqual(current['priority'],2);self.assertEqual(current['schedule_position'],1)
        code,changed=self.request('/api/planning/order',{'task_id':task['id'],'expected_task_version':current['execution_version'],'priority':3,'position':0});self.assertEqual(code,200,changed)
        code,after=self.request('/api/planning/'+plan['id']);self.assertEqual(code,200,after)
        self.assertEqual(after['plan']['allocations'],plan['allocations'])
        self.assertEqual(after['plan']['planned_minutes'],120)

    def test_capacity_conflict_keeps_entire_apply_atomic(self):
        project,task,person,_=self.fixture();working=self.save(self.draft(),confirmed=True)
        before=self.state()
        data={**self.payload(working),'project_id':project['id'],'task_mappings':[{'node_id':'wood','task_id':task['id'],'expected_task_version':task['execution_version'],'start_date':'2026-09-14','end_date':'2026-09-14','planned_minutes':999}]};data.pop('changes')
        code,body=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,409,body)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.grid()['working']['version'],working['version'])

    def test_inclusive_plan_dates_and_parallel_longest_path(self):
        result=ref.cycle_estimate([
            {'id':'prepare','enabled':True,'days':1,'predecessors':[]},
            {'id':'wood','enabled':True,'days':3,'predecessors':['prepare']},
            {'id':'metal','enabled':True,'days':2,'predecessors':['prepare']},
            {'id':'join','enabled':True,'days':1,'predecessors':['wood','metal']}], '2026-09-14')
        dates={n['id']:n for n in result['nodes']}
        self.assertEqual(result['total_days'],5)
        self.assertEqual(dates['wood']['start_date'],'2026-09-15')
        self.assertEqual(dates['wood']['end_date'],'2026-09-17')
        self.assertEqual(dates['join']['start_date'],'2026-09-18')

    def mapped_pair(self):
        project,first,person,tasks=self.fixture()
        second=next(t for t in tasks if t['id']!=first['id'] and t['trade']=='木工')
        # Two independent released fixture tasks; worksheet supplies a NEW edge.
        with self.store.connect() as con:
            second['dependencies']=[];self.store.put(con,'tasks',second)
        working=self.save(self.draft(),confirmed=True)
        data={**self.payload(working),'project_id':project['id'],'task_mappings':[
            {'node_id':'wood','task_id':first['id'],'expected_task_version':first['execution_version'],'start_date':'2026-09-14','end_date':'2026-09-14','planned_minutes':120},
            {'node_id':'paint','task_id':second['id'],'expected_task_version':second['execution_version'],'start_date':'2026-09-15','end_date':'2026-09-15','planned_minutes':120}]}
        data.pop('changes');return first,second,working,data

    def test_added_schedule_edge_blocks_actual_start_and_releases_after_predecessor(self):
        first,second,working,data=self.mapped_pair()
        code,result=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,200,result)
        second=next(t for t in self.state()['tasks'] if t['id']==second['id'])
        self.assertEqual(second['dependencies'],[])
        self.assertEqual(second['schedule_dependencies'],[first['id']])
        code,error=self.task_action(second,'status',{'status':'in_progress','expected_execution_version':second['execution_version']})
        self.assertEqual(code,409,error);self.assertIn('前置工序尚未完成',str(error))
        with self.store.connect() as con:
            first=self.store.get(con,'tasks',first['id']);first['status']='done';first['completed_quantity']=first['quantity'];first['remaining_quantity']=0;self.store.put(con,'tasks',first)
            blockers=self.store.start_blockers(con,second)
        self.assertFalse(any('前置工序尚未完成' in reason for reason in blockers),blockers)

    def test_multi_plan_move_keeps_ids_and_validates_final_reservations(self):
        first,second,working,data=self.mapped_pair()
        code,result=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,200,result)
        state={t['id']:t for t in self.state()['tasks']};plans={p['task_id']:p for p in result['plans']}
        data['expected_version']=result['working']['version']
        for idx,item in enumerate(data['task_mappings']):
            item.update(expected_task_version=state[item['task_id']]['execution_version'],expected_plan_version=plans[item['task_id']]['version'],start_date=f'2026-09-{16+idx}',end_date=f'2026-09-{16+idx}')
        code,moved=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,200,moved)
        self.assertEqual({p['id'] for p in moved['plans']},{p['id'] for p in result['plans']})
        self.assertEqual({p['start_date'] for p in moved['plans']},{'2026-09-16','2026-09-17'})

    def test_second_mapping_failure_rolls_back_first_plan_dependency_and_version(self):
        first,second,working,data=self.mapped_pair();data['task_mappings'][1]['planned_minutes']=999
        before=self.state()
        code,error=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,409,error)
        self.assertEqual(self.state(),before)
        with self.store.connect() as con:self.assertEqual(self.store.all(con,'plans'),[])
        self.assertEqual(self.grid()['working']['version'],working['version'])

    def test_combined_engineering_and_schedule_cycle_is_rejected(self):
        first,second,working,data=self.mapped_pair()
        with self.store.connect() as con:
            original=self.store.get(con,'tasks',first['id']);original['dependencies']=[second['id']];self.store.put(con,'tasks',original)
        before=self.state();code,error=self.request('/api/schedule-reference/apply',data)
        self.assertEqual(code,409,error);self.assertIn('循环',error['error']);self.assertEqual(self.state(),before)

    def test_missing_mapped_predecessor_remains_an_actual_start_blocker(self):
        first,second,working,data=self.mapped_pair();data['task_mappings']=data['task_mappings'][1:]
        code,result=self.request('/api/schedule-reference/apply',data);self.assertEqual(code,200,result)
        task=next(t for t in self.state()['tasks'] if t['id']==second['id'])
        self.assertEqual(task['schedule_unmapped_predecessors'],['木作'])
        code,error=self.task_action(task,'status',{'status':'in_progress','expected_execution_version':task['execution_version']});self.assertEqual(code,409,error)
        self.assertIn('排程前序尚未对应任务',str(error))

if __name__=='__main__':unittest.main()
