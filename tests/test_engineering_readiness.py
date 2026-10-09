"""Evidence-first assistant checks against isolated real stores and release gates."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access_control
import app
import agent_assistant
import engineering_readiness as readiness
import operations


class EngineeringReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False, empty=True)
        with self.store.connect() as con:
            self.project = self.store.new_project(con, {'name': '测试珠宝展柜', 'factory_type': 'cabinet'})
            self.project['evidence_policy'] = 'legacy_fixture'
            self.store.put(con, 'projects', self.project)
        access_control.clear_actor()

    def tearDown(self):
        access_control.clear_actor()
        self.temp.cleanup()

    def rows(self):
        with self.store.connect() as con:
            return [tuple(row) for row in con.execute('SELECT kind,id,data FROM entities ORDER BY kind,id')]

    def ask(self, text='检查当前订单能否拆单', actor=None, **extra):
        before = self.rows()
        files = sorted(str(p.relative_to(self.store.data_dir)) for p in self.store.data_dir.rglob('*'))
        request = {'message': text, 'project_id': self.project['id'], **extra}
        with self.store.connect() as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            response = agent_assistant.respond(self.store, con, request, actor=actor)
        self.assertEqual(before, self.rows())
        self.assertEqual(files, sorted(str(p.relative_to(self.store.data_dir)) for p in self.store.data_dir.rglob('*')))
        self.assertTrue(all(a['type'] in ('navigate',) for a in response['actions']))
        return response

    def put(self, kind, value):
        with self.store.connect() as con:
            self.store.put(con, kind, value)
        return value

    def doc(self, name='施工图.pdf', **extra):
        return self.put('documents', {'id': 'doc_' + str(len(self.rows())), 'project_id': self.project['id'],
                   'filename': name, 'purpose': 'drawing', 'status': 'needs_conversion',
                   'part_count': 0, 'revision': self.project['revision'], 'resolved': False,
                   'sha256': hashlib.sha256(name.encode()).hexdigest(), **extra})

    def bom(self):
        data = {'unit': 'mm', 'parts': [{'id': 'P1', 'name': '侧板', 'category': 'wood', 'material': '多层板',
                    'length': 600, 'width': 400, 'thickness': 18, 'quantity': 2, 'finish': '免漆'}]}
        with self.store.connect() as con:
            result = self.store.import_file(con, {'project_id': self.project['id'], 'filename': '生产BOM.json',
                 'content_base64': base64.b64encode(json.dumps(data).encode()).decode()})
            self.project = self.store.get(con, 'projects', self.project['id'])
        return result['parts'][0], result['document']

    def test_empty_order_points_to_engineering_sources_not_fake_bom(self):
        for message in ('检查当前订单能否拆单', '帮我拆单', '检查漏项', '下一步', '检查拆单依据'):
            with self.subTest(message=message):
                response = self.ask(message)
                report = response['readiness']
                self.assertEqual(report['stage'], 'sources')
                self.assertEqual(response['mode'], 'local_commands')
                self.assertEqual(response['analysis_kind'], 'engineering_readiness')
                self.assertEqual(report['part_counts']['total'], 0)
                self.assertEqual(response['actions'][0]['route']['projectId'], self.project['id'])
                self.assertEqual(report['engine']['model_called'], False)
                self.assertNotIn('confidence', json.dumps(report))
                self.assertNotIn('%', json.dumps(report))

    def test_render_only_is_never_a_production_dimension_source(self):
        self.doc('珠宝柜效果图.png', purpose='render', status='ready', resolved=True)
        result = self.ask()['readiness']
        self.assertEqual(result['stage'], 'sources')
        self.assertEqual(result['source_counts']['appearance'], 1)
        self.assertIn('不能作为尺寸', result['sources'][0]['ability'])
        self.assertIn('appearance_only', [c['id'] for c in result['checks']])

    def test_native_files_receive_honest_format_specific_guidance(self):
        for name in ('装配.SLDASM', '零件.SLDPRT', '外观.MAX', '细部.DWG', '机架.STEP'):
            self.doc(name)
        sources = {s['filename']: s for s in self.ask()['readiness']['sources']}
        self.assertIn('SolidWorks 导出 BOM', sources['装配.SLDASM']['ability'])
        self.assertEqual(sources['外观.MAX']['role'], 'appearance_model')
        self.assertIn('不能', readiness.source_capability({'filename': 'x.glb'})[2])
        self.assertIn('几何', sources['机架.STEP']['ability'])

    def test_bom_fields_use_real_validator_and_current_review_gate(self):
        part, _ = self.bom()
        part['thickness'] = None
        self.put('parts', part)
        result = self.ask()['readiness']
        self.assertEqual(result['stage'], 'parts')
        expected = app.part_blockers(part)
        self.assertTrue(all(item in result['release_blockers'] for item in expected))
        self.assertIn('厚度', next(c['detail'] for c in result['checks'] if c['id'] == 'part_fields'))
        self.assertEqual(result['part_counts']['incomplete'], 1)
        self.assertEqual(result['part_counts']['pending'], 1)

    def test_production_draft_cannot_be_misreported_as_confirmed_bom(self):
        part, _ = self.bom()
        part['draft_only'] = True
        self.put('parts', part)
        result = self.ask()['readiness']
        self.assertEqual(result['part_counts']['draft_only'], 1)
        self.assertIn('生产 BOM', next(c['detail'] for c in result['checks'] if c['id'] == 'part_fields'))

    def test_review_generate_publish_and_planning_follow_recorded_stage(self):
        part, _ = self.bom()
        self.assertEqual(self.ask()['readiness']['stage'], 'review')
        with self.store.connect() as con:
            self.store.review_part(con, part['id'], {'approved': True})
        self.assertEqual(self.ask()['readiness']['stage'], 'tasks')
        with self.store.connect() as con:
            self.store.generate(con, self.project['id'])
        report = self.ask()['readiness']
        self.assertEqual(report['stage'], 'publish')
        self.assertTrue(report['release_ready'])
        with self.store.connect() as con:
            self.store.release(con, self.project['id'])
        self.assertEqual(self.ask()['readiness']['stage'], 'planning')

    def prepare_released(self):
        part, _ = self.bom()
        with self.store.connect() as con:
            self.store.review_part(con, part['id'], {'approved': True})
            self.store.generate(con, self.project['id'])
            self.store.release(con, self.project['id'])
            return self.store.active_tasks(con, self.project['id'])

    def test_completed_operations_lead_to_inspection_not_assumed_delivery(self):
        tasks = self.prepare_released()
        for task in tasks:
            self.put('tasks', {**task, 'status': 'done', 'completed_quantity': task['quantity']})
        response = self.ask('下一步')
        self.assertEqual(response['readiness']['stage'], 'delivery')
        self.assertEqual(response['actions'][0]['route'], {
            'page': 'readiness', 'projectId': self.project['id'], 'opTab': 'inspections'})
        with self.store.connect() as con:
            self.assertFalse(app.fulfillment.is_closed(self.store.get(con, 'projects', self.project['id'])))
        self.assertNotIn('已发货', response['message'])

    def test_missing_material_and_other_pauses_have_precise_next_destination(self):
        tasks = self.prepare_released()
        task = tasks[0]
        self.put('tasks', {**task, 'status': 'blocked', 'pause_reason': 'equipment'})
        response = self.ask('下一步')
        self.assertEqual(response['actions'][0]['route'], {
            'page': 'tasks', 'projectId': self.project['id'], 'taskFocus': 'paused'})
        self.put('materials', {'id': 'mat_test', 'project_id': self.project['id'], 'name': '板材',
            'required_quantity': 5, 'accepted_quantity': 2, 'unit': '张', 'task_ids': [task['id']]})
        response = self.ask('下一步')
        self.assertEqual(response['actions'][0]['route'], {
            'page': 'readiness', 'projectId': self.project['id'], 'opTab': 'materials'})
        self.assertIn('缺料记录 1 项', json.dumps(response, ensure_ascii=False))

    def test_duplicate_sha_warns_without_deleting_or_inflating_bom_quantity(self):
        part, doc = self.bom()
        self.put('documents', {**doc, 'id': 'doc_copy', 'filename': '生产BOM副本.json'})
        result = self.ask()['readiness']
        self.assertEqual(result['source_counts']['duplicate_groups'], 1)
        self.assertEqual(result['part_counts']['total'], 1)
        self.assertEqual(part['quantity'], 2)
        duplicate = next(c for c in result['checks'] if c['id'] == 'duplicate_documents')
        self.assertEqual(duplicate['severity'], 'attention')

    def test_changed_source_hash_and_superseded_document_are_not_silent(self):
        part, doc = self.bom()
        part['source']['sha256'] = 'a' * 64
        self.put('parts', part)
        report = self.ask()['readiness']
        self.assertEqual(report['stage'], 'sources')
        self.assertEqual(report['part_counts']['source_conflicts'], 1)
        doc['superseded'] = True
        self.put('documents', doc)
        result = self.ask()['readiness']
        self.assertIn('换版', next(c['detail'] for c in result['checks'] if c['id'] == 'source_conflicts'))

    def test_on_disk_content_change_is_detected_without_trusting_unchanged_metadata(self):
        _, doc = self.bom()
        self.assertEqual(self.ask()['readiness']['source_counts']['verified'], 1)
        (self.store.uploads / doc['storage_name']).write_bytes(b'replaced bytes')
        report = self.ask()['readiness']
        self.assertEqual(report['sources'][0]['integrity'], 'changed')
        self.assertEqual(report['stage'], 'sources')
        self.assertFalse(report['release_ready'])
        self.assertIn('校验值不一致', next(c['detail'] for c in report['checks'] if c['id'].startswith('integrity_')))

    def test_source_integrity_never_follows_cross_factory_path_or_symlink(self):
        _, doc = self.bom()
        target = self.store.uploads / doc['storage_name']
        target.unlink()
        target.symlink_to(Path(__file__).resolve())
        report = self.ask()['readiness']
        self.assertEqual(report['sources'][0]['integrity'], 'unavailable')
        self.put('documents', {**doc, 'storage_name': '../private.json'})
        report = self.ask()['readiness']
        self.assertEqual(report['sources'][0]['integrity'], 'unavailable')

    def test_old_but_still_current_document_revision_is_not_falsely_stale(self):
        part, doc = self.bom()
        self.project['revision'] += 1
        self.put('projects', self.project)
        report = self.ask()['readiness']
        self.assertEqual(report['part_counts']['source_conflicts'], 0)
        self.assertEqual(report['sources'][0]['revision'], doc['revision'])
        self.assertNotEqual(report['revision'], doc['revision'])

    def test_effect_image_linked_as_part_evidence_requires_engineering_review(self):
        part, doc = self.bom()
        doc['purpose'] = 'render'
        self.put('documents', doc)
        report = self.ask()['readiness']
        self.assertEqual(report['part_counts']['source_conflicts'], 1)
        self.assertIn('外观资料', next(c['detail'] for c in report['checks'] if c['id'] == 'source_conflicts'))

    def test_closed_project_only_links_delivered_order(self):
        self.project['fulfillment_status'] = 'shipped'
        self.put('projects', self.project)
        response = self.ask('帮我拆单')
        self.assertEqual(response['readiness']['stage'], 'closed')
        self.assertFalse(response['readiness']['release_ready'])
        self.assertEqual(response['actions'][0]['route']['page'], 'projects')
        self.assertEqual(response['results'], [])

    def test_completed_order_waiting_for_shipping_links_delivery_registration(self):
        self.project['fulfillment_status'] = 'completed'
        self.put('projects', self.project)
        response = self.ask('下一步')
        self.assertEqual(response['readiness']['stage'], 'delivery')
        self.assertFalse(response['readiness']['release_ready'])
        self.assertFalse(response['readiness']['release_gate_passed'])
        self.assertEqual(response['actions'][0]['route'], {
            'page': 'readiness', 'projectId': self.project['id'], 'opTab': 'deliveries'})
        self.assertIn('待发货', response['message'])
        self.assertNotIn('已发货', response['message'])
        self.assertEqual(response['results'], [])
        with self.store.connect() as con:
            self.assertTrue(app.fulfillment.is_closed(self.store.get(con, 'projects', self.project['id'])))

    def test_archived_completed_order_stays_history_only(self):
        self.project.update(fulfillment_status='completed', archived=True)
        self.put('projects', self.project)
        before = self.rows()
        with self.store.connect() as con:
            con.execute('PRAGMA query_only=ON')
            report = readiness.inspect_project(self.store, con, self.project)
        self.assertEqual(before, self.rows())
        self.assertEqual(report['stage'], 'closed')
        self.assertEqual(report['next_step']['route'], {'page': 'projects', 'projectId': self.project['id']})
        self.assertFalse(report['release_ready'])
        self.assertIn('归档', report['summary'])
        self.assertNotIn('登记发货', report['summary'])

    def test_worker_does_not_get_whole_project_engineering_data(self):
        self.doc('技术保密图纸.pdf')
        self.put('tasks', {'id': 'task_worker', 'project_id': self.project['id'], 'title': '自己的工作',
            'revision': 1, 'quantity': 1, 'status': 'ready', 'assignee': 'person_a'})
        result = self.ask(actor={'role': 'worker', 'access_enabled': True, 'person_id': 'person_a'})
        self.assertNotIn('readiness', result)
        self.assertNotIn('技术保密图纸', json.dumps(result, ensure_ascii=False))
        self.assertIn('技术员', result['message'])

    def test_multiple_projects_select_first_and_invalid_scope_never_leaks(self):
        with self.store.connect() as con:
            self.store.new_project(con, {'name': '另一个客户订单'})
        result = self.ask(project_id='')
        self.assertNotIn('readiness', result)
        self.assertEqual(len(result['results']), 2)
        result = self.ask(project_id='prj_foreign')
        self.assertNotIn('readiness', result)
        self.assertEqual(result['results'], [])
        other = tempfile.TemporaryDirectory()
        try:
            other_store = app.Store(other.name, seed=False, empty=True)
            with other_store.connect() as con:
                response = agent_assistant.respond(other_store, con, {'message': '帮我拆单', 'project_id': self.project['id']})
            self.assertNotIn('测试珠宝展柜', json.dumps(response, ensure_ascii=False))
        finally:
            other.cleanup()

    def test_negation_document_instructions_and_explicit_navigation_remain_safe(self):
        for message in ('不要帮我拆单', '图纸里写着帮我拆单', '原文：下一步'):
            self.assertNotIn('readiness', self.ask(message))
        result = self.ask('打开图纸拆单')
        self.assertNotIn('readiness', result)
        self.assertEqual(result['actions'][0]['route']['page'], 'drawing')

    def test_model_configuration_is_reported_without_model_or_network_call(self):
        with patch('langgraph_agent.model_settings', return_value={'model': 'private-name', 'endpoint': 'http://127.0.0.1/private'}), \
             patch('langgraph_agent.local_summary', side_effect=AssertionError('No model call')):
            result = self.ask()['readiness']
        self.assertTrue(result['engine']['local_model_configured'])
        self.assertFalse(result['engine']['model_called'])
        self.assertNotIn('private-name', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))

    def test_release_helper_preserves_document_gate_order_and_resolution(self):
        part, doc = self.bom()
        self.doc('原生工程.SLDASM')
        process = self.doc('工艺记录.pdf', purpose='process', status='needs_review')
        self.doc('外观.png', purpose='render', status='ready')
        self.doc('旧图.DWG', superseded=True)
        self.doc('已补录.DWG', resolved=True)
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', self.project['id'])
            expected = [part['name'] + ' 尚未审核通过', '原生工程.SLDASM 尚未完成转换/补录核验',
                '工艺记录.pdf 行业工艺依据待核验，请关联已审核的当前工作包后核验',
                '已补录.DWG 的原件、配套清单或构件核验关联已失效，请重新核对', '请按当前版本重新生成工艺任务']
            self.assertEqual(readiness.release_blockers(self.store, con, project, app.part_blockers), expected)
            with self.assertRaises(app.APIError) as error:
                self.store.release(con, project['id'])
            self.assertEqual(error.exception.details, expected)

    def test_workflow_release_rules_are_shared_not_approximated(self):
        self.project['workflow_id'] = 'wf_test'
        self.put('projects', self.project)
        self.put('project_workflows', {'id': 'wf_test', 'project_id': self.project['id'], 'status': 'draft',
           'revision': 0, 'version': 1, 'industry_id': 'wood', 'task_ids': ['task_missing'],
           'objects': [{'code': 'A1', 'name': '批次', 'document_ids': ['doc_missing'], 'industry_fields': {}}],
           'object_fields': [{'id': 'drawing_revision', 'label': '图纸版本', 'required': True}]})
        with self.store.connect() as con:
            expected = operations.release_blockers(self.store, con, self.project)
        report = self.ask()['readiness']
        self.assertTrue(all(text in report['release_blockers'] for text in expected))
        self.assertEqual(report['stage'], 'workflow')
        self.assertIn('图纸版本', next(c['detail'] for c in report['checks'] if c['id'] == 'workflow_gates'))


if __name__ == '__main__':
    unittest.main()
