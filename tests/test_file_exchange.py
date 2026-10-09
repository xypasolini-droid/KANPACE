"""File exchange round trips use temporary SQLite and synthetic CSV/XLSX only."""
import base64
from copy import deepcopy
import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import file_exchange as exchange
import operations
from kanpace.core.errors import APIError


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = app.Store(self.temp.name, seed=False)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, *args, **kwargs):
        with self.store.connect() as con:
            return getattr(exchange, method)(self.store, con, *args, **kwargs)

    def all(self, kind):
        with self.store.connect() as con:
            return self.store.all(con, kind)

    def put(self, kind, item):
        with self.store.connect() as con:
            self.store.put(con, kind, item)

    def payload(self, rows=None, entity_type='projects', mapping=None, **extra):
        headers = ['订单号', '项目', '客户', '交期', '工厂类型']
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows or [['S001', '测试机械', '甲客户', '2026-10-09', 'machinery']])
        return {'filename': '订单.csv', 'content_base64': base64.b64encode(output.getvalue().encode('utf-8-sig')).decode(),
                'entity_type': entity_type, 'mapping': mapping if mapping is not None else
                {'external_key': '订单号', 'name': '项目', 'client': '客户', 'due_date': '交期', 'factory_type': '工厂类型'},
                'source_system': '测试ERP', **extra}

    def preview(self, payload=None):
        return self.call('prepare', payload or self.payload())['preview']

    def commit(self, preview):
        return self.call('apply', preview['id'], {'expected_version': preview['version']})

    def test_inspect_without_mapping_returns_headers_and_never_writes(self):
        result = self.call('prepare', self.payload(mapping={}))
        self.assertIsNone(result['preview'])
        self.assertEqual(result['headers'][0], '订单号')
        self.assertEqual(result['sample_rows'][0]['values']['项目'], '测试机械')
        self.assertEqual(self.all('exchange_previews'), [])
        self.assertEqual(self.all('projects'), [])
        self.assertEqual(self.all('events'), [])

    def test_preview_commit_idempotent_and_source_row_retained(self):
        preview = self.preview()
        self.assertEqual(preview['summary'], {'create': 1, 'update': 0, 'skip': 0, 'error': 0})
        self.assertEqual(self.all('projects'), [])
        self.assertEqual(self.all('events'), [])
        self.assertNotIn('source_content_base64', preview)
        receipt = self.commit(preview)
        self.assertEqual(len(self.all('projects')), 1)
        self.assertEqual(self.all('projects')[0]['status'], 'draft')
        self.assertEqual(self.all('projects')[0]['factory_type'], 'machinery')
        link = self.all('exchange_links')[0]
        self.assertEqual((link['external_key'], link['filename'], link['row_number']), ('S001', '订单.csv', 2))
        second = self.commit(preview)
        self.assertTrue(second['duplicate'])
        self.assertEqual(second['receipt'], receipt['receipt'])
        repeated = self.call('prepare', self.payload())
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(repeated['preview']['id'], preview['id'])
        self.assertEqual(len(self.all('projects')), 1)

    def test_update_preview_shows_changes_and_rejects_stale_business_record(self):
        self.commit(self.preview())
        preview = self.preview(self.payload([['S001', '改过名称', '甲客户', '2026-10-11', 'machinery']]))
        row = preview['rows'][0]
        self.assertEqual(row['action'], 'update')
        self.assertEqual({c['field'] for c in row['changes']}, {'name', 'due_date'})
        project = self.all('projects')[0]
        project['client'] = '其他管理员更改'
        self.put('projects', project)
        with self.assertRaises(exchange.ExchangeError) as error:
            self.commit(preview)
        self.assertEqual(error.exception.details['code'], 'preview_stale')
        self.assertEqual(self.all('projects')[0]['name'], '测试机械')

    def test_two_previews_cannot_create_same_external_order_twice(self):
        a = self.preview()
        payload = self.payload(); payload['filename'] = '订单副本.csv'
        b = self.preview(payload)
        self.commit(a)
        with self.assertRaises(exchange.ExchangeError):
            self.commit(b)
        self.assertEqual(len(self.all('projects')), 1)
        fresh = self.preview(payload)
        self.assertEqual(fresh['summary']['skip'], 1)
        self.commit(fresh)
        self.assertEqual(len(self.all('projects')), 1)

    def test_invalid_duplicate_and_formula_mapping_cannot_apply_partial_rows(self):
        preview = self.preview(self.payload([['S001', '有效', '', '2026-10-09', 'cabinet'],
                                             ['S001', '重复编号', '', '2026-10-10', 'cabinet']]))
        self.assertEqual(preview['summary']['error'], 1)
        with self.assertRaises(exchange.ExchangeError):
            self.commit(preview)
        self.assertEqual(self.all('projects'), [])
        payload = self.payload(); payload['mapping']['status'] = '项目'
        with self.assertRaises(exchange.ExchangeError):
            self.call('prepare', payload)

    def test_dates_require_year_and_template_type_not_silently_guessed(self):
        preview = self.preview(self.payload([['S001', '测试', '', '10/09', 'cabinet']]))
        self.assertEqual(preview['summary']['error'], 1)
        payload = self.payload(); del payload['mapping']['factory_type']
        missing = self.preview(payload)
        self.assertEqual(missing['summary']['error'], 1)
        payload['defaults'] = {'factory_type': 'site'}
        valid = self.preview(payload)
        self.assertEqual(valid['summary']['error'], 0)
        self.commit(valid)
        self.assertEqual(self.all('projects')[0]['factory_type'], 'site')

    def test_xlsx_roundtrip_preserves_ids_and_does_not_execute_formulas(self):
        data = exchange.xlsx_bytes(['单号', '项目', '类型'], [['000012', '=cmd()', 'cabinet']])
        payload = {'filename': '互联.xlsx', 'content_base64': base64.b64encode(data).decode(), 'entity_type': 'projects',
                   'mapping': {'external_key': '单号', 'name': '项目', 'factory_type': '类型'}}
        preview = self.preview(payload)
        self.assertEqual(preview['rows'][0]['data']['external_key'], '000012')
        self.assertEqual(preview['rows'][0]['data']['name'], '=cmd()')
        self.commit(preview)
        exported = self.call('export_data', 'projects', format='xlsx')
        with ZipFile(io.BytesIO(exported['bytes'])) as zip:
            self.assertNotIn(b'<f>', zip.read('xl/worksheets/sheet1.xml'))
        parsed = exchange.inspect_content(exported['filename'], exported['bytes'])
        self.assertEqual(parsed['rows'][0]['cells']['原系统订单号']['value'], '000012')
        csv_export = self.call('export_data', 'projects')
        self.assertIn("'=cmd()", csv_export['bytes'].decode('utf-8-sig'))

    def test_xlsx_formula_value_is_blocked_even_with_cached_result(self):
        raw = exchange.xlsx_bytes(['单号', '项目', '类型'], [['1001', '测试', 'cabinet']])
        output = io.BytesIO()
        with ZipFile(io.BytesIO(raw)) as original, ZipFile(output, 'w') as modified:
            for entry in original.infolist():
                content = original.read(entry.filename)
                if entry.filename == 'xl/worksheets/sheet1.xml':
                    content = content.replace(b'<ns0:is><ns0:t xml:space="preserve">1001</ns0:t></ns0:is>', b'<ns0:f>1+1000</ns0:f><ns0:v>1001</ns0:v>')
                modified.writestr(entry, content)
        payload = {'filename': '公式.xlsx', 'content_base64': base64.b64encode(output.getvalue()).decode(), 'entity_type': 'projects',
                   'mapping': {'external_key': '单号', 'name': '项目', 'factory_type': '类型'}}
        preview = self.preview(payload)
        self.assertEqual(preview['summary']['error'], 1)
        self.assertIn('公式', preview['rows'][0]['errors'][0])

    def test_custom_people_capacity_null_and_cross_factory_validation(self):
        with self.store.connect() as con:
            factory = operations.save_factory(self.store, con, {'name': '测试机电厂', 'factory_type': 'machinery'})['factory']
        raw = exchange.xlsx_bytes(['员工号', '姓名', '技能', '容量'], [['EMP01', '调试技师', '调试、编程', '']])
        payload = {'filename': '员工.xlsx', 'content_base64': base64.b64encode(raw).decode(), 'entity_type': 'people',
                   'mapping': {'external_key': '员工号', 'name': '姓名', 'skills': '技能', 'capacity_minutes': '容量'},
                   'defaults': {'factory_id': factory['id']}}
        preview = self.preview(payload)
        self.assertEqual(preview['summary']['error'], 0, preview)
        self.assertEqual(len(self.all('people')), 8)
        self.commit(preview)
        person = self.all('people')[-1]
        self.assertEqual(person['skills'], ['调试', '编程'])
        self.assertIsNone(person['capacity_minutes'])
        self.assertEqual(person['factory_id'], factory['id'])

    def people_payload(self, rows, headers=None, **extra):
        raw = exchange.xlsx_bytes(headers or ['姓名', '车间', '岗位'], rows)
        return {'filename': '人员.xlsx', 'content_base64': base64.b64encode(raw).decode(),
                'entity_type': 'people', 'mapping': {}, 'auto_map': True, **extra}

    def test_people_upload_confirm_without_ids_is_read_only_and_idempotent(self):
        data = [['小林', '木作车间', '封边'], ['小陈', '财务部', '会计']]
        before = deepcopy(self.all('people'))
        response = self.call('prepare', self.people_payload(data))
        preview = response['preview']
        self.assertEqual(preview['mapping'], {'name': '姓名', 'role': '岗位', 'workshop': '车间'})
        self.assertEqual(preview['summary'], {'create': 2, 'update': 0, 'skip': 0, 'error': 0})
        self.assertEqual(self.all('people'), before)
        self.assertEqual(self.all('events'), [])
        self.assertEqual(preview['rows'][0]['data']['skills'], ['木工'])
        self.assertEqual(preview['rows'][1]['data']['skills'], [])
        self.assertTrue(preview['rows'][0]['data']['external_key'].startswith('EMP-'))
        self.commit(preview)
        imported = [p for p in self.all('people') if not p.get('demo')]
        self.assertEqual(len(imported), 2)
        self.assertTrue(all(p.get('capacity_minutes') is None for p in imported))
        self.assertTrue(all(p.get('employee_no') for p in imported))
        repeated = self.preview(self.people_payload(data[::-1], filename='重排且改名.xlsx'))
        self.assertEqual(repeated['summary']['skip'], 2, repeated)
        self.commit(repeated)
        self.assertEqual([p for p in self.all('people') if not p.get('demo')], imported)

    def test_people_existing_employee_number_and_target_id_export_roundtrip(self):
        preview = self.preview(self.people_payload([['EMP0001', '小林', '木工']], ['员工号', '姓名', '岗位']))
        self.commit(preview)
        person = [p for p in self.all('people') if not p.get('demo')][0]
        self.assertEqual(person['employee_no'], 'EMP0001')
        exported = self.call('export_data', 'people', format='xlsx')
        back = self.preview({'filename': exported['filename'], 'content_base64': base64.b64encode(exported['bytes']).decode(),
                             'entity_type': 'people', 'auto_map': True})
        self.assertEqual(back['summary']['skip'], 1, back)
        self.assertEqual(back['rows'][0]['target_id'], person['id'])
        self.commit(back)
        self.assertEqual([p for p in self.all('people') if not p.get('demo')], [person])

    def test_people_duplicate_identity_blocks_all_ambiguous_rows(self):
        preview = self.preview(self.people_payload([['小林', '木作车间', '封边'], ['小林', '木作车间', '钉装']]))
        self.assertEqual(preview['summary']['error'], 2)
        with self.assertRaises(exchange.ExchangeError):
            self.commit(preview)
        self.assertFalse([p for p in self.all('people') if not p.get('demo')])
        distinct = self.preview(self.people_payload([['小林', '木作车间', '封边'], ['小林', '五金车间', '焊工']]))
        self.assertEqual(distinct['summary']['create'], 2)
        self.commit(distinct)
        ambiguous = self.preview(self.people_payload([['小林']], ['姓名']))
        self.assertEqual(ambiguous['summary']['error'], 1)
        self.assertIn('同名', ambiguous['rows'][0]['errors'][0])

    def test_people_factory_scoping_and_stale_factory_snapshot(self):
        with self.store.connect() as con:
            factories = [operations.save_factory(self.store, con, {'name': name, 'factory_type': 'cabinet'})['factory']
                         for name in ['甲厂', '乙厂']]
        payload = self.people_payload([['E01', '小林', '木工']], ['员工号', '姓名', '岗位'], defaults={'factory_id': factories[0]['id']})
        first = self.preview(payload)
        self.commit(first)
        payload['defaults']['factory_id'] = factories[1]['id']
        second = self.preview(payload)
        self.assertEqual(second['summary']['create'], 1, second)
        self.commit(second)
        self.assertEqual(len([p for p in self.all('people') if not p.get('demo')]), 2)
        third = self.preview(self.people_payload([['小王', '木作', '封边']], defaults={'factory_id': factories[0]['id']}))
        factories[0]['name'] = '已修改的工厂'
        self.put('factories', factories[0])
        with self.assertRaises(exchange.ExchangeError) as error:
            self.commit(third)
        self.assertEqual(error.exception.details['code'], 'preview_stale')
        person = [p for p in self.all('people') if p.get('factory_id') == factories[0]['id']][0]
        invalid = self.preview(self.people_payload([[person['id'], '小林']], ['KANPACE人员ID', '姓名'], defaults={'factory_id': factories[1]['id']}))
        self.assertEqual(invalid['summary']['error'], 1)
        self.assertIn('工厂', invalid['rows'][0]['errors'][0])

    def test_people_workshop_change_without_id_requires_identity_check(self):
        self.commit(self.preview(self.people_payload([['小林', '木作车间', '封边']])))
        preview = self.preview(self.people_payload([['小林', '五金车间', '焊工']]))
        self.assertEqual(preview['summary']['error'], 1)
        self.assertIn('调岗', preview['rows'][0]['errors'][0])
        before = [p for p in self.all('people') if not p.get('demo')]
        with self.assertRaises(exchange.ExchangeError):
            self.commit(preview)
        self.assertEqual([p for p in self.all('people') if not p.get('demo')], before)
        explicit = self.preview(self.people_payload([[before[0]['employee_no'], '小林', '五金车间', '焊工']], ['员工号', '姓名', '车间', '岗位']))
        self.assertEqual(explicit['summary']['update'], 1, explicit)
        self.commit(explicit)
        after = [p for p in self.all('people') if not p.get('demo')]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]['id'], before[0]['id'])
        self.assertEqual(after[0]['workshop'], '五金车间')

    def test_people_role_update_keeps_identity_and_requires_task_reassignment(self):
        self.commit(self.preview(self.people_payload([['小林', '木作车间', '封边']])))
        person = [p for p in self.all('people') if not p.get('demo')][0]
        with self.store.connect() as con:
            project = self.store.new_project(con, {'name': '人员变动隔离测试', 'factory_type': 'cabinet'})
            project.update(status='released', released_revision=project['revision'])
            self.store.put(con, 'projects', project)
            common = {'project_id': project['id'], 'revision': project['revision'], 'trade': '木工',
                      'assignee': person['id'], 'execution_version': 2, 'quantity': 2,
                      'completed_quantity': 0, 'remaining_quantity': 2, 'dependencies': []}
            self.store.put(con, 'tasks', dict(common, id='task_person_pending', title='待开料', status='ready'))
            self.store.put(con, 'tasks', dict(common, id='task_person_done', title='已完成封边', status='done',
                                              completed_quantity=2, remaining_quantity=0))
            self.store.put(con, 'device_deliveries', {'id': 'delivery_person_old', 'status': 'received',
                'project_id': project['id'], 'task_id': 'task_person_pending', 'revision': project['revision'],
                'device_id': 'badge_person_old', 'assignee_id': person['id'], 'test_mode': False})
        changed = self.preview(self.people_payload([['小林', '木作车间', '钉装']], filename='新岗位.xlsx'))
        self.assertEqual(changed['summary']['update'], 1, changed)
        self.assertEqual(changed['rows'][0]['target_id'], person['id'])
        self.assertEqual(changed['rows'][0]['reassignment_required'],
                         [{'task_id': 'task_person_pending', 'title': '待开料'}])
        self.commit(changed)
        imported = [p for p in self.all('people') if not p.get('demo')]
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]['id'], person['id'])
        pending = next(t for t in self.all('tasks') if t['id'] == 'task_person_pending')
        done = next(t for t in self.all('tasks') if t['id'] == 'task_person_done')
        self.assertIsNone(pending['assignee'])
        self.assertEqual(pending['execution_version'], 3)
        self.assertEqual(pending['status'], 'ready')
        self.assertEqual(done['assignee'], person['id'])
        self.assertEqual(done['execution_version'], 2)
        old_badge = self.store.handle_device_execution({'event_id': 'badge_person_old_event',
            'device_id': 'badge_person_old', 'task_id': pending['id'], 'delivery_id': 'delivery_person_old',
            'revision': project['revision'], 'execution_version': 2, 'action': 'start'})
        self.assertFalse(old_badge['accepted'])
        self.assertIn('负责人已变更', old_badge['message'])
        repeat = self.preview(self.people_payload([['小林', '木作车间', '钉装']], filename='新岗位再次.xlsx'))
        self.assertEqual(repeat['summary']['skip'], 1, repeat)
        with self.store.connect() as con:
            reassigned = self.store.assign(con, pending['id'], person['id'])
        self.assertEqual(reassigned['assignee'], person['id'])
        self.assertNotIn('reassignment_reason', reassigned)
        old_badge_after_reassignment = self.store.handle_device_execution({
            'event_id': 'badge_person_old_event_again', 'device_id': 'badge_person_old',
            'task_id': pending['id'], 'delivery_id': 'delivery_person_old',
            'revision': project['revision'], 'execution_version': 2, 'action': 'start'})
        self.assertFalse(old_badge_after_reassignment['accepted'])

    def test_people_leave_is_explicit_and_stale_preview_or_running_task_blocks_it(self):
        self.commit(self.preview(self.people_payload([['小林', '木作车间', '封边']])))
        person = [p for p in self.all('people') if not p.get('demo')][0]
        with self.store.connect() as con:
            project = self.store.new_project(con, {'name': '离职隔离测试', 'factory_type': 'cabinet'})
            task = {'id': 'task_person_leave', 'project_id': project['id'], 'revision': project['revision'],
                    'trade': '木工', 'title': '待交接工序', 'status': 'ready', 'assignee': person['id'],
                    'execution_version': 0, 'quantity': 1, 'completed_quantity': 0,
                    'remaining_quantity': 1, 'dependencies': []}
            self.store.put(con, 'tasks', task)
            self.store.put(con, 'tasks', dict(task, id='task_person_leave_done', title='历史完工工序',
                                              status='done', completed_quantity=1, remaining_quantity=0))
        payload = self.people_payload([['小林', '木作车间', '封边', '离职']],
                                      ['姓名', '车间', '岗位', '在职状态'])
        preview = self.preview(payload)
        self.assertEqual(preview['rows'][0]['reassignment_required'][0]['task_id'], task['id'])
        task['status'] = 'in_progress'
        self.put('tasks', task)
        with self.assertRaises(exchange.ExchangeError) as stale:
            self.commit(preview)
        self.assertEqual(stale.exception.details['code'], 'preview_stale')
        running = self.preview(payload)
        self.assertEqual(running['summary']['error'], 1)
        self.assertIn('先暂停', running['rows'][0]['errors'][0])
        task['status'] = 'blocked'
        task['completed_quantity'] = 1
        task['remaining_quantity'] = 0
        task['handover_note'] = '半成品交接给新木工'
        self.put('tasks', task)
        self.commit(self.preview(payload))
        left = next(p for p in self.all('people') if p['id'] == person['id'])
        self.assertEqual(left['employment_status'], 'left')
        handed = next(t for t in self.all('tasks') if t['id'] == task['id'])
        self.assertIsNone(handed['assignee'])
        self.assertEqual(handed['handover_note'], '半成品交接给新木工')
        self.assertEqual(handed['completed_quantity'], 1)
        self.assertEqual(next(t for t in self.all('tasks') if t['id'] == 'task_person_leave_done')['assignee'], person['id'])
        with self.store.connect() as con, self.assertRaises(APIError):
            self.store.assign(con, task['id'], person['id'])
        # A later partial workbook without a status column must not silently rehire.
        partial = self.preview(self.people_payload([['小林', '木作车间', '封边']]))
        self.assertEqual(partial['summary']['skip'], 1, partial)
        self.assertEqual(self.all('people')[-1]['employment_status'], 'left')

    def test_people_multiple_factories_need_choice_and_unknown_name_falls_back(self):
        with self.store.connect() as con:
            for name in ['甲厂', '乙厂']:
                operations.save_factory(self.store, con, {'name': name, 'factory_type': 'cabinet'})
        with self.assertRaises(exchange.ExchangeError) as error:
            self.preview(self.people_payload([['小林']], ['姓名']))
        self.assertEqual(error.exception.details['code'], 'factory_required')
        inspected = self.call('prepare', self.people_payload([['小林']], ['未命名列']))
        self.assertIsNone(inspected['preview'])
        self.assertIn('姓名', inspected['warning'])

    def test_people_manual_inspect_contract_and_no_skills_still_works(self):
        payload = self.people_payload([['小林', '财务部', '出纳']])
        payload.pop('auto_map')
        inspected = self.call('prepare', payload)
        self.assertIsNone(inspected['preview'])
        payload['mapping'] = {'name': '姓名', 'role': '岗位', 'workshop': '车间'}
        preview = self.preview(payload)
        self.assertEqual(preview['summary']['error'], 0)
        self.assertEqual(preview['rows'][0]['data']['skills'], [])
        self.commit(preview)
        person = [p for p in self.all('people') if not p.get('demo')][0]
        self.assertEqual(person['role'], '出纳')
        self.assertEqual(person['workshop'], '财务部')
        self.assertIsNone(person['capacity_minutes'])

    def test_people_titles_and_vertical_merged_context(self):
        raw = exchange.xlsx_bytes(['岗位人员表', '', ''], [['姓名', '车间', '岗位'], ['小林', '木作车间', '封边'], ['小周', '', '钉装']])
        output = io.BytesIO()
        with ZipFile(io.BytesIO(raw)) as original, ZipFile(output, 'w') as modified:
            for entry in original.infolist():
                content = original.read(entry.filename)
                if entry.filename == 'xl/worksheets/sheet1.xml':
                    content = content.replace(b'</ns0:worksheet>', b'<ns0:mergeCells><ns0:mergeCell ref="B3:B4"/></ns0:mergeCells></ns0:worksheet>')
                modified.writestr(entry, content)
        preview = self.preview({'filename': '标题及合并.xlsx', 'content_base64': base64.b64encode(output.getvalue()).decode(),
                                'entity_type': 'people', 'auto_map': True})
        self.assertEqual(preview['header_row'], 2)
        self.assertEqual(preview['summary']['create'], 2, preview)
        self.assertEqual(preview['rows'][1]['data']['workshop'], '木作车间')
        self.assertEqual(preview['rows'][1]['data']['skills'], ['木工'])

    def test_people_inference_preserves_office_roles_and_recognizes_production(self):
        rows = [['小林', '五金车间', '焊工'], ['小王', '油漆车间', '刮灰打磨'], ['小陈', '五金车间', '五金物料员'],
                ['小李', '玻璃车间', '玻璃加工'], ['小张', '木作车间', '雕刻学徒']]
        preview = self.preview(self.people_payload(rows))
        self.assertEqual(preview['summary']['error'], 0)
        self.assertEqual([r['data']['skills'] for r in preview['rows']], [['五金'], ['油漆'], [], ['玻璃'], []])

    def test_generic_role_in_trade_workshop_does_not_grant_dispatch_skill(self):
        preview = self.preview(self.people_payload([['小林', '木作车间', '普工'], ['小周', '玻璃车间', '操作工']]))
        self.assertEqual(preview['summary']['error'], 0, preview)
        self.assertEqual([r['data']['skills'] for r in preview['rows']], [[], []])

    def test_material_import_uses_real_material_action_and_unknown_task_rejected(self):
        self.commit(self.preview())
        project = self.all('projects')[0]
        raw = exchange.xlsx_bytes(['行号', '物料', '需求', '已验收', '单位'], [['MR1', '电机', '2', '1', '台']])
        payload = {'filename': '物料.xlsx', 'content_base64': base64.b64encode(raw).decode(), 'entity_type': 'materials',
                   'mapping': {'external_key': '行号', 'name': '物料', 'required_quantity': '需求', 'accepted_quantity': '已验收', 'unit': '单位'},
                   'defaults': {'project_id': project['id']}}
        preview = self.preview(payload)
        self.assertEqual(preview['summary']['error'], 0, preview)
        self.assertFalse(self.all('materials'))
        self.commit(preview)
        material = self.all('materials')[0]
        self.assertEqual((material['required_quantity'], material['accepted_quantity']), (2, 1))
        payload['filename'] = '物料错误.xlsx'
        payload['defaults']['task_id'] = 'missing'
        invalid = self.preview(payload)
        self.assertEqual(invalid['summary']['error'], 1)
        self.assertEqual(len(self.all('materials')), 1)

    def progress_fixture(self):
        with self.store.connect() as con:
            p = self.store.new_project(con, {'name': '报工测试', 'factory_type': 'machinery'})
            person = operations.save_person(self.store, con, {'name': '装配人员', 'skills': ['装配'], 'capacity_minutes': 480})['person']
            p.update(status='released', released_revision=1)
            self.store.put(con, 'projects', p)
            task = {'id': 'task_exchange_qa', 'project_id': p['id'], 'revision': 1, 'trade': '装配', 'title': '真实测试工作',
                    'status': 'in_progress', 'quantity': 10, 'completed_quantity': 0, 'assignee': person['id'], 'dependencies': [],
                    'execution_version': 0, 'hours': None, 'started_at': operations.stamp()}
            self.store.put(con, 'tasks', task)
        return task

    def progress_payload(self, quantity=2, filename='报工.xlsx', event_id='EVENT1'):
        data = exchange.xlsx_bytes(['事件号', '任务', '累计', '说明'], [[event_id, 'task_exchange_qa', quantity, '已核对工位实绩']])
        return {'filename': filename, 'content_base64': base64.b64encode(data).decode(), 'entity_type': 'progress',
                'mapping': {'external_key': '事件号', 'task_id': '任务', 'completed_quantity': '累计', 'note': '说明'}}

    def test_progress_preview_no_write_apply_cumulative_idempotent_never_marks_done(self):
        self.progress_fixture()
        before = deepcopy(self.all('tasks'))
        preview = self.preview(self.progress_payload(quantity=10))
        self.assertEqual(preview['summary']['error'], 0, preview)
        self.assertEqual(self.all('tasks'), before)
        self.commit(preview)
        task = self.all('tasks')[0]
        self.assertEqual(task['completed_quantity'], 10)
        self.assertEqual(task['status'], 'in_progress')
        copied = self.preview(self.progress_payload(quantity=10, filename='报工副本.xlsx'))
        self.assertEqual(copied['summary']['skip'], 1)
        before_version = task['execution_version']
        self.commit(copied)
        self.assertEqual(self.all('tasks')[0]['execution_version'], before_version)
        bad = self.preview(self.progress_payload(quantity=9, filename='篡改报工.xlsx'))
        self.assertEqual(bad['summary']['error'], 1)

    def test_progress_requires_live_execution_not_ready_or_closed(self):
        task = self.progress_fixture()
        task['status'] = 'ready'; self.put('tasks', task)
        preview = self.preview(self.progress_payload())
        self.assertEqual(preview['summary']['error'], 1)
        self.assertEqual(self.all('tasks')[0]['completed_quantity'], 0)

    def test_material_multiple_task_links_survive_export_and_reimport(self):
        task = self.progress_fixture()
        other = dict(task, id='task_exchange_other', status='ready')
        self.put('tasks', other)
        data = exchange.xlsx_bytes(['需求号', '物料', '需求', '单位', '任务'],
                                   [['MR-2', '铰链', '20', '个', task['id'] + '、' + other['id']]])
        payload = {'filename': '关联物料.xlsx', 'content_base64': base64.b64encode(data).decode(), 'entity_type': 'materials',
                   'mapping': {'external_key': '需求号', 'name': '物料', 'required_quantity': '需求', 'unit': '单位', 'task_id': '任务'},
                   'defaults': {'project_id': task['project_id']}}
        self.commit(self.preview(payload))
        material = self.all('materials')[0]
        self.assertEqual(material['task_ids'], [task['id'], other['id']])
        exported = self.call('export_data', 'materials', format='xlsx')
        mapping = {key: label for key, label, _ in exchange.FIELDS['materials']}
        back = {'filename': exported['filename'], 'content_base64': base64.b64encode(exported['bytes']).decode(),
                'entity_type': 'materials', 'mapping': mapping}
        preview = self.preview(back)
        self.assertEqual(preview['summary']['error'], 0, preview)
        self.assertEqual(preview['summary']['skip'], 1, preview)
        self.commit(preview)
        self.assertEqual(self.all('materials')[0], material)

    def test_material_snapshot_rejects_revision_change_before_apply(self):
        task = self.progress_fixture()
        data = exchange.xlsx_bytes(['需求号', '物料', '需求', '单位'], [['MR-3', '板材', '3', '张']])
        payload = {'filename': '版本物料.xlsx', 'content_base64': base64.b64encode(data).decode(), 'entity_type': 'materials',
                   'mapping': {'external_key': '需求号', 'name': '物料', 'required_quantity': '需求', 'unit': '单位'},
                   'defaults': {'project_id': task['project_id'], 'task_id': task['id']}}
        preview = self.preview(payload)
        task['revision'] = 2
        self.put('tasks', task)
        with self.assertRaises(exchange.ExchangeError) as error:
            self.commit(preview)
        self.assertEqual(error.exception.details['code'], 'preview_stale')
        self.assertEqual(self.all('materials'), [])

    def test_receipt_export_roundtrip_and_history(self):
        preview = self.preview()
        self.commit(preview)
        receipt = self.call('export_data', 'projects', format='xlsx', preview_id=preview['id'])
        parsed = exchange.inspect_content(receipt['filename'], receipt['bytes'])
        self.assertEqual(parsed['rows'][0]['cells']['原文件']['value'], '订单.csv')
        self.assertEqual(parsed['rows'][0]['cells']['结果']['value'], '已应用')
        self.assertEqual(self.call('build')['previews'][0]['status'], 'applied')


if __name__ == '__main__':
    unittest.main()
