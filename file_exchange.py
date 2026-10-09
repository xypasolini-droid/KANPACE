"""Auditable Excel/CSV exchange: inspect, map, preview, commit, and export.

Writes use the application's existing domain actions. A spreadsheet status cell
can never directly mark a task complete. No external ERP credentials required.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import base64
import binascii
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile, ZIP_DEFLATED

import operations as ops
import engine
import schedule_reference as sheets

MAX_UPLOAD = 20 * 1024 * 1024
MAX_ROWS = 10000
NAMESPACE = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
FIELDS = {
    'projects': [('external_key', '原系统订单号', True), ('target_id', 'KANPACE项目ID', False), ('name', '项目名称', True),
                 ('client', '客户', False), ('due_date', '交付日期', False), ('quantity', '项目数量', False),
                 ('factory_type', '工厂类型', False), ('factory_id', '工厂ID', False)],
    'people': [('external_key', '员工号', False), ('target_id', 'KANPACE人员ID', False), ('name', '姓名', True),
               ('role', '岗位', False), ('workshop', '车间', False), ('employment_status', '在职状态', False),
               ('skills', '技能（顿号分隔）', False), ('capacity_minutes', '每日可用分钟', False),
               ('factory_id', '工厂ID', False), ('team_id', '班组ID', False)],
    'materials': [('external_key', '原系统需求行号', True), ('target_id', 'KANPACE需求ID', False),
                  ('project_id', '项目ID', True), ('task_id', '关联任务ID（顿号分隔）', False), ('name', '物料名称', True),
                  ('required_quantity', '需求数量', True), ('accepted_quantity', '已验收并预留数量', False), ('unit', '单位', True),
                  ('supplier', '供应商', False), ('expected_date', '预计到料日期', False), ('note', '备注', False)],
    'progress': [('external_key', '原系统报工事件号', True), ('task_id', '任务ID', True),
                 ('completed_quantity', '累计完成数量', True), ('note', '报工说明', True)],
}
KINDS = {'projects': 'projects', 'people': 'people', 'materials': 'materials', 'progress': 'tasks'}


class ExchangeError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, status=400, code='exchange_invalid', **details):
    raise ExchangeError(status, message, {'code': code, **details})


def safe_data_error(error):
    return str(getattr(error, 'message', str(error)))[:1500]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_bytes(data):
    filename = ops.string(data.get('filename'), '文件名', True, 250)
    if Path(filename).name != filename or '\\' in filename or filename.startswith('.'):
        fail('文件名无效')
    if Path(filename).suffix.lower() not in ('.csv', '.xlsx'):
        fail('请选择 CSV 或 XLSX 文件')
    encoded = data.get('content_base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_UPLOAD * 4 // 3 + 8):
        fail('文件内容无效或超过 20 MB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        fail('文件内容编码无效')
    if not content or len(content) > MAX_UPLOAD:
        fail('文件为空或超过 20 MB')
    return filename, content


def numeric(value, label, integer=False, optional=False):
    if value in ('', None) and optional:
        return None
    if isinstance(value, bool):
        fail(label + '须为数值')
    try:
        result = float(str(value).strip())
    except (ValueError, TypeError):
        fail(label + '须为数值')
    if not math.isfinite(result) or result < 0 or result > 1000000000 or (integer and result != int(result)):
        fail(label + '数值无效')
    return int(result) if integer else result


def day(value):
    if not value:
        return ''
    text = str(value).strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        fail('日期须包含年份，格式为 YYYY-MM-DD')
    try:
        date.fromisoformat(text)
    except ValueError:
        fail('日期无效')
    return text


def column_index(reference):
    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', reference or '')
    if not match:
        fail('Excel 单元格坐标无效')
    number = 0
    for char in match[1]:
        number = number * 26 + ord(char) - 64
    if number > 500:
        fail('Excel 超过 500 列，请裁剪为需互联的业务表')
    return int(match[2]), number - 1


def parse_xlsx(content):
    try:
        archive = ZipFile(io.BytesIO(content))
    except BadZipFile:
        fail('XLSX 文件损坏')
    results = []
    with archive:
        infos = archive.infolist()
        if len(infos) > 5000 or sum(i.file_size for i in infos) > 200 * 1024 * 1024 or any(i.file_size > 40 * 1024 * 1024 for i in infos):
            fail('Excel 展开后过大，请拆成小表')
        if len({i.filename for i in infos}) != len(infos):
            fail('Excel 存在重复压缩条目')
        workbook = sheets.xml(archive, 'xl/workbook.xml')
        rels = sheets.xml(archive, 'xl/_rels/workbook.xml.rels')
        targets = {r.get('Id'): r.get('Target') for r in rels if r.get('TargetMode') != 'External'}
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(t.text or '' for t in item.findall('.//m:t', sheets.NS))
                       for item in sheets.xml(archive, 'xl/sharedStrings.xml').findall('m:si', sheets.NS)]
        formats, styles = {}, [0]
        if 'xl/styles.xml' in archive.namelist():
            style = sheets.xml(archive, 'xl/styles.xml')
            formats = {int(f.get('numFmtId')): f.get('formatCode', '') for f in style.findall('m:numFmts/m:numFmt', sheets.NS)}
            styles = [int(f.get('numFmtId', '0')) for f in style.findall('m:cellXfs/m:xf', sheets.NS)] or [0]
        pr = workbook.find('m:workbookPr', sheets.NS)
        epoch1904 = pr is not None and pr.get('date1904') in ('1', 'true')
        for sheet in workbook.findall('m:sheets/m:sheet', sheets.NS):
            target = targets.get(sheet.get(sheets.REL))
            if not target:
                continue
            target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not target.startswith('xl/worksheets/') or '..' in target.split('/'):
                fail('Excel 工作表路径无效')
            rows = []
            tree = sheets.xml(archive, target)
            for row in tree.findall('m:sheetData/m:row', sheets.NS):
                cells = {}
                row_number = int(row.get('r', '0'))
                for cell in row.findall('m:c', sheets.NS):
                    r, col = column_index(cell.get('r'))
                    if r != row_number:
                        fail('Excel 行号与单元格坐标不一致')
                    value = sheets.base_cell(cell, strings, styles, formats, epoch1904)
                    text = value['raw']
                    if value['date_style'] and text and value['excel_type'] not in ('s', 'inlineStr'):
                        try:
                            num = float(text)
                            if not math.isfinite(num) or num < 0 or num > 2958465:
                                raise ValueError()
                            text = ((datetime(1904, 1, 1) if epoch1904 else datetime(1899, 12, 30)) + timedelta(days=num)).date().isoformat()
                        except (ValueError, OverflowError):
                            fail('Excel 日期数值无效')
                    cells[col] = {'value': text, 'formula': value['formula'], 'coordinate': cell.get('r')}
                if any(c['value'] or c['formula'] for c in cells.values()):
                    rows.append({'row_number': row_number, 'cells': cells})
                if len(rows) > MAX_ROWS + 100:
                    fail('一次导入最多 10000 行')
            merges = [m.get('ref', '') for m in tree.findall('m:mergeCells/m:mergeCell', sheets.NS)]
            results.append({'name': sheet.get('name', ''), 'rows': rows, 'merged_ranges': merges})
        if not results:
            fail('Excel 没有可读取的工作表')
    return results


def parse_csv(content):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        fail('CSV 编码无法识别，请保存为 UTF-8')
    if '\x00' in text:
        fail('CSV 含无效字符')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',\t;')
    except csv.Error:
        dialect = csv.excel
    rows = []
    try:
        for index, row in enumerate(csv.reader(io.StringIO(text), dialect), 1):
            if len(row) > 500:
                fail('CSV 超过 500 列')
            if any(len(c) > 50000 for c in row):
                fail('CSV 单元格过长')
            if any(c.strip() for c in row):
                rows.append({'row_number': index, 'cells': {i: {'value': c, 'formula': None, 'coordinate': str(index) + ':' + str(i + 1)} for i, c in enumerate(row)}})
            if len(rows) > MAX_ROWS + 100:
                fail('一次导入最多 10000 行')
    except csv.Error:
        fail('CSV 结构无效')
    return [{'name': 'CSV', 'rows': rows}]



# Only exact, normalized header aliases are inferred. A workshop is not a skills column.
PEOPLE_HEADERS = {
    'name': ('姓名', '员工姓名', '人员姓名', '员工', '人员', '名字', 'name', 'employeename'),
    'external_key': ('员工号', '原系统员工号', '工号', '员工编号', '人员编号', 'employeeid', 'employeeno'),
    'target_id': ('KANPACE人员ID', 'kanpaceid', 'targetid'),
    'role': ('岗位', '职位', '职务', '工种', 'role', 'position', 'jobtitle'),
    'workshop': ('车间', '部门', '所属车间', '所属部门', '工作车间', 'workshop', 'department'),
    'employment_status': ('在职状态', '人员状态', '员工状态', 'employmentstatus'),
    'skills': ('技能', '工种技能', '技能（顿号分隔）', 'skills'),
    'capacity_minutes': ('每日可用分钟', '日可用分钟', 'capacityminutes'),
    'factory_id': ('工厂ID', 'factoryid'),
    'team_id': ('班组ID', 'teamid'),
}


def header_key(value):
    return re.sub(r'[\s_（）():：*]+', '', str(value)).casefold()


def people_mapping(headers):
    result = {}
    for key, aliases in PEOPLE_HEADERS.items():
        candidates = [h for h in headers if header_key(h) in {header_key(a) for a in aliases}]
        if len(candidates) == 1:
            result[key] = candidates[0]
    return result


def people_header(book, sheet_name=None):
    candidates = []
    for sheet in book:
        if sheet_name and sheet['name'] != sheet_name:
            continue
        for row in sheet['rows'][:30]:
            found = people_mapping([c['value'] for c in row['cells'].values() if not c['formula']])
            if 'name' in found:
                candidates.append((len(found), -row['row_number'], sheet, row))
    return max(candidates, key=lambda item: item[:2])[2:] if candidates else (None, None)


def infer_people_skills(store, con, values):
    """Infer only familiar production trades; office titles remain unassigned."""
    templates = ops.builtin_templates() + store.all(con, 'workflow_templates')
    catalog = {n['trade'] for t in templates for n in t.get('nodes', []) if n.get('trade')}
    catalog.update(step[1] for route in engine.ROUTES.values() for step in route)
    aliases = {'木作': '木工', '木工': '木工', '五金': '五金', '金工': '五金', '油漆': '油漆',
               '喷漆': '油漆', '玻璃': '玻璃', '电工': '电工', '灯光': '电工', '包装': '包装',
               '质检': '质检', '品检': '质检', '装配': '装配', '安装': '安装', '焊接': '焊接'}
    role, workshop = values.get('role', ''), values.get('workshop', '')
    # Department membership alone does not qualify managers, office or support staff.
    if re.search('销售|业务|财务|会计|行政|人事|采购|仓管|文员|司机|保安|保洁|总监|经理|总助|设计|物料|学徒', role):
        return []
    tokens = [t.strip() for t in re.split('[、,，;；|/\n]', role) if t.strip()]
    result = [t for t in tokens if t in catalog]
    for word, trade in aliases.items():
        # Workshop membership describes location, not a certified trade.
        # Generic titles such as 普工 must never unlock trade-based dispatch.
        if trade in catalog and word in role:
            result.append(trade)
    production_roles = {
        '木工': ('木作', r'下料|开料|钉装|封边|贴皮|雕刻|铣槽|钻孔'),
        '五金': ('五金', r'焊工|焊接|下料|折弯|折/剪|剪板|抛槽|抛光|打磨|擦锈|机加|上挂|喷粉'),
        '油漆': ('油漆', r'刮灰|打磨|底漆|面漆|喷漆'),
        '包装': ('装配', r'钉箱|打包'),
        '玻璃': ('玻璃', r'切割|磨边|开孔|加工'),
    }
    for trade, (department, pattern) in production_roles.items():
        if trade in catalog and department in workshop and re.search(pattern, role):
            result.append(trade)
    return list(dict.fromkeys(result))


def person_identity(values):
    return [values.get('factory_id') or '', values.get('workshop', '').strip(), values['name'].strip()]


def complete_person_data(store, con, values):
    factory_id = values.get('factory_id')
    if factory_id:
        ops.ensure_factory(store, con, factory_id)
    if not values.get('external_key'):
        values['external_key'] = 'EMP-' + digest(person_identity(values))[:12].upper()
        values['_generated_employee_no'] = True
    if not values.get('skills'):
        values['skills'] = infer_people_skills(store, con, values)
    if not values.get('role'):
        values['role'] = values['skills'][0] if values['skills'] else '待分工'
    return values


def person_link_id(source_system, values):
    return link_id(source_system + '|factory:' + (values.get('factory_id') or ''), 'people', values['external_key'])


def inspect_content(filename, content, sheet_name=None, header_row=None, auto_people=False):
    try:
        book = parse_xlsx(content) if filename.lower().endswith('.xlsx') else parse_csv(content)
    except (sheets.ReferenceError, ValueError, KeyError, ET.ParseError) as error:
        fail('表格无法读取：' + safe_data_error(error))
    inferred_sheet, inferred_header = people_header(book, sheet_name) if auto_people and not header_row else (None, None)
    sheet = inferred_sheet or (next((s for s in book if s['name'] == sheet_name), None) if sheet_name else book[0])
    if not sheet:
        fail('工作表不存在')
    if not sheet['rows']:
        fail('工作表为空')
    header = next((r for r in sheet['rows'] if r['row_number'] == header_row), None) if header_row else (inferred_header or sheet['rows'][0])
    if not header:
        fail('表头行不存在')
    headers = {i: str(c['value']).strip() for i, c in header['cells'].items() if str(c['value']).strip()}
    if len(set(headers.values())) != len(headers):
        fail('表头名称重复，请修改列名或选择正确表头行')
    if any(c['formula'] for c in header['cells'].values()):
        fail('表头不能是公式')
    if auto_people:
        # Fill only explicit vertical merges in context columns; never forward-fill names or blank rows.
        aliases = people_mapping(list(headers.values()))
        context_columns = {i for i, label in headers.items() if label in [aliases.get('workshop'), aliases.get('role')]}
        by_number = {row['row_number']: row for row in sheet['rows']}
        for merged in sheet.get('merged_ranges', []):
            if ':' not in merged:
                continue
            start, end = [column_index(ref) for ref in merged.split(':', 1)]
            if start[1] != end[1] or start[1] not in context_columns or start[0] <= header['row_number']:
                continue
            origin = by_number.get(start[0], {}).get('cells', {}).get(start[1])
            if not origin:
                continue
            for number, row in by_number.items():
                if start[0] < number <= end[0] and not row['cells'].get(start[1], {}).get('value'):
                    row['cells'][start[1]] = dict(origin)
    rows = []
    for row in sheet['rows']:
        if row['row_number'] <= header['row_number']:
            continue
        mapped = {label: row['cells'].get(i, {'value': '', 'formula': None, 'coordinate': ''}) for i, label in headers.items()}
        if any(c['value'] or c['formula'] for c in mapped.values()):
            rows.append({'row_number': row['row_number'], 'cells': mapped})
    if len(rows) > MAX_ROWS:
        fail('一次导入最多 10000 行')
    return {'sheets': [{'name': s['name'], 'row_count': len(s['rows'])} for s in book], 'sheet': sheet['name'],
            'header_row': header['row_number'], 'headers': list(headers.values()), 'rows': rows}


def normalize_data(kind, data):
    values = {key: str(value).strip() if value is not None else '' for key, value in data.items()}
    values['external_key'] = ops.string(values.get('external_key'), '原系统唯一编号', kind != 'people', 200)
    if kind == 'projects':
        values['name'] = ops.string(values.get('name'), '项目名称', True, 200)
        if 'due_date' in values:
            values['due_date'] = day(values['due_date'])
        if values.get('quantity'):
            values['quantity'] = numeric(values['quantity'], '项目数量')
            if not 0 < values['quantity'] <= 100000:
                fail('项目数量须为大于零的有效数值')
        else:
            values.pop('quantity', None)
        if values.get('factory_type'):
            values['factory_type'] = ops.factory_type(values['factory_type'])
        else:
            values.pop('factory_type', None)
    elif kind == 'people':
        values['name'] = ops.string(values.get('name'), '姓名', True, 100)
        values['skills'] = list(dict.fromkeys(s.strip() for s in re.split('[、,，;；|]', values.get('skills', '')) if s.strip()))
        if 'employment_status' in values:
            if values['employment_status']:
                statuses = {'在职': 'active', '正常': 'active', 'active': 'active',
                            '离职': 'left', '已离职': 'left', 'left': 'left'}
                status = statuses.get(values['employment_status'].casefold())
                if not status:
                    fail('在职状态只接受在职或离职')
                values['employment_status'] = status
            else:
                values.pop('employment_status')
        if 'capacity_minutes' in values:
            values['capacity_minutes'] = numeric(values['capacity_minutes'], '每日可用分钟', optional=True)
    elif kind == 'materials':
        values['project_id'] = ops.string(values.get('project_id'), '项目ID', True, 128)
        values['name'] = ops.string(values.get('name'), '物料名称', True, 200)
        values['unit'] = ops.string(values.get('unit'), '物料单位', True, 30)
        values['required_quantity'] = numeric(values.get('required_quantity'), '需求数量')
        if 'accepted_quantity' in values:
            values['accepted_quantity'] = numeric(values['accepted_quantity'], '已验收并预留数量')
        if 'expected_date' in values:
            values['expected_date'] = day(values['expected_date']) or None
    else:
        values['task_id'] = ops.string(values.get('task_id'), '任务ID', True, 128)
        values['completed_quantity'] = numeric(values.get('completed_quantity'), '累计完成数量', integer=True)
        values['note'] = ops.string(values.get('note'), '报工说明', True, 2000)
    for key in ('factory_id', 'team_id'):
        if key in values and not values[key]:
            values[key] = None
    return values


def material_task_ids(value):
    return list(dict.fromkeys(s.strip() for s in re.split('[、,，;；|]', value or '') if s.strip()))


def link_id(source_system, kind, external_key):
    return 'exlink_' + digest([source_system, kind, external_key])[:40]


def lookup(store, con, kind, identifier):
    return next((r for r in store.all(con, kind) if r['id'] == identifier), None)


def target_for(store, con, kind, data, source_system):
    link = lookup(store, con, 'exchange_links', person_link_id(source_system, data) if kind == 'people' else link_id(source_system, kind, data['external_key']))
    if kind == 'people' and not link:
        legacy = lookup(store, con, 'exchange_links', link_id(source_system, kind, data['external_key']))
        legacy_target = lookup(store, con, 'people', (legacy or {}).get('target_id'))
        if legacy_target and legacy_target.get('factory_id') == data.get('factory_id'):
            link = legacy
    explicit = data.get('task_id') if kind == 'progress' else data.get('target_id')
    if link and explicit and explicit != link['target_id']:
        fail('原系统编号已关联其他记录，不能重绑定', 409, 'external_key_conflict')
    identifier = explicit or (link or {}).get('target_id')
    target = lookup(store, con, KINDS[kind], identifier) if identifier else None
    if identifier and not target:
        fail('指定或已关联的目标记录不存在：' + identifier, 409)
    if kind == 'people' and not target:
        candidates = [p for p in store.all(con, 'people') if not p.get('demo') and p.get('factory_id') == data.get('factory_id')
                      and (p.get('employee_no') == data['external_key'] or
                           data.get('_generated_employee_no') and p.get('name', '').strip() == data['name'].strip()
                           and (not data.get('workshop') or p.get('workshop', '').strip() == data['workshop'].strip()))]
        if len(candidates) > 1:
            fail('同车间有同名人员，请补充员工号区分', 409, 'ambiguous_person')
        if not candidates and data.get('_generated_employee_no') and any(
                not p.get('demo') and p.get('factory_id') == data.get('factory_id') and p.get('name', '').strip() == data['name'].strip()
                for p in store.all(con, 'people')):
            fail('已有同名人员，车间不同；请补充员工号确认是调岗还是新人', 409, 'ambiguous_person')
        target = candidates[0] if candidates else None
    if kind == 'people' and target and target.get('factory_id') != data.get('factory_id'):
        fail('人员不属于本次导入的工厂，请重新选择', 409, 'factory_mismatch')
    if target and target.get('demo'):
        fail('文件互联不能覆盖演示数据', 409)
    return target, link


def related_context(store, con, kind, data, target):
    """Preview is bound to the project/resource scope the user actually reviewed."""
    result = {}
    project_id = data.get('project_id') or (target or {}).get('project_id')
    if kind == 'projects' and target:
        project_id = target['id']
    if project_id:
        result['project'] = lookup(store, con, 'projects', project_id)
    if kind == 'materials':
        task_ids = material_task_ids(data['task_id']) if 'task_id' in data else (target or {}).get('task_ids', [])
        result['tasks'] = [lookup(store, con, 'tasks', identifier) for identifier in sorted(task_ids)]
    factory_id = data.get('factory_id') or (target or {}).get('factory_id')
    if factory_id:
        result['factory'] = lookup(store, con, 'factories', factory_id)
    team_id = data.get('team_id') or (target or {}).get('team_id')
    if team_id:
        result['team'] = lookup(store, con, 'teams', team_id)
    if kind == 'people' and target:
        result['assigned_tasks'] = [t for t in ops.active_tasks(store, con)
                                    if t.get('assignee') == target['id']]
        result['badge_bindings'] = [b for b in store.all(con, 'device_bindings')
                                    if b.get('person_id') == target['id'] and not b.get('archived')]
        result['dispatches'] = [job for job in store.all(con, 'project_dispatches')
                                if job.get('status') not in ('completed', 'cancelled')
                                and any(w.get('person_id') == target['id'] for w in job.get('workers', []))]
    return result


def project_write(store, con, data, target):
    fields = {k: v for k, v in data.items() if k in ('name', 'client', 'due_date', 'quantity', 'factory_type', 'factory_id')}
    selected_factory = fields.get('factory_id')
    if selected_factory:
        factory = ops.get(store, con, 'factories', selected_factory)
        typ = fields.get('factory_type', (target or {}).get('factory_type', factory['factory_type']))
        if typ != factory['factory_type']:
            fail('工厂与项目类型不一致', 409)
        fields['factory_type'] = typ
    if not target:
        if not fields.get('factory_type'):
            fail('新项目须映射工厂类型，或通过导入默认值明确填写')
        project = store.new_project(con, fields)
    else:
        store.require_project_open(target)
        project = deepcopy(target)
        if fields.get('factory_type', project.get('factory_type', 'cabinet')) != project.get('factory_type', 'cabinet'):
            fail('导入不能修改已有项目的行业类型', 409)
        if selected_factory != project.get('factory_id') and 'factory_id' in fields and project.get('workflow_id'):
            fail('已有工作包的项目不能由文件导入改变工厂归属', 409)
        # Validate the same public metadata rules used at project creation.
        project['name'] = ops.string(fields.get('name', project.get('name')), '项目名称', True, 200)
        if 'client' in fields:
            project['client'] = ops.string(fields['client'], '客户', limit=200)
        if 'due_date' in fields:
            project['due_date'] = day(fields['due_date'])
        if 'quantity' in fields:
            project['quantity'] = fields['quantity']
    if 'factory_id' in fields:
        project['factory_id'] = fields['factory_id'] or None
    project.update(external_order_no=data['external_key'], exchange_version=project.get('exchange_version', 0) + 1, updated_at=ops.stamp())
    store.put(con, 'projects', project)
    if target:
        store.event(con, project['id'], 'project_metadata_imported', '导入订单资料更新', external_order_no=data['external_key'])
    return project


def domain_write(store, con, kind, data, target):
    payload = {k: v for k, v in data.items() if k not in ('external_key', 'target_id') and not k.startswith('_')}
    if kind == 'projects':
        return project_write(store, con, data, target)
    if kind == 'people':
        payload['employee_no'] = data['external_key']
        if not payload.get('role'):
            payload.pop('role', None)
        if target:
            payload['expected_version'] = target.get('version', 0)
        return ops.save_person(store, con, payload, target['id'] if target else None)['person']
    if kind == 'materials':
        try:
            import production
        except ImportError:
            fail('物料模块尚未接通，请稍后重新预览', 409, 'material_adapter_unavailable')
        if 'task_id' in payload:
            payload['task_ids'] = material_task_ids(payload.pop('task_id'))
        if target:
            payload.update(id=target['id'], expected_version=target.get('version', 0))
        result = production.save_material(store, con, payload)
        return result.get('material', result)
    if not target:
        fail('报工必须指定现有任务', 409)
    payload['expected_execution_version'] = target.get('execution_version', 0)
    payload.pop('task_id', None)
    return store.report_progress(con, target['id'], payload)


def changes_for(data, target, kind=None):
    if not target:
        return []
    changes = []
    if kind == 'people' and target.get('employee_no') != data.get('external_key'):
        changes.append({'field': 'employee_no', 'before': target.get('employee_no'), 'after': data.get('external_key')})
    for key, value in data.items():
        if key.startswith('_') or key in ('external_key', 'target_id') or (kind == 'progress' and key == 'task_id'):
            continue
        before, after = target.get(key), value
        if kind == 'materials' and key == 'task_id':
            before, after = target.get('task_ids', []), material_task_ids(value)
        if kind == 'people' and key == 'role' and not after:
            continue
        if before != after:
            changes.append({'field': key, 'before': before, 'after': after})
    return changes


def public_preview(preview):
    return {k: v for k, v in preview.items() if k not in ('source_content_base64',)}


def prepare(store, con, data):
    ops.check_fields(data, {'filename', 'content_base64', 'entity_type', 'mapping', 'sheet', 'header_row', 'source_system', 'defaults', 'auto_map'})
    filename, content = source_bytes(data)
    kind = data.get('entity_type')
    if kind not in FIELDS:
        fail('请选择订单、人员、物料或报工')
    mapping = dict(data.get('mapping') or {}) if isinstance(data.get('mapping') or {}, dict) else data['mapping']
    defaults = dict(data.get('defaults') or {}) if isinstance(data.get('defaults') or {}, dict) else data['defaults']
    auto_people = kind == 'people' and data.get('auto_map') is True
    allowed_fields = {f[0] for f in FIELDS[kind]}
    if not isinstance(mapping, dict) or not isinstance(defaults, dict) or (set(mapping) | set(defaults)) - allowed_fields:
        fail('字段映射含不支持的业务字段；不能映射任务状态')
    if any(not isinstance(v, str) for v in mapping.values()):
        fail('字段映射须为列名')
    if set(mapping) & set(defaults):
        fail('字段不能同时使用原表列与默认值')
    source_system = ops.string(data.get('source_system', 'Excel'), '来源系统', True, 100)
    header_row = data.get('header_row')
    if header_row is not None:
        header_row = ops.integer(header_row, '表头行', 1, 1000000)
    parsed = inspect_content(filename, content, data.get('sheet'), header_row, auto_people=auto_people)
    if auto_people:
        inferred = people_mapping(parsed['headers'])
        inferred.update(mapping)
        mapping = {key: value for key, value in inferred.items() if key not in defaults}
    if kind == 'people' and mapping and 'factory_id' not in mapping and 'factory_id' not in defaults:
        factories = [f for f in store.all(con, 'factories') if not f.get('demo') and not f.get('archived')]
        if len(factories) == 1:
            defaults['factory_id'] = factories[0]['id']
        elif len(factories) > 1:
            fail('请选择要导入人员的工厂', code='factory_required')
    if set(mapping.values()) - set(parsed['headers']):
        fail('映射列在原表中不存在', missing=sorted(set(mapping.values()) - set(parsed['headers'])))
    if not mapping or auto_people and 'name' not in mapping:
        return {'preview': None, 'mapping': mapping, 'defaults': defaults, 'auto_map': auto_people,
                'warning': '没有识别到姓名列，请选择姓名所在列' if auto_people else '', 'filename': filename, 'entity_type': kind, **{k: parsed[k] for k in ('sheets', 'sheet', 'header_row', 'headers')},
                'sample_rows': [{'row_number': r['row_number'], 'values': {k: v['value'] for k, v in r['cells'].items()}}
                                for r in parsed['rows'][:8]], 'field_catalog': field_catalog(kind)}
    missing = [f[0] for f in FIELDS[kind] if f[2] and f[0] not in mapping and f[0] not in defaults]
    if missing:
        fail('请映射必填字段', fields=missing)
    config = {k: v for k, v in data.items() if k not in ('content_base64',)}
    config.update(mapping=mapping, defaults=defaults, sheet=parsed['sheet'], header_row=parsed['header_row'])
    source_hash = hashlib.sha256(content).hexdigest()
    preview_hash = digest([source_hash, config])
    prior = next((p for p in store.all(con, 'exchange_previews') if p['preview_hash'] == preview_hash and p['status'] == 'applied'), None)
    if prior and kind != 'people':
        return {'preview': public_preview(prior), 'duplicate': True, 'field_catalog': field_catalog(kind), 'auto_map': auto_people}
    rows, seen_keys, seen_targets = [], set(), set()
    for raw in parsed['rows']:
        entry = {'row_number': raw['row_number'], 'action': 'error', 'errors': [], 'changes': [], 'target_id': None,
                 'source_cells': {key: raw['cells'][label]['coordinate'] for key, label in mapping.items()}}
        try:
            if any(raw['cells'][label]['formula'] for label in mapping.values()):
                fail('映射单元格含公式，请先在副本中粘贴为已核对的值')
            payload = dict(defaults)
            payload.update({key: raw['cells'][label]['value'] for key, label in mapping.items()})
            normalized = normalize_data(kind, payload)
            if kind == 'people':
                normalized = complete_person_data(store, con, normalized)
            target, link = target_for(store, con, kind, normalized, source_system)
            if kind == 'people' and target:
                if 'skills' not in mapping and 'skills' not in defaults:
                    normalized['skills'] = target.get('skills', normalized['skills'])
                if 'role' not in mapping and 'role' not in defaults:
                    normalized['role'] = target.get('role', normalized['role'])
                if 'workshop' not in mapping and 'workshop' not in defaults:
                    normalized['workshop'] = target.get('workshop', '')
                if normalized.get('_generated_employee_no') and target.get('employee_no'):
                    normalized['external_key'] = target['employee_no']
                    target, link = target_for(store, con, kind, normalized, source_system)
            entry['data'] = normalized
            key = normalized['external_key']
            if key in seen_keys:
                fail('同车间有同名人员，请补充员工号区分' if kind == 'people' and normalized.get('_generated_employee_no') else '同一文件原系统唯一编号重复')
            seen_keys.add(key)
            if target:
                if target['id'] in seen_targets:
                    fail('同一文件多行指向同一记录，请合并为一条明确更新')
                seen_targets.add(target['id'])
            entry['target_id'] = target['id'] if target else None
            entry['expected_version'] = (target.get('execution_version', 0) if kind == 'progress' else target.get('version', target.get('exchange_version', 0))) if target else 0
            entry['target_hash'] = digest(target) if target else None
            entry['link_hash'] = digest(link) if link else None
            entry['context_hash'] = digest(related_context(store, con, kind, normalized, target))
            entry['changes'] = changes_for(normalized, target, kind)
            if kind == 'progress' and link:
                if link.get('data_hash') != digest(normalized):
                    fail('报工事件号已使用，但数据不同；请核对原始报工', 409)
                entry['action'] = 'skip'
            elif target and not entry['changes']:
                entry['action'] = 'skip'
            else:
                # Exercise real domain checks without persisting simulated events/data.
                if kind == 'people':
                    future = ops.validate_person_update(store, con, target or {},
                                                         dict(normalized, employee_no=normalized['external_key']))
                    entry['reassignment_required'] = [{'task_id': task['id'], 'title': task['title']}
                        for task in ops.person_handoff_tasks(store, con, target or {}, future)]
                else:
                    con.execute('SAVEPOINT exchange_preview_row')
                    try:
                        domain_write(store, con, kind, normalized, target)
                    finally:
                        con.execute('ROLLBACK TO exchange_preview_row')
                        con.execute('RELEASE exchange_preview_row')
                entry['action'] = 'update' if target else 'create'
        except Exception as error:
            if not isinstance(error, (ExchangeError, ops.OperationError)) and not hasattr(error, 'status'):
                raise
            entry['errors'] = [safe_data_error(error)]
        rows.append(entry)
    if not rows:
        fail('原表没有可导入的数据行')
    # An ambiguous pair must show both rows as unresolved, never a seemingly valid first row.
    if kind == 'people':
        grouped = {}
        for entry in rows:
            value = entry.get('data', {})
            if value.get('_generated_employee_no'):
                grouped.setdefault(value['external_key'], []).append(entry)
        for group in grouped.values():
            if len(group) > 1:
                for entry in group:
                    entry.update(action='error', errors=['同车间有同名人员，请补充员工号区分'])
    summary = {key: sum(r['action'] == key for r in rows) for key in ('create', 'update', 'skip', 'error')}
    preview = {'id': ops.uid('exchange'), 'version': 1, 'status': 'preview', 'filename': filename, 'source_hash': source_hash,
               'preview_hash': preview_hash, 'source_system': source_system, 'entity_type': kind,
               'mapping': mapping, 'defaults': defaults, 'sheet': parsed['sheet'], 'sheets': parsed['sheets'],
               'header_row': parsed['header_row'], 'headers': parsed['headers'], 'rows': rows, 'summary': summary,
               'auto_map': auto_people, 'auto_notes': ['员工号自动补齐'] if any(r.get('data', {}).get('_generated_employee_no') for r in rows) else [],
               'created_at': ops.stamp(), 'source_content_base64': base64.b64encode(content).decode()}
    store.put(con, 'exchange_previews', preview)
    return {'preview': public_preview(preview), 'duplicate': False, 'field_catalog': field_catalog(kind), 'auto_map': auto_people}


def apply(store, con, identifier, data):
    ops.check_fields(data, {'expected_version'})
    preview = ops.get(store, con, 'exchange_previews', identifier)
    if preview['status'] == 'applied':
        return {'preview': public_preview(preview), 'receipt': preview['receipt'], 'duplicate': True}
    ops.expected(preview, data)
    if preview['summary']['error']:
        fail('预览仍有错误，请修正原表或映射后重新预览', 409, 'preview_has_errors')
    kind, system = preview['entity_type'], preview['source_system']
    # Check every precondition before changing any record.
    resolved_targets = []
    for row in preview['rows']:
        target, link = target_for(store, con, kind, row['data'], system)
        if ((digest(target) if target else None) != row['target_hash']
                or (digest(link) if link else None) != row['link_hash']
                or ('context_hash' in row and digest(related_context(store, con, kind, row['data'], target)) != row['context_hash'])):
            fail('预览后数据已变化，请重新预览', 409, 'preview_stale', row_number=row['row_number'], target_id=row['target_id'])
        resolved_targets.append(target)
    results = []
    for row, target in zip(preview['rows'], resolved_targets):
        if row['action'] != 'skip':
            target = domain_write(store, con, kind, row['data'], target)
        if not target:
            fail('导入目标未生成', 500)
        external = row['data']['external_key']
        record = {'id': person_link_id(system, row['data']) if kind == 'people' else link_id(system, kind, external), 'source_system': system, 'entity_type': kind,
                  'external_key': external, 'target_id': target['id'], 'data_hash': digest(row['data']),
                  'last_preview_id': identifier, 'source_hash': preview['source_hash'], 'filename': preview['filename'],
                  'sheet': preview['sheet'], 'row_number': row['row_number'], 'updated_at': ops.stamp()}
        store.put(con, 'exchange_links', record)
        results.append({'row_number': row['row_number'], 'external_key': external, 'target_id': target['id'],
                        'action': row['action'], 'result': '已跳过' if row['action'] == 'skip' else '已应用'})
    receipt = {'id': ops.uid('receipt'), 'applied_at': ops.stamp(), 'results': results, 'summary': preview['summary']}
    preview.update(status='applied', version=preview['version'] + 1, receipt=receipt)
    store.put(con, 'exchange_previews', preview)
    store.event(con, None, 'exchange_applied', '应用表格互联：' + preview['filename'], preview_id=identifier,
                source_hash=preview['source_hash'], entity_type=kind, summary=preview['summary'])
    return {'preview': public_preview(preview), 'receipt': receipt, 'duplicate': False}


def field_catalog(kind=None):
    return {key: [{'key': f[0], 'label': f[1], 'required': f[2]} for f in fields] for key, fields in FIELDS.items() if not kind or key == kind}


def build(store, con):
    history = []
    for preview in reversed(store.all(con, 'exchange_previews')):
        history.append({key: preview.get(key) for key in ('id', 'version', 'status', 'filename', 'source_system', 'entity_type', 'sheet', 'summary', 'created_at')})
    return {'previews': history, 'field_catalog': field_catalog(), 'formats': ['csv', 'xlsx'], 'mode': 'reviewed_file_exchange'}


def get_preview(store, con, identifier):
    return {'preview': public_preview(ops.get(store, con, 'exchange_previews', identifier))}


def safe_csv(value):
    text = '' if value is None else str(value)
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def xlsx_bytes(headers, rows):
    """Minimal interoperable XLSX: strings stay strings; never emits formulas."""
    ns = '{' + NAMESPACE + '}'
    sheet = ET.Element(ns + 'worksheet')
    sheet_data = ET.SubElement(sheet, ns + 'sheetData')
    for index, values in enumerate([headers] + list(rows), 1):
        row = ET.SubElement(sheet_data, ns + 'row', r=str(index))
        for col, value in enumerate(values, 1):
            letters, number = '', col
            while number:
                number, rem = divmod(number - 1, 26)
                letters = chr(65 + rem) + letters
            cell = ET.SubElement(row, ns + 'c', r=letters + str(index), t='inlineStr')
            inline = ET.SubElement(cell, ns + 'is')
            text = ET.SubElement(inline, ns + 't', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
            text.text = '' if value is None else str(value)
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="' + NAMESPACE + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="KANPACE" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', ET.tostring(sheet, encoding='utf-8', xml_declaration=True))
    return output.getvalue()


def export_data(store, con, entity_type, format='csv', project_id=None, factory_id=None, preview_id=None):
    if format not in ('csv', 'xlsx'):
        fail('导出格式须为 CSV 或 XLSX')
    if preview_id:
        preview = ops.get(store, con, 'exchange_previews', preview_id)
        headers = ['原文件', '工作表', '原行号', '原系统编号', 'KANPACE编号', '操作', '结果']
        results = preview.get('receipt', {}).get('results')
        if not results:
            results = [{'row_number': r['row_number'], 'external_key': r.get('data', {}).get('external_key'), 'target_id': r.get('target_id'),
                        'action': r['action'], 'result': '；'.join(r['errors']) or '待应用'} for r in preview['rows']]
        rows = [[preview['filename'], preview['sheet'], r['row_number'], r.get('external_key'), r.get('target_id'), r['action'], r['result']] for r in results]
        entity_type = 'import_receipt'
    else:
        if entity_type not in FIELDS:
            fail('导出类型无效')
        headers = [f[1] for f in FIELDS[entity_type]] + ['执行状态' if entity_type == 'progress' else '记录版本']
        projects = {p['id']: p for p in store.all(con, 'projects')}
        rows = []
        links = {r['target_id']: r['external_key'] for r in store.all(con, 'exchange_links') if r['entity_type'] == entity_type}
        for item in store.all(con, KINDS[entity_type]):
            project = item if entity_type == 'projects' else projects.get(item.get('project_id'), {})
            if item.get('demo') or project.get('demo') or item.get('archived'):
                continue
            if project_id and (item['id'] if entity_type == 'projects' else item.get('project_id')) != project_id:
                continue
            if factory_id and (item.get('factory_id') or project.get('factory_id')) != factory_id:
                continue
            values = dict(item, external_key=links.get(item['id'], item.get('employee_no') or item.get('external_order_no', '')), target_id=item['id'])
            if entity_type == 'materials':
                values['task_id'] = '、'.join(item.get('task_ids', []))
            if entity_type == 'progress':
                values['task_id'] = item['id']
                values['note'] = item.get('handover_note') or item.get('notes', '')
            if isinstance(values.get('skills'), list):
                values['skills'] = '、'.join(values['skills'])
            rows.append([values.get(f[0]) for f in FIELDS[entity_type]] + [item.get('status') if entity_type == 'progress' else item.get('version', item.get('exchange_version', 0))])
    filename = 'KANPACE-' + entity_type + '.' + format
    if format == 'xlsx':
        return {'bytes': xlsx_bytes(headers, rows), 'filename': filename,
                'content_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([[safe_csv(v) for v in row] for row in rows])
    return {'bytes': output.getvalue().encode('utf-8-sig'), 'filename': filename, 'content_type': 'text/csv; charset=utf-8'}
