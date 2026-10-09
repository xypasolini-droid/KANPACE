"""Deterministic, review-only component candidates from a completed STEP job.

Model occurrences are evidence, not an order BOM. World-axis bounding boxes
must never be copied into manufacturing dimensions by this module.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata


_UNIT_ALIASES = {
    'mm': 'mm', 'millimeter': 'mm', 'millimeters': 'mm',
    'millimetre': 'mm', 'millimetres': 'mm',
    'cm': 'cm', 'centimeter': 'cm', 'centimeters': 'cm',
    'centimetre': 'cm', 'centimetres': 'cm',
    'm': 'm', 'meter': 'm', 'meters': 'm', 'metre': 'm', 'metres': 'm',
    'in': 'inch', 'inch': 'inch', 'inches': 'inch',
    'ft': 'foot', 'foot': 'foot', 'feet': 'foot',
    'um': 'micrometer', 'micrometer': 'micrometer',
    'micrometers': 'micrometer', 'micrometre': 'micrometer',
    'micrometres': 'micrometer',
}


def _source_units(value):
    """Expose only canonical, recognized source units; never guess mm."""
    if not isinstance(value, list) or len(value) > 16:
        return [], False
    normalized = []
    unknown = False
    for item in value:
        if not isinstance(item, str) or len(item) > 80:
            unknown = True
            continue
        token = unicodedata.normalize('NFKC', item).strip().casefold()
        token = re.sub(r'[\s._-]+', '', token)
        unit = _UNIT_ALIASES.get(token)
        if unit is None:
            unknown = True
        elif unit not in normalized:
            normalized.append(unit)
    return normalized, bool(normalized) and not unknown and len(normalized) == 1


def _name(value):
    text = unicodedata.normalize('NFKC', str(value or '').strip())
    # Truncating before grouping would silently merge two distinct part names
    # sharing a prefix. Reject unusually long labels instead of changing the
    # model's identity.
    text = re.sub(r'\s+', ' ', text) or '未命名模型实例'
    if len(text) > 500:
        raise ValueError('STEP 实例名称过长，无法可靠地分组')
    return text


def _dimension_sample(value):
    if not isinstance(value, list) or len(value) != 3:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not math.isfinite(item) or item <= 0 for item in value):
        return None
    return [round(float(item), 6) for item in value]


def _form_hint(value, index):
    """Keep only the kernel's bounded geometry label, never a process claim."""
    if not isinstance(value, dict) or value.get('kind') != 'thin_plate_shape' \
            or value.get('basis') != 'oriented_bbox' or value.get('review_required') is not True:
        return None
    ratio = value.get('thinness_ratio')
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) \
            or not math.isfinite(ratio) or not 0 < ratio <= 0.10:
        return None
    return {'instance_index': index, 'kind': 'thin_plate_shape',
            'thinness_ratio': round(float(ratio), 6), 'basis': 'oriented_bbox',
            'review_required': True}


def _assemblies_by_path(value):
    """Index only explicit XDE assembly occurrences, never inferred cabinet names."""
    if value is None:
        return {}
    if not isinstance(value, list) or len(value) > 5000:
        raise ValueError('STEP 上级装配清单无效或超过安全范围')
    nodes = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('STEP 上级装配记录无效')
        path, definition = item.get('instance_path'), item.get('definition_id')
        if not isinstance(path, str) or not path or len(path) > 500 or path in nodes \
                or not isinstance(definition, str) or not definition or len(definition) > 120:
            raise ValueError('STEP 上级装配定义或路径无效')
        raw_name = item.get('name')
        nodes[path] = {'instance_path': path, 'definition_id': definition,
                       'name': _name(raw_name) if raw_name else None}
    return nodes


def _assembly_context(path, index, nodes):
    """Relate a part to exact path prefixes; same labels alone are not evidence."""
    segments = path.split('/')
    prefixes = ['/'.join(segments[:length]) for length in range(1, len(segments))]
    ancestors = [nodes[prefix] for prefix in prefixes if prefix in nodes]
    return {'instance_index': index, 'instance_path': path,
            'ancestors': ancestors,
            'nearest_parent': nodes.get(prefixes[-1]) if prefixes else None,
            'unresolved_parent_paths': [prefix for prefix in prefixes if prefix not in nodes]}


def build(job):
    """Return reproducible groups without any guessed manufacturing fields."""
    if not isinstance(job, dict) or job.get('kind') != 'cad' or job.get('status') != 'completed':
        raise ValueError('仅能从处理完成的 STEP 模型生成待核对构件建议')
    source = job.get('source') or {}
    source_sha = source.get('sha256')
    if not isinstance(source_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha):
        raise ValueError('STEP 来源指纹无效')
    result = job.get('result') or {}
    if result.get('format') != 'STEP' or result.get('output_length_unit') != 'mm':
        raise ValueError('STEP 单位或格式未完成校验')
    source_units, units_confirmed = _source_units(result.get('source_length_units'))
    instances = result.get('parts')
    if not isinstance(instances, list) or not 1 <= len(instances) <= 5000:
        raise ValueError('STEP 实例清单为空或超过安全范围')
    assembly_nodes = _assemblies_by_path(result.get('assemblies'))
    grouped = {}
    paths = set()
    for index, instance in enumerate(instances):
        if not isinstance(instance, dict):
            raise ValueError('STEP 实例记录无效')
        definition = instance.get('definition_id')
        path = instance.get('instance_path')
        if not isinstance(definition, str) or not definition or len(definition) > 120 \
                or not isinstance(path, str) or not path or len(path) > 500 or path in paths:
            raise ValueError('STEP 实例定义或路径无效')
        paths.add(path)
        display_name = _name(instance.get('name'))
        canonical_name = display_name.casefold()
        key = (definition, canonical_name)
        group = grouped.setdefault(key, {'name': display_name, 'definition_id': definition,
                                         'instance_indices': [], 'instance_paths': [],
                                         '_assembly_contexts': [],
                                         'geometry_valid': True, '_samples': [],
                                         '_oriented_samples': [], '_form_hints': [],
                                         '_form_hint_count': 0})
        group['instance_indices'].append(index)
        group['instance_paths'].append(path)
        group['_assembly_contexts'].append(_assembly_context(path, index, assembly_nodes))
        group['geometry_valid'] &= instance.get('valid') is True and type(instance.get('solid_count')) is int and instance['solid_count'] > 0
        sample = _dimension_sample(instance.get('bbox_extents_mm'))
        if sample is not None and sample not in group['_samples'] and len(group['_samples']) < 4:
            group['_samples'].append(sample)
        oriented = _dimension_sample(instance.get('oriented_bbox_extents_mm'))
        if oriented is not None and oriented not in group['_oriented_samples'] \
                and len(group['_oriented_samples']) < 4:
            group['_oriented_samples'].append(oriented)
        hint = _form_hint(instance.get('geometry_form_candidate'), index)
        if hint is not None:
            group['_form_hint_count'] += 1
            if len(group['_form_hints']) < 4:
                group['_form_hints'].append(hint)
    proposals = []
    for (definition, canonical_name), group in grouped.items():
        candidate_id = 'sp_' + hashlib.sha256((source_sha + '\x1f' + definition + '\x1f' + canonical_name).encode()).hexdigest()[:16]
        issues = ['模型实例数只是数量建议，请核对订单件数',
                  '模型外包尺寸不是加工或下料尺寸，请按施工图填写']
        if not units_confirmed:
            issues.append('STEP 源长度单位未能明确识别；几何尺寸仅供核对，不可作为施工尺寸')
        if not group['geometry_valid']:
            issues.append('部分模型实例不是有效实体，须核对装配结构')
        if len(group['_samples']) > 1:
            issues.append('同组实例的轴向外包尺寸不同，可能存在旋转或变体')
        if len(group['_oriented_samples']) > 1:
            issues.append('同组实例的定向外包参考值不同，请核对是否为不同规格')
        if group['_form_hint_count']:
            issues.append('薄板形态仅供几何核对，不代表板材、工艺或加工尺寸')
        parent_paths = {context['nearest_parent']['instance_path']
                        for context in group['_assembly_contexts'] if context['nearest_parent']}
        if len(parent_paths) > 1:
            issues.append('同名同定义实例跨多个上级装配；合并数量仅供核对，须按实际柜组确认归属')
        if any(context['unresolved_parent_paths'] for context in group['_assembly_contexts']):
            issues.append('部分实例路径缺少上级装配记录，请对照原模型核对归属')
        proposals.append({'id': candidate_id, 'name': group['name'], 'definition_id': definition,
                          'instance_indices': group['instance_indices'],
                          'instance_paths': group['instance_paths'],
                          'assembly_contexts': group['_assembly_contexts'],
                          'suggested_quantity': len(group['instance_indices']),
                          'bbox_extents_mm_sample': group['_samples'][0] if group['_samples'] else None,
                          'bbox_extents_mm_samples': group['_samples'],
                          'bbox_meaning': '世界坐标轴外包尺寸，仅用于核对模型，不是加工或下料尺寸',
                          'oriented_bbox_extents_mm_sample': group['_oriented_samples'][0] if group['_oriented_samples'] else None,
                          'oriented_bbox_extents_mm_samples': group['_oriented_samples'],
                          'oriented_bbox_meaning': '模型定向外包短/中/长边，仅供核对；不是已确认长宽厚或下料尺寸',
                          'geometry_form_candidates': group['_form_hints'],
                          'geometry_form_candidate_count': group['_form_hint_count'],
                          'geometry_valid': group['geometry_valid'], 'material': None,
                          'category': None, 'manufacturing_dimensions': None,
                          'review_status': 'pending', 'issues': issues})
    proposals.sort(key=lambda item: (item['name'].casefold(), item['definition_id'], item['id']))
    warnings = ['只按 STEP 定义与实例名称组织候选，不推断材料、工艺或制造尺寸',
                '同定义但名称不同的实例分别列出，技术员须判断是否为左右件或不同做法',
                '上级装配仅保留模型原有名称与实例路径；同候选跨装配时须人工确认柜组归属']
    if not units_confirmed:
        warnings.append('STEP 源长度单位未能明确识别或存在冲突；仍可依施工图人工填写加工尺寸')
    return {'project_id': job.get('metadata', {}).get('project_id'), 'job_id': job.get('id'),
            'source_sha256': source_sha, 'status': 'needs_review', 'proposals': proposals,
            'source_length_units': source_units, 'units_confirmed': units_confirmed,
            'warnings': warnings,
            'manufacturing_release': False}


def selected(snapshot, proposal_id, indices):
    """Return a canonical candidate, rejecting invented or partial client groups."""
    if not isinstance(proposal_id, str) or not isinstance(indices, list) \
            or not indices or any(type(index) is not int for index in indices):
        raise ValueError('请选择一组完整的 STEP 构件候选')
    proposal = next((item for item in snapshot['proposals'] if item['id'] == proposal_id), None)
    if proposal is None or indices != proposal['instance_indices']:
        raise ValueError('模型实例范围与当前 STEP 候选不一致，请重新核对')
    return proposal
