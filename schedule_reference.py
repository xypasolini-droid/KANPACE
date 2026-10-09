"""Immutable XLSX evidence plus explicitly edited and published working schedules."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import base64
import binascii
import gzip
import hashlib
import io
import json
import posixpath
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

KIND = 'schedule_reference_sources'
PARSER_VERSION = 3
MAX_UPLOAD = 20 * 1024 * 1024
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
FIELDS = [
    ('ship_date', '出货时间', ['出货时间', '出货日期', '发货日期']),
    ('customer_level', '客户等级', ['客户等级']), ('sequence', '序号', ['序号']),
    ('customer', '客户名称', ['客户名称', '客户']), ('shop', '店铺信息', ['店铺信息', '店铺名称', '店铺地址']),
    ('order_no', '单号', ['单号', '业务单号', '订单号', '订单编号']), ('order_date', '下单日期', ['下单日期', '下单时间']),
    ('marketing_due', '营销要求日期', ['营销要求日期', '营销要求', '客户要求交期']),
    ('planned_split', '预计拆单日期', ['预计拆单日期', '预计拆单']), ('first_due', '首次交期', ['首次交期']),
    ('technician', '技术员', ['技术员']), ('actual_split', '拆单日期', ['实际拆单完成日期', '实际拆单日期', '拆单日期']),
    ('wood', '木作', ['木作', '木工']), ('paint', '油漆', ['油漆', '喷漆']), ('metal', '五金', ['五金', '金工']),
    ('outsource', '外协', ['外协', '委外']), ('assembly', '安装', ['安装', '装配', '组装']),
    ('photography', '拍摄', ['拍摄']), ('packing', '包装', ['包装']), ('quantity', '件数', ['件数', '数量']),
    ('volume', '方数', ['方数', '立方数']), ('packaging', '包装方式', ['包装方式']), ('note', '备注', ['备注'])]
DATE_FIELDS = {'ship_date', 'order_date', 'marketing_due', 'planned_split', 'first_due', 'actual_split',
               'wood', 'paint', 'metal', 'outsource', 'assembly', 'photography', 'packing'}
NODE_FIELDS = {'technical': 'actual_split', 'wood': 'wood', 'paint': 'paint', 'metal': 'metal',
               'outsourcing': 'outsource', 'assembly': 'assembly', 'photography': 'photography', 'packing': 'packing', 'shipping': 'ship_date'}
IDENTITY_FIELDS = ('customer', 'shop', 'order_no', 'technician', 'sequence', 'customer_level')
LABELS = {key: label for key, label, _ in FIELDS}
ALIASES = {re.sub(r'\s+', '', alias): key for key, _, aliases in FIELDS for alias in aliases}


class ReferenceError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, status=422):
    raise ReferenceError(status, message)


def xml(archive, name):
    try:
        data = archive.read(name)
    except KeyError:
        fail('Excel 缺少必要结构：' + name)
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        fail('Excel XML 含不支持的实体定义')
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        fail('Excel XML 内容损坏')


def coordinate(ref):
    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', ref or '')
    if not match:
        return 0, 0
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - 64
    return int(match[2]), column


def column_name(number):
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def full_date(value):
    value = str(value or '').strip()
    match = re.fullmatch(r'(20\d{2}|19\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:[ T]00:00:00(?:\.0+)?Z?)?', value)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def filename_date(filename):
    match = re.search(r'(20\d{2})(\d{2})(\d{2})', filename)
    if not match:
        match = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', filename)
    if not match:
        short = re.search(r'(?<!\d)(2[0-9])(\d{2})(\d{2})(?!\d)', filename)
        groups = (2000 + int(short[1]), int(short[2]), int(short[3])) if short else None
    else:
        groups = tuple(map(int, match.groups()))
    if groups:
        try:
            return date(*groups).isoformat()
        except ValueError:
            pass
    return None


def sheet_date(name, file_date, active=False):
    explicit = full_date(name)
    if explicit:
        return explicit, '工作表名称明确日期', True
    partial = re.fullmatch(r'\s*(\d{1,2})[./月](\d{1,2})日?\s*', name)
    if not partial:
        partial = re.search(r'(?<!\d)(0[1-9]|1[0-2])([0-2][0-9]|3[01])(?!\d)', name)
    if partial and file_date:
        try:
            result = date(int(file_date[:4]), int(partial[1]), int(partial[2])).isoformat()
            return result, '工作表月日与文件名年份', result <= file_date
        except ValueError:
            pass
    if active and file_date:
        return file_date, '文件名日期（工作表未标日期）', True
    return None, '日期未确认', False


def date_style(format_code, num_fmt_id):
    if num_fmt_id in set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59)):
        return True
    cleaned = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', format_code or '').lower()
    return bool(re.search(r'[dy]', cleaned) and re.search(r'[m]', cleaned))


def base_cell(element, strings, styles, formats, epoch1904):
    ref, excel_type = element.get('r'), element.get('t', 'n')
    raw_v = element.findtext('m:v', default='', namespaces=NS)
    formula = element.findtext('m:f', namespaces=NS)
    if excel_type == 's':
        try:
            value = strings[int(raw_v)]
        except (ValueError, IndexError):
            fail('Excel 共享字符串引用无效')
    elif excel_type == 'inlineStr':
        value = ''.join(t.text or '' for t in element.findall('.//m:t', NS))
    else:
        value = raw_v
    if len(value) > 50000:
        fail('Excel 单元格文字过长')
    try:
        style_index = int(element.get('s', '0'))
    except ValueError:
        fail('Excel 单元格样式编号无效')
    fmt_id = styles[style_index] if style_index < len(styles) else 0
    return {'cell': ref, 'raw': value, 'raw_value': raw_v, 'excel_type': excel_type,
            'formula': '=' + formula if formula is not None else None,
            'number_format': formats.get(fmt_id, ''), 'date_style': date_style(formats.get(fmt_id, ''), fmt_id),
            'epoch1904': epoch1904}


def classify(raw, field, *, inferred_year=None, inferred_basis=None, merged_from=None):
    original = raw.get('raw', '') if raw else ''
    value = original.strip()
    result = {'raw': original, 'value': original, 'display': original, 'kind': 'blank' if not value else 'text',
              'date': None, 'month_day': None, 'year_basis': None, 'cell': raw.get('cell') if raw else None,
              'formula': raw.get('formula') if raw else None, 'merged_from': merged_from,
              'excel_type': raw.get('excel_type', 'blank') if raw else 'blank',
              'raw_value': raw.get('raw_value', '') if raw else '', 'date_origin': None}
    if not value and not result['formula']:
        return result
    if result['formula']:
        result.update(kind='formula', display=original or result['formula'])
        return result
    if value.upper() == 'OK' or value in ('已完成', '完成', '已包好'):
        result.update(kind='status', status='ok')
        return result
    if value in ('/', '／', '-', '—', '--'):
        result.update(kind='placeholder')
        return result
    if value in ('不适用', '无需', '无此工序'):
        result.update(kind='not_applicable')
        return result
    if field not in DATE_FIELDS:
        if raw and raw.get('excel_type') == 'n':
            try:
                result.update(kind='number', value=float(value) if '.' in value else int(value))
            except ValueError:
                pass
        return result
    iso = full_date(value)
    if iso:
        result.update(kind='date', date=iso, value=iso, display=iso, year_basis='原单元格明确年份',
                      date_origin='typed_date' if raw.get('excel_type') == 'd' else 'text_full_date')
        return result
    if raw and raw.get('excel_type') == 'n':
        try:
            serial = float(value)
            if 20000 <= serial <= 110000:
                origin = datetime(1904, 1, 1) if raw.get('epoch1904') else datetime(1899, 12, 30)
                iso = (origin + timedelta(days=serial)).date().isoformat()
                result.update(kind='date', date=iso, value=iso, display=iso, year_basis='Excel 序列值所含年份',
                              date_origin='excel_date_serial' if raw.get('date_style') else 'unstyled_serial_in_date_column')
                return result
        except (ValueError, OverflowError):
            pass
        result['kind'] = 'number'
    partial = re.fullmatch(r'(\d{1,2})[./月-](\d{1,2})(?:日|[./])?', value)
    if partial:
        month, day = map(int, partial.groups())
        try:
            date(2000, month, day)
        except ValueError:
            return result
        result.update(kind='date_partial', month_day=f'{month:02d}-{day:02d}')
        if inferred_year:
            try:
                result.update(date=date(inferred_year, month, day).isoformat(), year_basis=inferred_basis,
                              date_origin='text_month_day_with_context')
            except ValueError:
                pass
    return result


def normalize(value):
    return re.sub(r'[\W_]+', '', str(value or '')).lower()


def parse_sheet(tree, name, strings, styles, formats, epoch1904, source_id, meta):
    cells = {}
    for element in tree.findall('.//m:sheetData/m:row/m:c', NS):
        row, col = coordinate(element.get('r'))
        if not row or row > 30000 or col > 64:
            continue
        if element.find('m:v', NS) is None and element.find('m:is', NS) is None and element.find('m:f', NS) is None:
            continue
        cells[(row, col)] = base_cell(element, strings, styles, formats, epoch1904)
    headers = {}
    header_rows = []
    for row in range(1, 21):
        found = {}
        for (r, col), cell in cells.items():
            if r == row:
                key = ALIASES.get(re.sub(r'\s+', '', cell['raw']))
                if key:
                    found[key] = col
        if len(found) >= 4:
            headers.update(found)
            header_rows.append(row)
    if not header_rows or not {'customer', 'shop'} <= set(headers) or len(set(headers) & set(NODE_FIELDS.values())) < 2:
        return None
    header_end = max(header_rows)
    merges = {}
    for element in tree.findall('.//m:mergeCell', NS):
        points = element.get('ref', '').split(':')
        if len(points) != 2:
            continue
        first, last = coordinate(points[0]), coordinate(points[1])
        if first[1] != last[1] or last[0] - first[0] > 1000:
            continue
        if first[1] in headers.values():
            for row in range(first[0] + 1, last[0] + 1):
                merges[(row, first[1])] = first
    rows = []
    max_row = max((r for r, _ in cells), default=header_end)
    for row_number in range(header_end + 1, max_row + 1):
        identity, anchors = {}, []
        for key in IDENTITY_FIELDS:
            col = headers.get(key)
            position = (row_number, col)
            anchor = merges.get(position, position)
            identity[key] = cells.get(anchor, {}).get('raw', '')
            # Customer/category can span many distinct orders; only order/shop
            # merges identify the original two-line logical order.
            if col and key in ('order_no', 'shop') and cells.get(anchor, {}).get('raw'):
                anchors.append(anchor[0])
        if not identity.get('shop') or not (identity.get('customer') or identity.get('order_no')):
            continue
        identity['tech'] = identity.get('technician', '')
        if ALIASES.get(re.sub(r'\s+', '', identity['shop'])):
            continue
        group_row = min(anchors) if anchors else row_number
        physical = {}
        for key, col in headers.items():
            raw = cells.get((row_number, col))
            anchor = merges.get((row_number, col))
            inherited = cells.get(anchor) if anchor else None
            base = classify(raw, key, merged_from=inherited.get('cell') if inherited else None)
            if inherited:
                base['inherited_display'] = classify(inherited, key)['display']
            if base['cell'] is None:
                base['cell'] = column_name(col) + str(row_number)
            physical[key] = base
        # Explicit years in this logical order are more specific than the file date.
        group_years = set()
        for key in DATE_FIELDS & set(headers):
            position = (row_number, headers[key])
            raw = cells.get(position) or cells.get(merges.get(position))
            parsed = classify(raw, key)
            if parsed['date']:
                group_years.add(int(parsed['date'][:4]))
        inferred = next(iter(group_years)) if len(group_years) == 1 else None
        basis = '同一原表行明确日期年份' if inferred else None
        if not group_years and meta.get('snapshot_date') and meta.get('date_trusted'):
            inferred, basis = int(meta['snapshot_date'][:4]), '当前工作表快照年份（待核对）'
        for key, cell in list(physical.items()):
            if cell['kind'] == 'date_partial':
                physical[key] = classify(cells.get((row_number, headers[key])), key,
                                         inferred_year=inferred, inferred_basis=basis, merged_from=cell['merged_from'])
        order_key = normalize(identity.get('order_no'))
        key_basis = 'order_no'
        if not order_key or order_key in ('无', '待定'):
            order_key, key_basis = normalize(identity['customer'] + '|' + identity['shop']), 'customer_shop'
        ship_pos = (row_number, headers.get('ship_date'))
        ship_group = cells.get(merges.get(ship_pos, ship_pos), {}).get('raw', '')
        rows.append({'id': source_id + ':' + hashlib.sha256(name.encode()).hexdigest()[:8] + ':' + str(row_number),
                     'group_id': source_id + ':' + hashlib.sha256(name.encode()).hexdigest()[:8] + ':' + str(group_row),
                     'row_number': row_number, 'sheet': name, 'group_start_row': group_row, 'variant_index': row_number - group_row,
                     'row_role': 'unknown', 'identity': identity, 'order_key': order_key, 'key_basis': key_basis,
                     'cells': physical, 'nodes': {node: physical.get(field, classify(None, field)) for node, field in NODE_FIELDS.items()},
                     'group_shipping_status': ship_group, 'suggestions': []})
    groups = defaultdict(list)
    for row in rows:
        groups[row['group_id']].append(row['row_number'])
    for row in rows:
        row['group_row_numbers'] = groups[row['group_id']]
        row['nodes']['split'] = row['nodes']['technical']
    return {'name': name, 'columns': [{'key': key, 'label': LABELS[key], 'column': column_name(col)} for key, col in sorted(headers.items(), key=lambda entry: entry[1])],
            'header_rows': header_rows, 'rows': rows, 'row_count': len(rows), 'group_count': len(groups), **meta}


def parse_workbook(filename, content, source_id):
    try:
        archive = ZipFile(io.BytesIO(content))
    except BadZipFile:
        fail('请选择有效的 .xlsx Excel 文件')
    with archive:
        infos = archive.infolist()
        if len(infos) > 5000 or sum(info.file_size for info in infos) > 200 * 1024 * 1024 or any(info.file_size > 40 * 1024 * 1024 for info in infos):
            fail('Excel 内容超过本地解析范围，请拆成较小工作簿')
        if len({info.filename for info in infos}) != len(infos):
            fail('Excel 含重复 ZIP 条目')
        workbook = xml(archive, 'xl/workbook.xml')
        relationships = xml(archive, 'xl/_rels/workbook.xml.rels')
        targets = {element.get('Id'): element.get('Target') for element in relationships if element.get('TargetMode') != 'External'}
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [
                ''.join(t.text or '' for t in item.findall('.//m:t', NS))
                for item in xml(archive, 'xl/sharedStrings.xml').findall('m:si', NS)]
        formats, styles = {}, [0]
        if 'xl/styles.xml' in archive.namelist():
            style_root = xml(archive, 'xl/styles.xml')
            formats = {int(element.get('numFmtId')): element.get('formatCode', '') for element in style_root.findall('m:numFmts/m:numFmt', NS)}
            styles = [int(element.get('numFmtId', '0')) for element in style_root.findall('m:cellXfs/m:xf', NS)] or [0]
        book_pr = workbook.find('m:workbookPr', NS)
        epoch1904 = book_pr is not None and book_pr.get('date1904') in ('1', 'true')
        book_view = workbook.find('m:bookViews/m:workbookView', NS)
        try:
            active_index = int(book_view.get('activeTab', '0')) if book_view is not None else 0
        except ValueError:
            active_index = 0
        dated_file = filename_date(filename)
        sheets, ignored, warnings = [], [], []
        for index, sheet in enumerate(workbook.findall('m:sheets/m:sheet', NS)):
            name = sheet.get('name', '')
            target = targets.get(sheet.get(REL))
            if not target:
                continue
            target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not target.startswith('xl/worksheets/') or '..' in PurePosixPath(target).parts:
                fail('Excel 工作表路径无效')
            snapshot, basis, trusted = sheet_date(name, dated_file, active=index == active_index)
            meta = {'snapshot_date': snapshot, 'date_basis': basis, 'date_trusted': trusted,
                    'workbook_index': index, 'active': index == active_index}
            if snapshot and not trusted:
                warnings.append(name + ' 的日期晚于文件名日期，快照日期待核对')
            parsed = parse_sheet(xml(archive, target), name, strings, styles, formats, epoch1904, source_id, meta)
            if parsed:
                sheets.append(parsed)
            else:
                ignored.append(name)
        if not sheets:
            fail('未找到客户、店铺与部门节点表头，请上传生产排程原表')
        trustworthy = [s for s in sheets if s['date_trusted'] and s['snapshot_date']]
        if trustworthy:
            chosen = max(trustworthy, key=lambda s: (s['snapshot_date'], s['active'], s['group_count'], s['workbook_index']))
        else:
            chosen = next((s for s in sheets if s['active']), max(sheets, key=lambda s: s['group_count']))
            warnings.append('未找到可确认的快照日期，默认显示工作簿选中表，日期待核对')
        for sheet in sheets:
            sheet['is_default'] = sheet['name'] == chosen['name']
        return {'parser_version': PARSER_VERSION, 'default_sheet': chosen['name'], 'snapshot_date': chosen['snapshot_date'],
                'filename_date': dated_file, 'sheets': sheets, 'ignored_sheets': ignored, 'warnings': warnings}


STAT_LABELS = {'technical': '下单至拆单', 'wood': '拆单至木作节点', 'paint': '木作至油漆节点',
               'metal': '拆单至五金节点', 'outsourcing': '拆单至外协节点',
               'assembly': '前置部门节点至安装', 'packing': '安装至包装节点', 'shipping': '包装至原表出货日期'}
STAT_PAIRS = {'technical': ('order_date', 'actual_split'), 'wood': ('actual_split', 'wood'),
              'paint': ('wood', 'paint'), 'metal': ('actual_split', 'metal'), 'outsourcing': ('actual_split', 'outsource'),
              'photography': ('assembly', 'photography'), 'packing': ('assembly', 'packing'), 'shipping': ('packing', 'ship_date')}


def stat_candidates(book, filename):
    candidates = []
    for sheet in book['sheets']:
        grouped = defaultdict(list)
        for row in sheet['rows']:
            grouped[row['group_id']].append(row)
        for group in grouped.values():
            for node_id in STAT_LABELS:
                valid, rejected = [], []
                for row in group:
                    base = {'node_id': node_id, 'order_key': row['order_key'], 'key_basis': row['key_basis'],
                            'filename': filename, 'sheet': sheet['name'], 'row': row['row_number'],
                            'snapshot_date': sheet['snapshot_date'], 'date_trusted': sheet['date_trusted'],
                            'order_no': row['identity'].get('order_no', ''), 'shop': row['identity'].get('shop', '')}
                    if any(word in row['group_shipping_status'] for word in ('库存', '呆滞', '待通知')):
                        rejected.append(dict(base, reason='stock_or_hold'))
                        continue
                    cells = row['cells']
                    if node_id == 'assembly':
                        branches = [cells.get(key) for key in ('wood', 'paint', 'metal', 'outsource')]
                        relevant = [cell for cell in branches if cell is None or cell.get('kind') != 'not_applicable']
                        if not relevant or any(not cell or not cell.get('date') or cell.get('date_origin') == 'text_month_day_with_context' for cell in relevant):
                            rejected.append(dict(base, reason='missing_branch_dates'))
                            continue
                        start_cell = max(relevant, key=lambda cell: cell['date'])
                        end_cell = cells.get('assembly')
                    else:
                        start_key, end_key = STAT_PAIRS[node_id]
                        start_cell, end_cell = cells.get(start_key), cells.get(end_key)
                    if not start_cell or not end_cell or not start_cell.get('date') or not end_cell.get('date'):
                        rejected.append(dict(base, reason='missing_dates'))
                        continue
                    if any(cell.get('date_origin') == 'text_month_day_with_context' for cell in (start_cell, end_cell)):
                        rejected.append(dict(base, reason='inferred_year_excluded'))
                        continue
                    days = (date.fromisoformat(end_cell['date']) - date.fromisoformat(start_cell['date'])).days
                    example = dict(base, start=start_cell['date'], end=end_cell['date'], days=days,
                                   start_cell=start_cell['cell'], end_cell=end_cell['cell'])
                    if days < 0:
                        rejected.append(dict(example, reason='negative_interval'))
                    elif days > 120:
                        rejected.append(dict(example, reason='over_120_days'))
                    else:
                        valid.append(example)
                complete = [v for v in valid + rejected if 'start' in v and 'end' in v]
                unique = {(v['start'], v['end']) for v in complete}
                if len(unique) > 1:
                    candidates.append(dict(complete[0], reason='unlabeled_row_variants_conflict'))
                elif len(unique) == 1 and valid:
                    candidates.append(dict(valid[0], reason=None))
                elif rejected:
                    # One reason per logical order/node/snapshot, never one sample per physical row.
                    candidates.append(next((v for v in rejected if v['reason'] not in ('missing_dates', 'missing_branch_dates')), rejected[0]))
    return candidates


def quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * fraction
    lower = int(pos)
    return round(ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (pos - lower), 2)


def build_stats(sources):
    grouped = defaultdict(list)
    all_samples = [dict(sample, source_id=source['id']) for source in sources for sample in source.get('stat_candidates', [])]
    revisions = revision_keys(all_samples)
    for sample in all_samples:
        grouped[(sample['node_id'], revisions.get(sample['order_key'], sample['order_key']))].append(sample)
    results = []
    for node_id, label in STAT_LABELS.items():
        selected, anomalies, discarded = [], Counter(), Counter()
        fallback_count, latest_issues = 0, Counter()
        examples = []
        for (node, order_key), samples in grouped.items():
            if node != node_id:
                continue
            sorted_samples = sorted(samples, key=lambda s: (s.get('snapshot_date') or '', s.get('date_trusted', False), '删减' not in s.get('filename', ''), s.get('filename', '')), reverse=True)
            latest_trusted = next((s['snapshot_date'] for s in sorted_samples if s.get('date_trusted')), None)
            current_hold = next((s for s in sorted_samples if s.get('date_trusted') and s['snapshot_date'] == latest_trusted and s.get('reason') == 'stock_or_hold'), None)
            usable = [] if current_hold else [s for s in sorted_samples if not s.get('reason') and s.get('date_trusted')]
            accepted = usable[0] if usable else None
            # Same-date snapshots are not a sequence. Conflicting full/reduced
            # copies have no reliable latest revision; do not choose by filename.
            if accepted and len({(s['start'], s['end']) for s in sorted_samples
                                 if s.get('date_trusted') and s['snapshot_date'] == accepted['snapshot_date']
                                 and 'start' in s and 'end' in s}) > 1:
                latest = dict(accepted, reason='same_date_snapshot_conflict')
                accepted = None
            else:
                latest = current_hold or sorted_samples[0]
            if accepted:
                newest = next((s for s in sorted_samples if s.get('date_trusted')), sorted_samples[0])
                accepted = dict(accepted, is_historical_fallback=accepted['snapshot_date'] < newest['snapshot_date'],
                                latest_snapshot_date=newest['snapshot_date'], latest_snapshot_issue=newest.get('reason'))
                if accepted['is_historical_fallback']:
                    fallback_count += 1
                    latest_issues[newest.get('reason') or 'latest_snapshot_unusable'] += 1
                selected.append(accepted)
                for reason in {s.get('reason') for s in samples if s.get('reason')}:
                    discarded[reason] += 1
            else:
                anomalies[latest.get('reason') or 'snapshot_date_unconfirmed'] += 1
                if len(examples) < 6:
                    examples.append(latest)
        values = [sample['days'] for sample in selected]
        results.append({'node_id': node_id, 'label': label, 'n': len(values), 'p25': quantile(values, .25),
                        'p50': quantile(values, .5), 'p75': quantile(values, .75), 'unit': 'calendar_days',
                        'basis': '同订单跨快照取最新可用的同一原表行节点日期间隔；每单一个样本，排除推断年份、库存/待通知、同日版本冲突、负数及超过120日的间隔。同日记0日历天，非0工时；上下行口径未标明，不能作为实际加工耗时',
                        'source_examples': selected[:8], 'anomaly_count': sum(anomalies.values()),
                        'anomalies': dict(anomalies), 'anomaly_examples': examples,
                        'n_same_day': sum(v == 0 for v in values), 'historical_fallback_count': fallback_count,
                        'latest_snapshot_issues': dict(latest_issues),
                        'revision_groups_merged': len(set(revisions.values())),
                        'discarded_snapshot_anomalies': dict(discarded)})
    return results


def revision_keys(samples):
    """Only merge explicit G revisions corroborated by a matching shop -改 suffix.

    G1/G2 alone can mean split orders. A revised name, shared full base business
    number, and a newer trusted snapshot are all required.
    """
    records = {}
    for sample in samples:
        if not sample.get('date_trusted'):
            continue
        key = (sample['order_key'], sample.get('shop', ''), sample.get('snapshot_date'))
        records[key] = sample
    result = {}
    for sample in records.values():
        match = re.fullmatch(r'(.+)g\d+', sample['order_key'])
        shop = re.sub(r'\s+', '', sample.get('shop', ''))
        revised = re.search(r'[-－—（(]?改(?:版)?0*\d+[）)]?$', shop)
        if not match or not revised:
            continue
        base_shop = normalize(shop[:revised.start()])
        originals = [s for s in records.values() if s['order_key'] == match[1]
                     and normalize(s.get('shop', '')) == base_shop and s['snapshot_date'] < sample['snapshot_date']]
        if originals:
            result[sample['order_key']] = match[1]
    return result


def public_source(source):
    return {key: value for key, value in source.items() if key not in ('stat_candidates', 'original_file', 'parsed_file')}


def reference_directory(store):
    folder = Path(store.data_dir) / 'schedule-references'
    if folder.is_symlink():
        fail('排程参考存储路径无效', 409)
    return folder


def registered_path(store, source, key):
    folder = reference_directory(store)
    filename = source.get(key, '')
    if not isinstance(filename, str) or not re.fullmatch(r'[0-9a-f]{64}\.(?:xlsx|xls|json\.gz)', filename):
        fail('排程参考文件登记无效', 409)
    path = folder / filename
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
        fail('原排程文件不存在或存储路径无效', 404)
    return path


def get_source(store, con, source_id):
    source = next((s for s in store.all(con, KIND) if s['id'] == source_id), None)
    if source is None:
        fail('未找到排程原表版本', 404)
    return source


def convert_legacy_xls(content):
    """Read a legacy workbook through a disposable local conversion.

    The uploaded .xls bytes remain the immutable registered original. The
    converted OOXML is used only for parsing, never presented as source data.
    """
    if not content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        fail('旧版 Excel 文件内容无效，请检查 .xls 文件')
    converter = shutil.which('soffice') or shutil.which('libreoffice')
    if not converter:
        fail('本机缺少旧版 Excel 转换组件，请在表格软件中另存为 .xlsx 后上传')
    with tempfile.TemporaryDirectory(prefix='kanpace-schedule-') as temp:
        root = Path(temp)
        original = root / 'schedule.xls'
        original.write_bytes(content)
        command = [converter, '-env:UserInstallation=' + (root / 'profile').as_uri(), '--headless',
                   '--convert-to', 'xlsx', '--outdir', str(root), str(original)]
        try:
            completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        except (OSError, subprocess.TimeoutExpired):
            fail('旧版 Excel 转换失败，请另存为 .xlsx 后上传')
        converted = root / 'schedule.xlsx'
        if completed.returncode or not converted.is_file() or converted.stat().st_size > MAX_UPLOAD:
            fail('旧版 Excel 转换失败，请另存为 .xlsx 后上传')
        return converted.read_bytes()


def import_reference(store, con, data):
    filename = data.get('filename')
    if not isinstance(filename, str) or not 1 <= len(filename) <= 220 or Path(filename).name != filename or any(c in filename for c in ('/', '\\')) or any(ord(c) < 32 for c in filename) or Path(filename).suffix.lower() not in ('.xlsx', '.xls'):
        fail('请提供有效的 XLSX 或 XLS 文件名')
    encoded = data.get('content_base64')
    if not isinstance(encoded, str) or not encoded or len(encoded) > (MAX_UPLOAD + 2) // 3 * 4:
        fail('Excel 内容为空或超过 20 MB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        fail('Excel 上传内容编码无效')
    if not content or len(content) > MAX_UPLOAD:
        fail('Excel 内容为空或超过 20 MB')
    digest = hashlib.sha256(content).hexdigest()
    sources = store.all(con, KIND)
    duplicate = next((s for s in sources if s['sha256'] == digest), None)
    if duplicate and duplicate.get('parser_version') == PARSER_VERSION:
        # Verify the registered original still exists instead of claiming a
        # missing/corrupted prior import is usable.
        registered_path(store, duplicate, 'original_file')
        return {'source': public_source(duplicate), 'duplicate': True,
                'selected_sheet': duplicate['default_sheet'], 'row_count': duplicate['row_count']}
    source_id = 'sref_' + digest[:24]
    if duplicate:
        filename = duplicate['filename']
    try:
        parse_content = convert_legacy_xls(content) if filename.lower().endswith('.xls') else content
        book = parse_workbook(filename, parse_content, source_id)
    except (ValueError, TypeError, KeyError, OverflowError, BadZipFile, RuntimeError) as exc:
        fail('无法读取该 XLSX 的单元格结构：' + str(exc)[:100])
    default = next(s for s in book['sheets'] if s['is_default'])
    source = {'id': source_id, 'filename': filename, 'sha256': digest,
              'snapshot_version': duplicate['snapshot_version'] if duplicate else 1 + max((s['snapshot_version'] for s in sources if s['filename'] == filename), default=0),
              'parser_version': PARSER_VERSION, 'imported_at': duplicate['imported_at'] if duplicate else datetime.now(timezone.utc).isoformat(),
              'size_bytes': len(content), 'default_sheet': book['default_sheet'], 'snapshot_date': book['snapshot_date'],
              'date_trusted': default['date_trusted'], 'date_basis': default['date_basis'],
              'row_count': default['row_count'], 'group_count': default['group_count'],
              'sheet_count': len(book['sheets']), 'reduced_copy': '删减' in filename,
              'original_file': digest + Path(filename).suffix.lower(), 'parsed_file': digest + '.json.gz',
              'stat_candidates': stat_candidates(book, filename)}
    folder = reference_directory(store)
    folder.mkdir(exist_ok=True)
    outputs = [(folder / source['original_file'], content),
               (folder / source['parsed_file'], gzip.compress(json.dumps(book, ensure_ascii=False, allow_nan=False).encode(), mtime=0))]
    for path, payload in outputs:
        if path.is_symlink():
            fail('排程参考存储文件路径无效', 409)
        temporary = path.with_name(path.name + '.tmp')
        if temporary.is_symlink():
            fail('排程参考临时路径无效', 409)
        temporary.write_bytes(payload)
        temporary.replace(path)
    store.put(con, KIND, source)
    return {'source': public_source(source), 'duplicate': bool(duplicate), 'reparsed': bool(duplicate),
            'selected_sheet': book['default_sheet'], 'row_count': default['row_count']}


def identity_key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).casefold()


def matching_projects(identity, projects):
    """Exact identities can bind automatically; fuzzy names only suggest."""
    shop, number = identity_key(identity.get('shop')), identity_key(identity.get('order_no'))
    result = []
    for project in projects:
        if project.get('demo') or project.get('archived'):
            continue
        name = identity_key(project.get('name'))
        numbers = {identity_key(project.get(key)) for key in ('external_order_no', 'order_no', 'customer_order_no') if project.get(key)}
        exact_number = bool(number and number in numbers)
        exact_name = bool(shop and name == shop)
        conflicting_number = bool(number and numbers and number not in numbers)
        overlap = min(len(name), len(shop))
        fuzzy = bool(name and shop and overlap >= 6 and (name in shop or shop in name))
        if exact_number or exact_name or fuzzy:
            exact = exact_number or exact_name and not conflicting_number
            result.append({'project_id': project['id'], 'name': project.get('name', ''), 'exact': exact,
                           'match_basis': 'order_no' if exact_number else 'name' if exact_name and not conflicting_number else 'review',
                           'reason': '完整订单号相同' if exact_number else '项目名称相同' if exact_name and not conflicting_number else
                                     '名称相同但订单号不同，请核对' if conflicting_number else '项目名称相近，请核对'})
    return sorted(result, key=lambda item: not item['exact'])


def project_reference(project, documents):
    if not project:
        return None
    docs = [d for d in documents if d.get('project_id') == project['id'] and not d.get('superseded') and not d.get('archived') and not d.get('demo')]
    renders = sorted((d for d in docs if d.get('purpose') == 'render' and d.get('image_url')),
                     key=lambda d: (d.get('render_scope') == 'project', d.get('created_at', '')), reverse=True)
    image_types = {'png', 'jpg', 'jpeg', 'webp'}
    drawings = sorted((d for d in docs if d.get('purpose', 'drawing') == 'drawing' and
                       (str(d.get('format') or Path(d.get('filename', '')).suffix.lstrip('.')).lower() in image_types | {'pdf'})),
                      key=lambda d: d.get('created_at', ''), reverse=True)
    render = next(iter(renders), None)
    drawing = next(iter(drawings), None)
    doc = render or drawing
    drawing_type = str(drawing.get('format') or Path(drawing.get('filename', '')).suffix.lstrip('.')).lower() if drawing else ''
    drawing_image_url = ('/api/documents/' + drawing['id'] +
                         ('/preview-image?page=1&thumb=1' if drawing_type == 'pdf' else '/badge-image')) if drawing else None
    return {'id': project['id'], 'name': project.get('name', ''), 'status': project.get('status'),
            'document_count': len(docs), 'document_id': doc['id'] if doc else None,
            'image_kind': 'render' if render else 'drawing' if drawing else None,
            'image_url': render['image_url'] if render else drawing_image_url,
            'render_image_url': render['image_url'] if render else None,
            'drawing_image_url': drawing_image_url,
            'drawing_name': drawing.get('filename') if drawing else None,
            'document_name': doc.get('filename') if doc else None}


def get_references(store, con, source_id=None, sheet_name=None):
    sources = store.all(con, KIND)
    sources.sort(key=lambda s: (s.get('date_trusted', False), s.get('snapshot_date') or '', not s.get('reduced_copy'), s.get('group_count', 0), s.get('imported_at', '')), reverse=True)
    stats = build_stats(sources)
    empty = {'sources': [public_source(s) for s in sources], 'selected': {'source_id': None, 'sheet': None},
             'source': None, 'sheets': [], 'columns': [], 'rows': [], 'candidates': [], 'stats': stats, 'warnings': []}
    if not sources and not source_id:
        return empty
    source = get_source(store, con, source_id) if source_id else sources[0]
    try:
        with gzip.open(registered_path(store, source, 'parsed_file'), 'rt', encoding='utf-8') as stream:
            book = json.load(stream)
    except (OSError, ValueError):
        fail('排程参考解析快照损坏，请重新核对原件', 409)
    selected_name = sheet_name or source['default_sheet']
    sheet = next((s for s in book['sheets'] if s['name'] == selected_name), None)
    if sheet is None:
        fail('该原表没有所选工作表', 404)
    projects = store.all(con, 'projects')
    candidates = {}
    for row in sheet['rows']:
        row['suggestions'] = matching_projects(row['identity'], projects)
        candidate = candidates.setdefault(row['group_id'], {'group_id': row['group_id'], 'order_key': row['order_key'],
            'identity': row['identity'], 'row_ids': [], 'row_numbers': row['group_row_numbers'], 'suggestions': row['suggestions']})
        candidate['row_ids'].append(row['id'])
    warnings = list(book['warnings'])
    if source.get('reduced_copy'):
        warnings.append('此文件为删减副本；缺少的原表行不表示取消订单。')
    if not sheet.get('date_trusted'):
        warnings.append('所选工作表快照日期未确认，不作为可靠的最新统计样本。')
    result = {**empty, 'source': public_source(source), 'selected': {'source_id': source['id'], 'sheet': selected_name},
            'sheets': [{k: v for k, v in s.items() if k not in ('rows', 'columns')} for s in book['sheets']],
            'columns': sheet['columns'], 'rows': sheet['rows'], 'candidates': list(candidates.values()), 'warnings': warnings}
    result['working'] = working_schedule(store, con, result)
    by_group = {order['key']: order for order in result['working']['orders']}
    for row in result['rows']:
        working = by_group[row['group_id']]
        row.update(project_id=working.get('project_id'), project=working.get('project'), match_status=working.get('match_status'))
    documents = store.all(con, 'documents')
    result['projects'] = [project_reference(p, documents) for p in projects if not p.get('demo') and not p.get('archived')]
    return result

# Editable production preparation is separate from immutable workbook evidence.
# Dependencies below are an explicit factory proposal, never inferred solely
# from the chronological order of spreadsheet milestone dates.
WORKING_KIND = 'schedule_reference_working'
WORKING_NODES = [('technical', '技术拆单'), ('wood', '木作'), ('paint', '油漆'),
                 ('metal', '五金'), ('outsourcing', '外协配套'), ('assembly', '安装总装'),
                 ('packing', '包装'), ('shipping', '发货')]
WORKING_ROUTE = {'technical': [], 'wood': ['technical'], 'metal': ['technical'],
                 'outsourcing': ['technical'], 'paint': ['wood'],
                 'assembly': ['paint', 'metal', 'outsourcing'], 'packing': ['assembly'], 'shipping': ['packing']}


def working_id(source_id, sheet):
    return 'sw_' + hashlib.sha256((source_id + '\n' + sheet).encode()).hexdigest()[:24]


def cycle_estimate(nodes, start_date=None):
    import math
    active = [node for node in nodes if node.get('enabled', True)]
    known = {node['id']: node for node in active}
    if len(known) != len(active):
        fail('工序编号重复')
    for node in active:
        days = node.get('days')
        if days is not None and (type(days) not in (int, float) or not math.isfinite(days) or not 0 <= days <= 36500):
            fail('工序周期须为0至36500的日历天数，未知请留空')
        if any(key not in known or key == node['id'] for key in node['predecessors']):
            fail('前置工序不存在、已停用或依赖自身')
    pending = set(known)
    ordered, calculated = [], {}
    while pending:
        ready = [node['id'] for node in active if node['id'] in pending and all(p in calculated for p in node['predecessors'])]
        if not ready:
            fail('前后工序形成循环，请取消一条前置关系')
        for key in ready:
            node = known[key]
            previous = [calculated[p]['finish'] for p in node['predecessors']]
            start = None if any(p is None for p in previous) else max([0] + previous)
            finish = None if start is None or node.get('days') is None else start + node['days']
            calculated[key] = {'id': key, 'start': start, 'finish': finish}
            if start_date and full_date(start_date):
                # CPM offsets are elapsed time; execution-plan end dates are
                # inclusive. A three-day interval Mon→Thu ends on Wednesday.
                end_day = None if finish is None else max(math.ceil(start), math.ceil(finish) - 1)
                for name, value in [('start_date', start), ('end_date', end_day)]:
                    calculated[key][name] = (date.fromisoformat(full_date(start_date)) + timedelta(days=math.ceil(value))).isoformat() if value is not None else None
            ordered.append(key)
            pending.remove(key)
    values = [n['finish'] for n in calculated.values()]
    return {'order': ordered, 'nodes': list(calculated.values()), 'total_days': max(values) if values and all(v is not None for v in values) else None,
            'method': 'CPM_longest_path', 'unit': 'calendar_days'}


def working_schedule(store, con, data):
    source_id, sheet = data['source']['id'], data['selected']['sheet']
    identifier = working_id(source_id, sheet)
    saved = next((row for row in store.all(con, WORKING_KIND) if row['id'] == identifier), None)
    if saved:
        result = json.loads(json.dumps(saved))
    else:
        grouped = {}
        for row in data['rows']:
            group = grouped.setdefault(row['group_id'], {'key': row['group_id'], 'identity': row['identity'], 'rows': []})
            group['rows'].append(row)
        stats = {s['node_id']: s for s in data['stats']}
        source = get_source(store, con, source_id)
        orders = []
        for index, group in enumerate(grouped.values()):
            first = group['rows'][0]
            start = next((r['cells'].get('order_date', {}).get('date') for r in group['rows'] if r['cells'].get('order_date', {}).get('date')), None)
            order = {'key': group['key'], 'match_key': normalize(group['identity'].get('order_no')), 'identity': group['identity'],
                     'source_rows': [r['row_number'] for r in group['rows']], 'priority': 0, 'position': index + 1,
                     'start_date': start, 'confirmed': False, 'manual': False, 'project_id': '', 'task_mappings': [], 'nodes': []}
            for key, label in WORKING_NODES:
                stat = stats.get(key, {})
                milestone = next((r['nodes'].get(key, {}).get('date') for r in group['rows'] if r['nodes'].get(key, {}).get('date')), None)
                sample = next((sample for sample in source.get('stat_candidates', [])
                               if sample.get('node_id') == key and sample.get('sheet') == sheet and sample.get('row') in order['source_rows']
                               and not sample.get('reason') and sample.get('date_trusted')), None)
                order['nodes'].append({'id': key, 'label': label, 'enabled': True, 'days': sample['days'] if sample else stat.get('p50') if stat.get('n', 0) else None,
                    'predecessors': list(WORKING_ROUTE[key]), 'duration_source': 'order_dates' if sample else 'source_p50' if stat.get('n', 0) else 'unknown',
                    'duration_basis': ({k: sample.get(k) for k in ('filename', 'sheet', 'row', 'start', 'end', 'start_cell', 'end_cell')} if sample else None),
                    'relationship_source': 'cabinet_template', 'sample_count': 1 if sample else stat.get('n', 0), 'milestone_date': milestone, 'manual': False})
            orders.append(order)
        result = {'id': identifier, 'source_id': source_id, 'sheet': sheet, 'version': 0, 'orders': orders}
    projects = {p['id']: p for p in store.all(con, 'projects')}
    tasks = {t['id']: t for t in store.all(con, 'tasks')}
    documents = store.all(con, 'documents')
    suggestions = {order['key']: matching_projects(order['identity'], list(projects.values())) for order in result['orders']}
    exact_claims = Counter(candidate['project_id'] for order in result['orders'] for candidate in suggestions[order['key']] if candidate['exact'])
    import fulfillment
    for order in result['orders']:
        matches = suggestions[order['key']]
        exact = [m for m in matches if m['exact']]
        if not order.get('project_id') and not order.get('project_binding_manual'):
            if len(exact) == 1 and exact_claims[exact[0]['project_id']] == 1:
                order.update(project_id=exact[0]['project_id'], match_status='matched', match_basis=exact[0]['match_basis'])
            else:
                order['match_status'] = 'review' if matches else 'unmatched'
        project = projects.get(order.get('project_id'))
        bound = [tasks.get(m.get('task_id')) for m in order.get('task_mappings', [])]
        order['project'] = project_reference(project, documents)
        order['suggestions'] = matches
        if project and order.get('project_binding_manual'):
            order['match_status'] = 'manual'
        elif project and not order.get('match_status'):
            order['match_status'] = 'matched'
        order['locked'] = bool(project and (fulfillment.is_closed(project) or project.get('archived'))) or bool(bound and all(t and t.get('status') == 'done' for t in bound))
        order['lock_reason'] = '已完成或已交付，保留排程历史' if order['locked'] else ''
        order['estimate'] = cycle_estimate(order['nodes'], order.get('start_date'))
    result['orders'].sort(key=lambda order: (-order['priority'], order['position'], order['key']))
    return result


def _working_context(store, con, data):
    source_id, sheet = data.get('source_id'), data.get('sheet')
    if not isinstance(source_id, str) or not isinstance(sheet, str) or not source_id or not sheet:
        fail('请指定排程文件和工作表')
    grid = get_references(store, con, source_id, sheet)
    return grid, grid['working']


def _working_version(working, data):
    if type(data.get('expected_version')) is not int or data['expected_version'] != working['version']:
        fail('排程已更新，请刷新后重新核对；本次编辑未覆盖', 409)


def _write_working(store, con, working):
    working['version'] += 1
    working['updated_at'] = datetime.now(timezone.utc).isoformat()
    store.put(con, WORKING_KIND, working)
    return {'working': working}


def save_working(store, con, data):
    _, working = _working_context(store, con, data)
    _working_version(working, data)
    key = data.get('order_key')
    order = next((row for row in working['orders'] if row['key'] == key), None)
    if not order:
        fail('未找到选中的排程订单', 404)
    if order['locked']:
        fail(order['lock_reason'], 409)
    changes = data.get('changes')
    if not isinstance(changes, dict) or set(changes) - {'priority', 'position', 'start_date', 'confirmed', 'nodes', 'project_id'}:
        fail('排程编辑字段无效')
    if 'project_id' in changes:
        project_id = changes['project_id']
        projects = {p['id']: p for p in store.all(con, 'projects') if not p.get('demo') and not p.get('archived')}
        if project_id and project_id not in projects:
            fail('关联项目不存在，请重新选择', 409)
        if order.get('task_mappings') and project_id != order.get('project_id'):
            fail('已排工序不能改绑其他项目', 409)
        if project_id and any(other['key'] != key and other.get('project_id') == project_id for other in working['orders']):
            fail('该项目已关联本表其他订单，请核对订单范围', 409)
        changes = {**changes, 'project_binding_manual': True, 'match_status': 'manual' if project_id else 'unmatched',
                   'project': project_reference(projects.get(project_id), store.all(con, 'documents'))}
    for name, limit in [('priority', 3), ('position', 1000000)]:
        if name in changes and (type(changes[name]) is not int or not 0 <= changes[name] <= limit):
            fail('优先级或顺序须为有效整数')
    if 'start_date' in changes and changes['start_date'] not in (None, '') and not full_date(changes['start_date']):
        fail('请选择有效的开始日期')
    if 'start_date' in changes:
        changes = {**changes, 'start_date': full_date(changes['start_date'])}
    if 'confirmed' in changes and type(changes['confirmed']) is not bool:
        fail('关系确认状态无效')
    if 'nodes' in changes:
        nodes = changes['nodes']
        ids = {key for key, _ in WORKING_NODES}
        if not isinstance(nodes, list) or len(nodes) != len(ids) or any(not isinstance(node, dict) or not isinstance(node.get('id'), str) for node in nodes) or {node['id'] for node in nodes} != ids:
            fail('必须保留完整工序清单；不需要的工序可停用')
        current = {node['id']: node for node in order['nodes']}
        updated = []
        for node in nodes:
            if set(node) - {'id', 'enabled', 'days', 'predecessors'} or type(node.get('enabled')) is not bool or not isinstance(node.get('predecessors'), list) or any(not isinstance(p, str) for p in node['predecessors']) or len(node['predecessors']) != len(set(node['predecessors'])):
                fail('工序关系格式无效')
            original = current[node['id']]
            manual = any(node.get(k) != original.get(k) for k in ('enabled', 'days', 'predecessors'))
            updated.append({**original, **node, 'manual': original.get('manual', False) or manual,
                            'duration_source': 'manual' if node.get('days') != original.get('days') else original['duration_source']})
        cycle_estimate(updated, changes.get('start_date', order.get('start_date')))
        changes = {**changes, 'nodes': updated}
    order.update(changes, manual=True)
    order['estimate'] = cycle_estimate(order['nodes'], order.get('start_date'))
    return _write_working(store, con, working)


def replacement_preview(store, con, data):
    _, target = _working_context(store, con, data)
    if not isinstance(data.get('incoming_source_id'), str) or not data['incoming_source_id'] or not isinstance(data.get('incoming_sheet'), str) or not data['incoming_sheet']:
        fail('请选择新Excel及其工作表')
    if data['incoming_source_id'] == target['source_id'] and data['incoming_sheet'] == target['sheet']:
        fail('新表与当前排程相同，无需覆盖')
    incoming = get_references(store, con, data['incoming_source_id'], data['incoming_sheet'])
    source = incoming['working']
    # Always derive from incoming immutable Excel, not somebody's edited draft.
    fresh_id = working_id(source['source_id'], source['sheet'])
    saved = next((row for row in store.all(con, WORKING_KIND) if row['id'] == fresh_id), None)
    incoming_orders = source['orders']
    lookup = defaultdict(list)
    for row in incoming_orders:
        if row['match_key']:
            lookup[row['match_key']].append(row)
    target_counts = Counter(row['match_key'] for row in target['orders'] if row['match_key'])
    rows = []
    for order in target['orders']:
        matches = lookup[order['match_key']] if order['match_key'] else []
        matched = matches[0] if len(matches) == 1 and target_counts[order['match_key']] == 1 else None
        reason = order['lock_reason'] if order['locked'] else '新表没有相同完整单号，原记录保留' if not matches else '完整单号重复，不能自动匹配' if not matched else '新表含人工编辑，请选择未编辑的原表版本' if saved and matched.get('manual') else ''
        rows.append({'order_key': order['key'], 'identity': order['identity'], 'incoming_key': matched['key'] if matched else None,
                     'selectable': not bool(reason), 'reason': reason, 'has_manual': order.get('manual', False),
                     'before': {'source_rows': order['source_rows'], 'start_date': order.get('start_date'), 'nodes': order['nodes']},
                     'after': {'source_rows': matched['source_rows'], 'start_date': matched.get('start_date'), 'nodes': matched['nodes']} if matched else None})
    return {'target_version': target['version'], 'source_id': target['source_id'], 'sheet': target['sheet'],
            'incoming_source_id': source['source_id'], 'incoming_sheet': source['sheet'], 'rows': rows,
            'scope': '只覆盖勾选且完整单号唯一匹配的订单；缺失订单和已完成历史保留，生产报工不变'}


def replace_working(store, con, data):
    _, target = _working_context(store, con, data)
    _working_version(target, data)
    preview = replacement_preview(store, con, data)
    keys = data.get('selected_order_keys')
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys) or len(set(keys)) != len(keys):
        fail('请选择本次覆盖的明确订单')
    indexed = {row['order_key']: row for row in preview['rows']}
    if any(k not in indexed or not indexed[k]['selectable'] for k in keys):
        fail('所选订单已完成、重复或无法匹配，未覆盖任何记录', 409)
    if any(indexed[k]['has_manual'] for k in keys) and data.get('overwrite_manual') is not True:
        fail('所选订单包含人工修改，请明确确认覆盖这些人工修改', 409)
    incoming = get_references(store, con, preview['incoming_source_id'], preview['incoming_sheet'])['working']
    by_id = {row['key']: row for row in incoming['orders']}
    for order in target['orders']:
        if order['key'] not in keys:
            continue
        fresh = by_id[indexed[order['key']]['incoming_key']]
        order.update(nodes=fresh['nodes'], start_date=fresh['start_date'], source_rows=fresh['source_rows'], confirmed=False, manual=False,
                     replaced_from={'source_id': incoming['source_id'], 'sheet': incoming['sheet']})
        # Existing explicit project/task bindings and table priority remain.
        order['estimate'] = cycle_estimate(order['nodes'], order.get('start_date'))
    return _write_working(store, con, target)


def apply_working(store, con, data):
    import planning
    _, working = _working_context(store, con, data)
    _working_version(working, data)
    order = next((row for row in working['orders'] if row['key'] == data.get('order_key')), None)
    if not order or order['locked']:
        fail('订单不存在或已完成，不能改写历史排程', 409)
    if order.get('confirmed') is not True:
        fail('请先核对并保存工序关系与周期')
    mappings = data.get('task_mappings')
    if not isinstance(mappings, list) or not mappings or len(mappings) > 200:
        fail('请明确选择要排产的已发布工序')
    ctx = planning.context(store, con)
    if not isinstance(data.get('project_id'), str) or data['project_id'] not in ctx['projects']:
        fail('请明确关联一个本地工程项目')
    if order.get('project_id') and order.get('task_mappings') and order['project_id'] != data['project_id']:
        fail('本单已关联工程项目，不能把已排任务转入另一项目', 409)
    active_nodes = {node['id']: node for node in order['nodes'] if node['enabled']}
    seen = set()
    pending = {}
    for item in mappings:
        if not isinstance(item, dict) or not isinstance(item.get('node_id'), str) or not isinstance(item.get('task_id'), str) or item['node_id'] not in active_nodes or item['task_id'] in seen:
            fail('工序映射重复或节点已停用')
        task = ctx['tasks'].get(item.get('task_id'))
        if not planning.eligible(task, ctx) or task['project_id'] != data['project_id']:
            fail('只能选择所关联项目内已发布且未完工的工序', 409)
        if type(item.get('expected_task_version')) is not int or item['expected_task_version'] != task['execution_version']:
            fail('工序已更新，请刷新后重新核对', 409)
        seen.add(task['id']); pending[task['id']] = item
    by_node = defaultdict(list)
    for item in mappings:
        by_node[item['node_id']].append(item)
    for item in mappings:
        for predecessor in active_nodes[item['node_id']]['predecessors']:
            for previous in by_node[predecessor]:
                if planning.parse_day(previous.get('end_date')) >= planning.parse_day(item.get('start_date')):
                    fail('表内前后序日期冲突，请把后序安排在前序结束后的工作日', 409)
    # A confirmed worksheet prerequisite also governs actual dispatch/start.
    # Existing engineering dependencies cannot be removed by worksheet edits.
    combined = {m['task_id']: m for m in order.get('task_mappings', [])}
    combined.update({m['task_id']: m for m in mappings})
    all_by_node = defaultdict(list)
    for item in combined.values():
        candidate = ctx['tasks'].get(item['task_id'])
        if candidate and candidate.get('project_id') == data['project_id'] and not candidate.get('archived'):
            all_by_node[item['node_id']].append(candidate['id'])
    labels = dict(WORKING_NODES)
    for item in mappings:
        task = ctx['tasks'][item['task_id']]
        binding = task.get('schedule_reference_binding') or {}
        if binding and (binding.get('working_id') != working['id'] or binding.get('order_key') != order['key']):
            fail('工序已属于其他排程订单，请先核对关联范围', 409)
        predecessors = active_nodes[item['node_id']]['predecessors']
        task['schedule_dependencies'] = list(dict.fromkeys(tid for node in predecessors for tid in all_by_node[node]))
        # Engineering release is the authoritative completion of preparation
        # when the factory has no separate technical production task.
        task['schedule_unmapped_predecessors'] = [labels[node] for node in predecessors if not all_by_node[node] and node != 'technical']
        task['schedule_reference_binding'] = {'working_id': working['id'], 'order_key': order['key'], 'source_id': working['source_id'], 'sheet': working['sheet']}
    # Validate the combined graph, including previous worksheet bindings.
    unresolved = {tid for tid, task in ctx['tasks'].items() if task.get('project_id') == data['project_id'] and not task.get('archived')}
    while unresolved:
        ready = {tid for tid in unresolved if not any(dep in unresolved for dep in planning.task_dependencies(ctx['tasks'][tid]))}
        if not ready:
            fail('排程前序与工程前序合并后形成循环，请调整表内关系', 409)
        unresolved -= ready
    # Existing engineering dependencies remain authoritative. Forecast edits
    # cannot silently remove released engineering prerequisites.
    sequence = []
    while pending:
        ready = [key for key in pending if not any(dep in pending for dep in planning.task_dependencies(ctx['tasks'][key]))]
        if not ready:
            fail('已发布工程任务的依赖存在循环')
        for key in ready:
            sequence.append(pending.pop(key))
    plans = []
    previous_by_task = {p['task_id']: p for p in ctx['plans'] if p.get('status') == 'scheduled' and p['task_id'] in seen}
    for item in mappings:
        previous = previous_by_task.get(item['task_id'])
        if previous and (type(item.get('expected_plan_version')) is not int or item['expected_plan_version'] != previous['version']):
            fail('已有排程已更新，请刷新后重新核对', 409)
        if not previous and item.get('expected_plan_version') not in (None, 0):
            fail('已有排程已失效，请刷新后重新核对', 409)
    replacing = {p['id'] for p in previous_by_task.values()}
    con.execute('SAVEPOINT schedule_apply')
    try:
        for index, item in enumerate(sequence):
            task = ctx['tasks'][item['task_id']]
            previous = previous_by_task.get(task['id'])
            payload = {k: item[k] for k in ('task_id', 'expected_task_version', 'start_date', 'end_date', 'planned_minutes') if k in item}
            payload.update(minutes_source='manual', material_status=previous['material_status'] if previous else 'pending',
                           note='生产排程表核定：' + str(order['identity'].get('order_no') or order['identity'].get('shop')))
            if previous:
                if type(item.get('expected_plan_version')) is not int or item['expected_plan_version'] != previous['version']:
                    fail('已有排程已更新，请刷新后重新核对', 409)
                payload.update(id=previous['id'], expected_version=previous['version'])
            task['priority'] = order['priority']; task['schedule_position'] = order['position']
            store.save_execution(con, task, 'schedule_confirmed', '核定排程顺序与开工前序',
                                 schedule_dependencies=task['schedule_dependencies'],
                                 schedule_unmapped_predecessors=task['schedule_unmapped_predecessors'],
                                 schedule_reference_binding=task['schedule_reference_binding'])
            payload['expected_task_version'] = task['execution_version']
            plan = planning.save(store, con, payload, replacing_plan_ids=replacing)['plan']
            if previous:
                replacing.discard(previous['id'])
            plans.append(plan)
        bound = {m['task_id']: m for m in order.get('task_mappings', [])}
        bound.update({m['task_id']: m for m in mappings})
        order.update(project_id=data['project_id'], task_mappings=list(bound.values()), applied_plan_ids=list(dict.fromkeys(order.get('applied_plan_ids', []) + [p['id'] for p in plans])))
        result = _write_working(store, con, working)
        con.execute('RELEASE schedule_apply')
        return {**result, 'plans': plans}
    except Exception:
        con.execute('ROLLBACK TO schedule_apply'); con.execute('RELEASE schedule_apply'); raise
