"""Traceable order-scope drafts. These records never authorize production."""
from __future__ import annotations
import hashlib
import math
import re
from pathlib import Path

SCHEMA = 'cabinet-order-draft-v1'
TRADES = {'木工', '五金', '油漆', '玻璃', '电工', '装配', '质检', '包装'}
LEVELS = {'assembly', 'component', 'material', 'unknown'}
LOCATOR_KINDS = {'pdf_region', 'image_region', 'table_cell', 'step_face', 'dxf_entity', 'csv_cell', 'json_pointer', 'text_line'}


def text(value, field, limit=4000, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(field + ' 必须为有效文字')
    return value.strip()


def numeric(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1e9:
        raise ValueError(field + ' 必须为正数或 null')
    return value


def strings(value, field, limit=200):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(field + ' 必须为文字数组')
    return list(dict.fromkeys(text(item, field, 4000, True) for item in value))


def objects(value, field, limit=10000):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, dict) for item in value):
        raise ValueError(field + ' 必须为对象数组')
    return value


def identifier(value, field):
    value = text(value, field, 200, True)
    if any(ord(c) < 32 for c in value):
        raise ValueError(field + ' 不可含控制字符')
    return value


def source_path(value):
    path = text(value, 'source_path', 4000, True)
    if not Path(path).is_absolute() or any(ord(c) < 32 for c in path):
        raise ValueError('source_path 必须为本地绝对路径')
    return path


def digest(value, field='source_sha256'):
    if value is None or value == '':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError(field + ' 必须为 64 位 SHA-256 十六进制值')
    return value.lower()


def revision(value, field='source_revision'):
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return text(value, field, 200, True)


def index(value, field, ranges=False):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if numeric(value, field) != int(value):
            raise ValueError(field + ' 应为从 1 开始的整数')
        return value
    if ranges and isinstance(value, str):
        # Older drafts used textual page/row ranges; keep their representation.
        if re.fullmatch(r'[1-9]\d*(?:\s*[-–—:]\s*[1-9]\d*)?(?:\s*[,，]\s*[1-9]\d*(?:\s*[-–—:]\s*[1-9]\d*)?)*', value):
            return value
    raise ValueError(field + ' 应为从 1 开始的整数' + ('或范围' if ranges else ''))


def finite(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e9:
        raise ValueError(field + ' 必须为有限坐标')
    return value


def bounds(value, field='bbox', nonnegative=True):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(field + ' 必须为 [x0,y0,x1,y1]')
    result = [finite(v, field) for v in value]
    if result[2] <= result[0] or result[3] <= result[1] or (nonnegative and min(result) < 0):
        raise ValueError(field + ' 必须有正面积且坐标有效')
    return result


def page_size(value, field):
    if isinstance(value, list) and len(value) == 2:
        values = [numeric(v, field) for v in value]
        result = values
    elif isinstance(value, dict):
        values = [numeric(value.get(k), field + '.' + k) for k in ('width', 'height')]
        result = dict(zip(('width', 'height'), values))
    else:
        raise ValueError(field + ' 需要 [width,height] 或 width/height 对象')
    if any(v is None for v in values):
        raise ValueError(field + ' 需要正数 width/height')
    return result


def size_values(value):
    return [value['width'], value['height']] if isinstance(value, dict) else value


def metadata(value, field, depth=0):
    """Bounded JSON metadata, including explicit unknown/null model values."""
    if depth > 5:
        raise ValueError(field + ' 嵌套过深')
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return text(value, field, 20000 if field == 'candidate' else 4000)
    if isinstance(value, (int, float)):
        return finite(value, field)
    if isinstance(value, list) and len(value) <= 100:
        return [metadata(v, field, depth + 1) for v in value]
    if isinstance(value, dict) and len(value) <= 64:
        return {text(k, field, 100, True): metadata(v, field, depth + 1) for k, v in value.items()}
    raise ValueError(field + ' 必须为有限的 JSON 元数据')


def locator(item):
    if not isinstance(item, dict) or item.get('kind') not in LOCATOR_KINDS:
        raise ValueError('locator.kind 不支持')
    result = {'kind': item['kind']}
    for key in ('page', 'row', 'column', 'line', 'end_line'):
        if item.get(key) is not None:
            result[key] = index(item[key], 'locator.' + key)
    for key in ('sheet', 'cell', 'table_id', 'layer', 'entity_type'):
        if item.get(key) is not None:
            result[key] = text(item[key], 'locator.' + key, 500)
    if 'bbox' in item and item['bbox'] is None:
        result['bbox'] = None
    elif item.get('bbox') is not None:
        result['bbox'] = bounds(item['bbox'])
    for key in ('bbox_pdf_points', 'bbox_pixels'):
        if key in item:
            result[key] = None if item[key] is None else bounds(item[key], key)
    if result.get('bbox_pdf_points') is not None:
        if result.get('bbox') is not None and result['bbox'] != result['bbox_pdf_points']:
            raise ValueError('bbox 与 bbox_pdf_points 不一致')
        result.setdefault('bbox', result['bbox_pdf_points'])
        if result.get('bbox') is None:
            result['bbox'] = result['bbox_pdf_points']
    kind = result['kind']
    if kind == 'pdf_region' and not (result.get('page') and result.get('bbox')):
        raise ValueError('pdf_region 需要 1 基页码与 bbox')
    if kind == 'table_cell' and ('row' not in result or not (result.get('page') or result.get('sheet'))):
        raise ValueError('table_cell 需要 1 基行号以及 page 或 sheet')
    if kind == 'image_region':
        if not result.get('page') or not result.get('bbox_pixels') or item.get('page_size_pixels') is None:
            raise ValueError('image_region 需要 1 基页码、bbox_pixels 和 page_size_pixels')
        if result.get('bbox_pdf_points') is not None or item.get('page_size_pdf_points') is not None:
            raise ValueError('image_region 不可冒充 PDF points')
        if result.get('bbox') is not None and result['bbox'] != result['bbox_pixels']:
            raise ValueError('image_region bbox 必须为空或与 bbox_pixels 一致')
        system = item.get('coordinate_system', 'pixels')
        if system not in ('pixels', 'image_pixels'):
            raise ValueError('image_region coordinate_system 必须为 pixels/image_pixels')
        result['coordinate_system'] = system
        result['page_size_pixels'] = page_size(item['page_size_pixels'], 'page_size_pixels')
        width, height = size_values(result['page_size_pixels'])
        if result['bbox_pixels'][2] > width or result['bbox_pixels'][3] > height:
            raise ValueError('bbox_pixels 超出原图大小')
    if kind == 'step_face':
        result['face_id'] = identifier(str(item['face_id']), 'face_id') if isinstance(item.get('face_id'), str) else index(item.get('face_id'), 'face_id')
        if item.get('assembly_path') is not None:
            value = item['assembly_path']
            result['assembly_path'] = strings(value, 'assembly_path', 100) if isinstance(value, list) else text(value, 'assembly_path', 2000, True)
    if kind == 'dxf_entity':
        result['handle'] = identifier(item.get('handle'), 'handle')
    if kind == 'csv_cell' and not all(key in result for key in ('row', 'column')):
        raise ValueError('csv_cell 需要 1 基 row/column')
    if kind == 'json_pointer':
        if not isinstance(item.get('pointer'), str):
            raise ValueError('json_pointer 需要 pointer，根节点使用空字符串')
        pointer = text(item.get('pointer'), 'pointer', 2000)
        if (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])', pointer):
            raise ValueError('pointer 必须为 RFC 6901 JSON Pointer')
        result['pointer'] = pointer
    if kind == 'text_line' and 'line' not in result:
        raise ValueError('text_line 需要 1 基 line')
    if result.get('end_line') is not None and result['end_line'] < result.get('line', result['end_line']):
        raise ValueError('end_line 不可早于 line')
    if kind in ('pdf_region', 'image_region', 'table_cell'):
        coordinate_system = item.get('coordinate_system', 'pdf_points' if kind == 'pdf_region' else 'pixels' if kind == 'image_region' else None)
        if coordinate_system is not None:
            if coordinate_system not in ('pdf_points', 'image_pixels', 'pixels', 'normalized'):
                raise ValueError('coordinate_system 无效')
            if kind == 'pdf_region' and (coordinate_system != 'pdf_points' or result.get('bbox_pixels') is not None):
                raise ValueError('pdf_region 必须使用 PDF points，不可混用像素')
            result['coordinate_system'] = coordinate_system
        if item.get('origin') is not None:
            if item['origin'] not in ('top_left', 'bottom_left'):
                raise ValueError('origin 必须为 top_left/bottom_left')
            result['origin'] = item['origin']
        if item.get('canonical_origin') is not None:
            if item['canonical_origin'] != 'top_left' or item.get('origin', 'top_left') != 'top_left':
                raise ValueError('canonical_origin 必须为 top_left 且与 origin 一致')
            result['canonical_origin'] = item['canonical_origin']
        if item.get('coordinate_space') is not None:
            space = item['coordinate_space']
            allowed = ('original_image_pixels',) if kind == 'image_region' else ('pdf_display_page', 'pdf_media_display_page', 'pdfium_page')
            if space not in allowed:
                raise ValueError('coordinate_space 无效或与坐标单位不一致')
            result['coordinate_space'] = space
        if item.get('rotation') is not None:
            if isinstance(item['rotation'], bool) or item['rotation'] not in (0, 90, 180, 270):
                raise ValueError('rotation 必须为 0/90/180/270')
            result['rotation'] = item['rotation']
        elif 'rotation' in item:
            result['rotation'] = None
        for key in ('page_size_pdf_points', 'image_size_pixels'):
            if item.get(key) is not None:
                result[key] = page_size(item[key], key)
            elif key in item:
                result[key] = None
        for key in ('crop_box', 'cropbox', 'mediabox'):
            if key in item:
                result[key] = None if item[key] is None else bounds(item[key], key, nonnegative=False)
        for matrix_key in ('crop_to_page_matrix', 'crop_to_page_transform'):
            if matrix_key not in item:
                continue
            matrix = item[matrix_key]
            if matrix is None:
                result[matrix_key] = None
                continue
            if isinstance(matrix, list) and len(matrix) == 3 and all(isinstance(row, list) and len(row) == 3 for row in matrix):
                result[matrix_key] = [[finite(v, matrix_key) for v in row] for row in matrix]
            elif isinstance(matrix, list) and len(matrix) in (6, 9):
                result[matrix_key] = [finite(v, matrix_key) for v in matrix]
            else:
                raise ValueError(matrix_key + ' 必须为 6/9 项或 3×3 有限矩阵')
        if result.get('bbox') is not None:
            size = result.get('page_size_pdf_points') if coordinate_system == 'pdf_points' else result.get('image_size_pixels')
            if coordinate_system == 'normalized' and max(result['bbox']) > 1:
                raise ValueError('normalized bbox 不可超出 0..1')
            if size:
                width, height = size_values(size)
                if result['bbox'][2] > width or result['bbox'][3] > height:
                    raise ValueError('bbox 超出页面/图像范围')
    return result


def provenance(item, result):
    """Keep provenance separate from review; imported candidates are never approved."""
    for key in ('document_id', 'source_document_id', 'source_id'):
        if item.get(key) is not None:
            result[key] = identifier(item[key], key)
    if result.get('document_id') and result.get('source_document_id') and result['document_id'] != result['source_document_id']:
        raise ValueError('document_id 与 source_document_id 不一致')
    if result.get('source_document_id'):
        result.setdefault('document_id', result['source_document_id'])
    for key in ('sha256', 'source_sha256', 'model_sha256'):
        if key in item:
            result[key] = digest(item[key], key)
    if result.get('sha256') and result.get('source_sha256') and result['sha256'] != result['source_sha256']:
        raise ValueError('sha256 与 source_sha256 不一致')
    if result.get('sha256'):
        result.setdefault('source_sha256', result['sha256'])
    for key in ('revision', 'source_revision'):
        if key in item:
            result[key] = revision(item[key], key)
    if result.get('revision') is not None and result.get('source_revision') is not None and str(result['revision']) != str(result['source_revision']):
        raise ValueError('revision 与 source_revision 不一致')
    for key in ('engine', 'model', 'metadata'):
        if key in item:
            result[key] = metadata(item[key], key)
            if key == 'model' and isinstance(result[key], dict) and 'sha256' in result[key]:
                result[key]['sha256'] = digest(result[key]['sha256'], 'model.sha256')
    for key in ('engine_version', 'model_revision'):
        if key in item:
            result[key] = revision(item[key], key) if key == 'model_revision' else text(item[key], key, 200)
    if 'observation_kind' in item:
        if item['observation_kind'] not in (None, 'observed', 'inferred'):
            raise ValueError('observation_kind 必须为 observed/inferred 或 null')
        result['observation_kind'] = item['observation_kind']
    if item.get('review_status') not in (None, 'unreviewed', 'pending', 'approved', 'rejected'):
        raise ValueError('review_status 无效')
    result['review_status'] = 'unreviewed'
    return result


def evidence(item):
    if not isinstance(item, dict):
        raise ValueError('evidence 必须为对象')
    result = {key: text(item.get(key), key, 20000 if key == 'quote' else 4000)
              for key in ('source_path', 'file', 'sheet', 'cell', 'reference', 'quote', 'role') if item.get(key) is not None}
    for key in ('evidence_id', 'source_role', 'method'):
        if item.get(key) is not None:
            result[key] = text(item[key], key, 500)
    if 'raw_text' in item:
        result['raw_text'] = text(item['raw_text'], 'raw_text', 20000)
    if 'candidate' in item:
        result['candidate'] = metadata(item['candidate'], 'candidate')
    if 'is_manufacturing_dimension' in item:
        if not isinstance(item['is_manufacturing_dimension'], bool):
            raise ValueError('is_manufacturing_dimension 必须为布尔值')
        result['is_manufacturing_dimension'] = False
    if result.get('source_path'):
        result['source_path'] = source_path(result['source_path'])
    for key in ('page', 'row'):
        if item.get(key) is not None:
            result[key] = index(item[key], key, ranges=True)
    if item.get('bbox') is not None:
        result['bbox'] = bounds(item['bbox'])
    if item.get('locator') is not None:
        result['locator'] = locator(item['locator'])
        if result.get('page') is not None and result['locator'].get('page') is not None and result['page'] != result['locator']['page']:
            raise ValueError('page 与 locator.page 不一致')
    return provenance(item, result)


def bind_evidence(item, sources):
    """Resolve supplied identities against the declared source manifest, never quotes."""
    identities = ('document_id', 'source_path', 'source_id')
    supplied = {key: item[key] for key in identities if item.get(key)}
    if not supplied:
        if item.get('locator'):
            raise ValueError('structured locator 需要来源身份')
        return item  # v1 quote/cell-only references remain readable.
    matches = [source for source in sources if all(source.get('id' if key == 'source_id' else key) == value for key, value in supplied.items())]
    if len(matches) != 1:
        raise ValueError('evidence 来源必须唯一对应 sources 中的登记文件')
    source = matches[0]
    for key, alias in (('source_sha256', 'source_sha256'), ('source_revision', 'source_revision')):
        expected = source.get(alias)
        if expected is None:
            expected = source.get('revision') if key == 'source_revision' else source.get('sha256')
        current = item.get(key, item.get('revision') if key == 'source_revision' else None)
        if current is not None and expected is not None and str(current) != str(expected):
            raise ValueError('evidence ' + key + ' 与来源不一致')
        if expected is not None:
            item.setdefault(key, expected)
    if source.get('document_id'):
        item.setdefault('document_id', source['document_id'])
    item.setdefault('source_id', source['id'])
    return item


def normalise(payload):
    if not isinstance(payload, dict):
        raise ValueError('拆单草稿必须为对象')
    order_key = text(payload.get('order_key'), 'order_key', 300, True)
    revision = text(payload.get('source_revision'), 'source_revision', 200, True)
    project = payload.get('project')
    if not isinstance(project, dict):
        raise ValueError('缺少 project')
    project = {key: text(project.get(key), key, 200, key == 'name') for key in ('name', 'client', 'due_date')}
    project['quantity'] = numeric(payload['project'].get('quantity'), '项目数量')
    sources = []
    for item in objects(payload.get('sources', []), 'sources'):
        path = source_path(item['source_path']) if item.get('source_path') else None
        source = {'filename': text(item.get('filename') or (Path(path).name if path else ''), 'filename', 500),
                  'kind': text(item.get('kind'), 'kind', 100), 'note': text(item.get('note'), 'note'),
                  'sha256': digest(item.get('sha256', item.get('source_sha256', '')), 'sha256')}
        provenance(item, source)
        if path:
            source['source_path'] = path
        if not path and not source.get('document_id'):
            raise ValueError('source 需要本地绝对 source_path 或服务端 document_id')
        if source.get('document_id') and not source.get('source_sha256'):
            raise ValueError('登记文档需要 source_sha256 绑定文件版本')
        if source.get('source_sha256'):
            source['sha256'] = source['source_sha256']
        # Retain the exact v1 path identity; registered sources have their own
        # stable namespace and cannot borrow a parser-supplied arbitrary ID.
        source['id'] = ('doc:' + source['document_id'] if source.get('document_id') else
                        hashlib.sha256(path.encode()).hexdigest()[:16])
        if source.get('source_id') and source['source_id'] != source['id']:
            raise ValueError('source_id 与来源身份不一致')
        if item.get('pages') is not None:
            source['pages'] = index(item['pages'], '页数')
        if any(old['id'] == source['id'] for old in sources):
            raise ValueError('sources 不可包含重复来源身份')
        sources.append(source)
    rows = []
    for row_index, incoming in enumerate(objects(payload.get('parts', []), 'parts')):
        level = incoming.get('item_level', 'unknown')
        if level not in LEVELS:
            raise ValueError('item_level 必须为 assembly/component/material/unknown')
        row = {key: text(incoming.get(key), key, 4000 if key in ('specification', 'material', 'notes') else 500) for key in
               ('name', 'material', 'category', 'finish', 'quantity_unit', 'quantity_basis', 'specification', 'source_file', 'source_reference', 'notes', 'parent_reference')}
        row['name'] = text(incoming.get('name'), 'name', 500, True)
        row['id'] = text(incoming.get('id') or f'ITEM-{row_index + 1:04d}', 'id', 200)
        row.update(item_level=level, quantity=numeric(incoming.get('quantity'), '数量'))
        if not isinstance(incoming.get('procurement_reference_only', False), bool):
            raise ValueError('procurement_reference_only 必须为布尔值')
        row['procurement_reference_only'] = incoming.get('procurement_reference_only', False)
        row['overall_dimensions'] = {key: numeric((incoming.get('overall_dimensions') or {}).get(key), key) for key in ('length_mm', 'width_mm', 'height_mm')}
        row['evidence'] = [bind_evidence(evidence(item), sources) for item in objects(incoming.get('evidence', []), 'evidence', 100)]
        row['review_questions'] = strings(incoming.get('review_questions'), 'review_questions')
        if row['quantity'] is None:
            row['review_questions'].append('数量未确认')
        if not row['quantity_unit'] and row['quantity'] is not None:
            row['review_questions'].append('数量单位未确认')
        row['review_questions'] = list(dict.fromkeys(row['review_questions']))
        row['work_scopes'] = []
        for scope in objects(incoming.get('work_scopes', []), 'work_scopes', 100):
            trade = text(scope.get('trade'), 'trade', 20, True)
            if trade not in TRADES:
                raise ValueError('工种不支持：' + trade)
            row['work_scopes'].append({'trade': trade, 'title': text(scope.get('title'), 'title', 1000, True),
                                       'basis': text(scope.get('basis'), 'basis'), 'status': 'suggested'})
        for key in ('length', 'width', 'thickness'):
            value = incoming.get(key + '_mm', incoming.get(key))
            row[key] = numeric(value, key) if level == 'component' else None
        rows.append(row)
    result = {'schema': SCHEMA, 'order_key': order_key, 'source_revision': revision, 'project': project,
            'version_note': text(payload.get('version_note'), 'version_note'), 'sources': sources,
            'issues': strings(payload.get('issues'), 'issues', 1000), 'parts': rows}
    if payload.get('project_id') is not None:
        result['project_id'] = identifier(payload['project_id'], 'project_id')
    if payload.get('expected_revision') is not None:
        result['expected_revision'] = index(payload['expected_revision'], 'expected_revision')
    return result


def parse(payload, filename):
    payload = normalise(payload)
    parts = []
    for row in payload['parts']:
        first = next(iter(row['evidence']), {})
        part = dict(row)
        part.update(unit='mm', review_status='pending', draft_only=True,
                    issues=list(row['review_questions']),
                    source={'file': filename, 'reference': row['source_reference'] or first.get('reference') or first.get('cell') or '',
                            'model_file': row['source_file'] or first.get('source_path') or first.get('file', ''),
                            'revision': payload['source_revision'], 'part_number': row['id']})
        for key in ('document_id', 'source_sha256', 'source_revision', 'locator', 'engine', 'model', 'observation_kind'):
            if key in first:
                part['source'][key] = first[key]
        parts.append(part)
    return {'parts': parts, 'geometry': [], 'warnings': payload['issues'], 'format': 'order_draft',
            'status': 'needs_review', 'order_draft': {key: value for key, value in payload.items() if key != 'parts'}}
