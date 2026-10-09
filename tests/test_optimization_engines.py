"""Real solver integration on disposable Stores, plus independent certificate checks."""
from copy import deepcopy
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import optimization_engines as engines
import production
import scheduling
import test_scheduling as fixtures

REAL = os.environ.get('KANPACE_TEST_REAL_ENGINES') == '1'


@unittest.skipUnless(REAL,'Set KANPACE_TEST_REAL_ENGINES=1 after installing the optional engines')
class RealScheduleTests(unittest.TestCase):
    setUp=fixtures.SchedulingTests.setUp
    tearDown=fixtures.SchedulingTests.tearDown
    worker=fixtures.SchedulingTests.worker
    project_create=fixtures.SchedulingTests.project_create
    center=fixtures.SchedulingTests.center
    task=fixtures.SchedulingTests.task
    put=fixtures.SchedulingTests.put
    all=fixtures.SchedulingTests.all

    def advice(self,**extra):
        with self.store.connect() as con:
            return engines.schedule_advice(self.store,con,{'start_date':'2026-09-07','horizon_days':7,
                'time_limit_seconds':2,'allow_fallback':False,**extra})

    def test_real_solver_multiresource_join_and_read_only(self):
        wc=self.center(); a=self.task(90,wc=wc); b=self.task(120,person=self.worker('另一人'),wc=wc)
        final=self.task(45,deps=[a,b]); before=self.all('tasks')
        result=self.advice()
        self.assertEqual(result['engine']['used'],'Google OR-Tools CP-SAT')
        self.assertIn(result['engine']['status'],['OPTIMAL','FEASIBLE'])
        self.assertTrue(result['validation']['valid'])
        self.assertEqual(result['summary']['scheduled'],3)
        rows={r['task_id']:r for r in result['rows']}
        self.assertGreaterEqual(rows[final['id']]['start_at'],max(rows[a['id']]['ready_at'],rows[b['id']]['ready_at']))
        self.assertEqual(self.all('tasks'),before)
        self.assertFalse(self.all('plans')); self.assertFalse(self.all('scheduling_scenarios'))

    def test_material_gate_expected_date_and_unknown_duration(self):
        a=self.task(60); self.task(None)
        material={'id':'mat_optimizer','project_id':self.project['id'],'task_ids':[a['id']],'name':'待验板材','unit':'张',
                  'required_quantity':2,'accepted_quantity':0,'version':1,'expected_date':None}
        self.put('materials',material)
        self.assertEqual(self.advice()['summary']['scheduled'],0)
        material['expected_date']='2026-09-09'; self.put('materials',material)
        result=self.advice(); self.assertEqual(result['summary']['scheduled'],1)
        self.assertGreaterEqual(result['rows'][0]['start_at'],'2026-09-09T08:00')
        self.assertEqual(self.all('materials')[0]['accepted_quantity'],0)

    def test_freeze_non_interruptible_and_stale_persistence(self):
        a=self.task(60)
        with self.store.connect() as con:
            first=scheduling.preview(self.store,con,{'start_date':'2026-09-07','task_ids':[a['id']]})['scenario']
            scheduling.apply(self.store,con,first['id'],{'expected_version':1,'note':'冻结原计划'})
        b=self.task(120); before=deepcopy(self.all('plans'))
        result=self.advice(non_interruptible_task_ids=[b['id']])
        self.assertEqual(len(result['rows'][0]['minute_segments']),1)
        self.assertGreaterEqual(result['rows'][0]['start_at'],'2026-09-07T09:00')
        self.assertEqual(self.all('plans'),before)
        b['execution_version']=1; self.put('tasks',b)
        with self.store.connect() as con:
            with self.assertRaises(production.ProductionError) as caught:
                engines.persist_schedule(self.store,con,result)
        self.assertEqual(caught.exception.status,409)

    def test_explicit_fallback_never_claims_solver_success(self):
        self.task(60)
        with patch.object(engines,'_python',return_value=Path('/missing/kanpace-worker-python')):
            result=self.advice(allow_fallback=True)
        self.assertEqual(result['engine']['used'],'KANPACE heuristic')
        self.assertEqual(result['engine']['status'],'UNAVAILABLE')
        self.assertTrue(result['engine']['fallback_reason'])
        self.assertEqual(result['summary']['scheduled'],1)

    def test_real_solver_improves_two_stage_order_baseline(self):
        second=self.worker('第二工序负责人')
        a1=self.task(180); self.task(20,person=second,deps=[a1])
        b1=self.task(20); self.task(180,person=second,deps=[b1])
        result=self.advice(horizon_days=1)
        self.assertEqual(result['summary']['scheduled'],4)
        self.assertEqual(result['comparison']['baseline_metrics']['completion_span_minutes'],380)
        self.assertEqual(result['comparison']['optimized_metrics']['completion_span_minutes'],220)

    def test_preview_apply_keeps_task_state_and_owner(self):
        a=self.task(60,status='blocked')
        with self.store.connect() as con:
            prep=engines.prepare_schedule(self.store,con,{'start_date':'2026-09-07','horizon_days':2,'time_limit_seconds':2,'allow_fallback':False})
        result=engines.solve_prepared(prep)
        with self.store.connect() as con:
            saved=engines.persist_schedule(self.store,con,result)['scenario']
            applied=scheduling.apply(self.store,con,saved['id'],{'expected_version':saved['version'],'note':'仅确认计划'})
        self.assertEqual(self.all('tasks')[0]['status'],'blocked')
        self.assertEqual(self.all('tasks')[0]['assignee'],a['assignee'])
        self.assertEqual(applied['plans'][0]['material_status'],'pending')


class CertificateTests(unittest.TestCase):
    def test_schedule_validator_rejects_conflict_and_bad_duration(self):
        payload={'jobs':[{'id':'a','duration':10,'release':0,'windows':[[0,30]],'resources':['p'],'dependencies':[],'wait_minutes':0},
                         {'id':'b','duration':10,'release':0,'windows':[[0,30]],'resources':['p'],'dependencies':['a'],'wait_minutes':0}]}
        output={'rows':[{'task_id':'a','start':0,'end':10,'segments':[[0,10]]},
                        {'task_id':'b','start':5,'end':15,'segments':[[5,15]]}]}
        result=engines.validate_schedule(payload,output)
        self.assertFalse(result['valid']); self.assertGreaterEqual(len(result['errors']),2)

    def test_packing_requires_review_and_same_material(self):
        data=packing_fixture(); data['dimensions_confirmed']=False
        with self.assertRaises(production.ProductionError): engines.packing_request(data)
        data=packing_fixture(); data['items'][0]['material']='玻璃'
        with self.assertRaises(production.ProductionError): engines.packing_request(data)
        data=packing_fixture(); data['grain']='width'; data['items'][0]['allow_rotate']=True
        with self.assertRaises(production.ProductionError): engines.packing_request(data)


def packing_fixture():
    return {'dimensions_confirmed':True,'material':'审核测试板材','thickness_mm':18,'grain':'none','kerf_mm':5,'trim_mm':10,
            'stock':{'width_mm':1000,'height_mm':1000,'quantity':5,'cost_per_sheet':120},
            'items':[{'id':'panel_a','width_mm':480,'height_mm':480,'quantity':4,'allow_rotate':False}],
            'baseline_sheet_count':2,'time_limit_seconds':2}


@unittest.skipUnless(REAL,'Set KANPACE_TEST_REAL_ENGINES=1 after installing the optional engines')
class RealPackingTests(unittest.TestCase):
    def test_real_guillotine_layout_cost_and_independent_check(self):
        data=packing_fixture(); result=engines.packing_preview(data)
        self.assertEqual(result['engine']['used'],'PackingSolver rectangle-guillotine')
        self.assertTrue(result['validation']['valid'])
        self.assertEqual(result['summary']['sheet_count'],1)
        self.assertEqual(result['summary']['placed_quantity'],4)
        self.assertEqual(result['summary']['material_cost'],120)
        self.assertEqual(result['baseline_comparison']['material_cost_saved'],120)
        self.assertIn('PLATE_ID',result['certificate_csv'])
        bad=deepcopy(result['layouts']); bad[0]['pieces'][1]['x_mm']=bad[0]['pieces'][0]['x_mm']; bad[0]['pieces'][1]['y_mm']=bad[0]['pieces'][0]['y_mm']
        self.assertFalse(engines.validate_packing(engines.packing_request(data),bad)['valid'])

    def test_real_rotation_and_insufficient_stock_are_not_ignored(self):
        data=packing_fixture(); data.update(trim_mm=0,kerf_mm=0)
        data['stock'].update(width_mm=500,height_mm=1000,quantity=1)
        data['items'][0].update(width_mm=900,height_mm=400,quantity=1,allow_rotate=True)
        result=engines.packing_preview(data)
        self.assertTrue(result['layouts'][0]['pieces'][0]['rotated'])
        data['grain']='width'; data['items'][0]['allow_rotate']=False
        with self.assertRaises(production.ProductionError): engines.packing_preview(data)
        data=packing_fixture(); data.update(trim_mm=0,kerf_mm=5)
        data['items'][0].update(width_mm=500,height_mm=500)
        data['stock']['quantity']=1
        with self.assertRaises(production.ProductionError): engines.packing_preview(data)

    def test_kerf_and_rotation_affect_real_layout(self):
        data=packing_fixture(); data['trim_mm']=0; data['kerf_mm']=0
        data['items'][0].update(width_mm=500,height_mm=500)
        self.assertEqual(engines.packing_preview(data)['summary']['sheet_count'],1)
        data['kerf_mm']=5
        self.assertEqual(engines.packing_preview(data)['summary']['sheet_count'],4)


if __name__=='__main__': unittest.main()
