"""Conservative, read-only STEP-to-drawing OCR evidence matching.

This module does not infer a BOM, manufacturing dimensions, material, or work
order. It matches only a sufficiently specific CAD name or part number to a
single OCR text region. Nearby drawing dimensions are deliberately not joined.
"""
from __future__ import annotations

import math
import re
import unicodedata


_EFFECT_HINTS = ('效果', '渲染', '产品参考', '共用参考', 'render')
_GENERIC_NAMES = frozenset({
    '板', '板件', '板材', '木板', '侧板', '顶板', '底板', '背板', '门板', '层板',
    '玻璃', '五金', '零件', '构件', '模型', '实体', '装配体', 'part', 'panel',
    'body', 'solid', 'component', 'assembly', '未命名模型实例',
})
_GENERIC_KEYS = frozenset(re.sub(r'[\s\-_.·:：、，,;；]+', '', item.casefold()) for item in _GENERIC_NAMES)
_AUTO_NAME = re.compile(r'(?:part|panel|body|solid|component|assembly|零件|构件|实体|模型)[-_ .]*\d+', re.I)
_PART_CODE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{1,6}(?:[-_.]?\d{1,6}){1,3})(?![A-Za-z0-9])')
_DIMENSION = re.compile(
    r'(?<![\d.])\d+(?:\.\d+)?\s*(?:mm|cm|米|毫米)?\s*[×xX*]\s*'
    r'\d+(?:\.\d+)?\s*(?:mm|cm|米|毫米)?'
    r'(?:\s*[×xX*]\s*\d+(?:\.\d+)?\s*(?:mm|cm|米|毫米)?)?'
    r'(?![\d.])', re.I)
_SINGLE_DIMENSION = re.compile(r'(?<![\d.])\d+(?:\.\d+)?\s*(?:mm|cm|毫米)(?![A-Za-z])', re.I)
_LABEL_PREFIX = re.compile(r'^(?:构件名称|零件名称|构件|零件|件号|编号|图号|名称)\s*[:：]\s*')
_CODE_SEPARATOR = re.compile(r'[-_.\s]')
_LABEL_SEPARATOR = re.compile(r'[\s\-_.·:：、，,;；]+')
_MAX_CANDIDATE_LINKS = 20_000


def _nfkc(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def _name_key(value):
    return _LABEL_SEPARATOR.sub('', _nfkc(value).casefold())


def _code_key(value):
    return _CODE_SEPARATOR.sub('', _nfkc(value).casefold())


def is_effect_source(label):
    lower = _nfkc(label).casefold()
    return any(hint in lower for hint in _EFFECT_HINTS)


def _generic(value):
    name = _nfkc(value)
    key = _name_key(name)
    if not key or key in _GENERIC_KEYS or _AUTO_NAME.fullmatch(name):
        return True
    # Two Chinese characters without a drawing part number are usually a role
    # such as "侧板", not enough to join two separate sources safely.
    if len(key) <= 2 and all('\u3400' <= ch <= '\u9fff' for ch in key):
        return True
    return False


def _label_without_dimensions(value):
    text = _LABEL_PREFIX.sub('', _nfkc(value))
    text = _DIMENSION.sub(' ', text)
    text = _SINGLE_DIMENSION.sub(' ', text)
    return text.strip(' \t\r\n:：,，;；、-–—()（）[]【】')


def _part_code(value):
    match = _PART_CODE.search(_nfkc(value))
    return _code_key(match.group(1)) if match else None


def _code_only(value):
    text = _nfkc(value)
    return bool(_PART_CODE.fullmatch(text))


def _dimension_candidates(value):
    """Return literal annotations only; never label them L/W/T or cut sizes."""
    text = _nfkc(value)
    candidates = []
    for match in _DIMENSION.finditer(text):
        raw = match.group(0)
        numbers = [float(piece) for piece in re.findall(r'\d+(?:\.\d+)?', raw)]
        if len(numbers) not in (2, 3) or any(not math.isfinite(n) or n <= 0 for n in numbers):
            continue
        units = {token.casefold() for token in re.findall(r'(?i)mm|cm|毫米|米', raw)}
        unit = 'mm' if units and units <= {'mm', '毫米'} else 'cm' if units == {'cm'} else 'm' if units == {'米'} else 'unspecified'
        candidates.append({'raw': raw, 'values': numbers, 'unit': unit,
                           'meaning': 'OCR 尺寸文字候选，未验证尺寸方向、单位或加工含义'})
    return candidates


def _bbox(value):
    if not isinstance(value, list) or len(value) != 4 or any(
            isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0 for n in value):
        return None
    if value[2] < value[0] or value[3] < value[1]:
        return None
    return [float(n) for n in value]


def _regions(jobs):
    result = []
    for job in jobs:
        metadata = job.get('metadata') or {}
        source = job.get('source') or {}
        result_data = job.get('result') or {}
        label = str(metadata.get('source_label') or source.get('filename') or '')
        if is_effect_source(label) or is_effect_source(source.get('filename')):
            continue
        for page in result_data.get('pages', []):
            if not isinstance(page, dict) or type(page.get('page')) is not int:
                continue
            for index, region in enumerate(page.get('regions', [])):
                if not isinstance(region, dict):
                    continue
                text = region.get('text')
                if not isinstance(text, str) or not 1 <= len(text) <= 500:
                    continue
                bbox = _bbox(region.get('bbox'))
                if bbox is None:
                    continue
                score = region.get('score')
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                    score = None
                source_page = region.get('source_page', page.get('source_page', metadata.get('source_page', page['page'])))
                if type(source_page) is not int or source_page < 1:
                    source_page = page['page']
                item = {'job_id': job['id'], 'source_sha256': source.get('sha256'),
                        'source_file': label, 'page': page['page'], 'source_page': source_page,
                        'region_index': index, 'bbox': bbox,
                        'coordinate_system': region.get('coordinate_system') or 'pixels_top_left',
                        'text': text, 'score': score,
                        'dimension_candidates': _dimension_candidates(text)}
                if type(page.get('width')) is int and type(page.get('height')) is int \
                        and page['width'] > 0 and page['height'] > 0:
                    item['page_width'] = page['width']
                    item['page_height'] = page['height']
                pdf_bbox = _bbox(region.get('bbox_pdf_points'))
                if pdf_bbox is not None:
                    item['bbox_pdf_points'] = pdf_bbox
                item['_name_key'] = _name_key(_label_without_dimensions(text))
                item['_code_key'] = _part_code(text)
                result.append(item)
    return result


def _public_region(item, method):
    return {k: v for k, v in item.items() if not k.startswith('_')} | {'match_method': method}


def build(cad_snapshot, ocr_jobs):
    """Match one current STEP snapshot to already-current, project-scoped OCR jobs.

    The caller MUST validate project ownership and current registered source
    hashes for the STEP and every OCR job before invoking this pure function.
    """
    proposals = cad_snapshot.get('proposals')
    if not isinstance(proposals, list):
        raise ValueError('STEP 候选清单无效')
    regions = _regions(ocr_jobs)
    by_name = {}
    by_code = {}
    for item in regions:
        if item['_name_key']:
            by_name.setdefault(item['_name_key'], []).append(item)
        if item['_code_key']:
            by_code.setdefault(item['_code_key'], []).append(item)
    matches = []
    region_owners = {}
    candidate_links = 0
    for proposal in proposals:
        name = proposal.get('name')
        proposal_id = proposal.get('id')
        if not isinstance(name, str) or not isinstance(proposal_id, str):
            raise ValueError('STEP 候选标识无效')
        generic = _generic(name)
        name_key = _name_key(name)
        code = _part_code(name)
        code_only = _code_only(name)
        confirmed = []
        code_name_conflicts = []
        if not generic:
            name_candidates = by_name.get(name_key, [])
            code_candidates = by_code.get(code, [])
            candidate_links += len(name_candidates) + len(code_candidates)
            if candidate_links > _MAX_CANDIDATE_LINKS:
                raise ValueError('同名或同件号的工程图候选过多，请先按件号核对并清理重复 OCR 记录')
            candidates = { (item['job_id'], item['page'], item['region_index']): item
                           for item in name_candidates + code_candidates }
            for item in candidates.values():
                method = None
                if item['_name_key'] == name_key:
                    method = 'exact_normalized_name'
                elif code and item['_code_key'] == code:
                    if code_only:
                        method = 'exact_part_number'
                    else:
                        # A part number identifying a different part name is
                        # valuable conflict evidence, never a positive join.
                        code_name_conflicts.append(_public_region(item, 'part_number_name_conflict'))
                if method:
                    confirmed.append(_public_region(item, method))
                    region_owners.setdefault((item['job_id'], item['page'], item['region_index']), []).append(proposal_id)
        matches.append({'proposal_id': proposal_id, 'name': name, 'match_status': 'generic_name' if generic else 'unmatched',
                        'drawing_evidence': confirmed, 'conflicting_drawing_evidence': code_name_conflicts,
                        'issues': []})

    for item in matches:
        evidence = item['drawing_evidence']
        if item['match_status'] == 'generic_name':
            item['issues'].append('STEP 名称过于通用，不能据此自动关联施工图；请核对件号或重命名模型')
            continue
        if not evidence and not item['conflicting_drawing_evidence']:
            item['issues'].append('没有找到同名或同件号的工程图文字；请手工核对')
            continue
        if item['conflicting_drawing_evidence']:
            item['issues'].append('同一件号对应了不同名称，须人工核对图纸与模型版本')
        code_only = _code_only(item['name'])
        code_region_names = {_name_key(_label_without_dimensions(e['text'])) for e in evidence} if code_only else set()
        if len(code_region_names) > 1:
            item['issues'].append('同一件号在图纸中对应多个不同构件名称，无法判断是不同版本还是件号重复')
        ambiguous = any(len(region_owners[(e['job_id'], e['page'], e['region_index'])]) > 1 for e in evidence)
        if ambiguous:
            item['issues'].append('同一处图纸文字匹配多个 STEP 候选，无法自动确认构件身份')
        dimensions = {(tuple(dim['values']), dim['unit']) for e in evidence for dim in e['dimension_candidates']}
        if len(dimensions) > 1:
            item['issues'].append('匹配的图纸文字含不同尺寸注释；可能是不同规格、视图或版本')
        if any(e['dimension_candidates'] for e in evidence):
            item['issues'].append('尺寸是 OCR 原文候选，未确认长宽厚、单位和下料尺寸')
        if item['conflicting_drawing_evidence'] or len(dimensions) > 1 or len(code_region_names) > 1:
            item['match_status'] = 'conflict'
        elif ambiguous:
            item['match_status'] = 'ambiguous'
        elif evidence:
            item['match_status'] = 'matched'

    return {'project_id': cad_snapshot.get('project_id'), 'cad_job_id': cad_snapshot.get('job_id'),
            'cad_source_sha256': cad_snapshot.get('source_sha256'), 'status': 'evidence_only',
            'ocr_job_count': len(ocr_jobs), 'matches': matches,
            'warnings': ['只关联同项目、当前登记文件的 OCR 文字；图纸文字不是已确认制造参数',
                         '没有把相邻尺寸区域自动归属构件，也没有从图片推断材料、数量或工艺'],
            'manufacturing_release': False}
