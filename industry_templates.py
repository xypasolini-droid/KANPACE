"""Bundled, review-required industry reference routes, with no customer data.

This catalog is based on the existing 2026-09-07 Quanzhou desk research. It is
not a claim that the named companies use these exact routes. Loading or
resolving a reference never installs a factory profile or writes production
records. Callers must use the normal draft/preview/review/install workflow.

The three legacy ``factory_type`` values are runtime compatibility mappings;
``industry_id`` and ``variant_id`` identify the actual business choice.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

CATALOG_VERSION = 1
CATALOG_PATH = Path(__file__).resolve().parent / 'config' / 'industry-templates.json'


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


@lru_cache(maxsize=1)
def _load():
    data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    if data.get('catalog_version') != CATALOG_VERSION:
        raise ValueError('行业模板目录版本不匹配')
    industries = data.get('industries', [])
    if len(industries) != 19 or len({item['id'] for item in industries}) != len(industries):
        raise ValueError('行业模板目录内容不完整')
    for industry in industries:
        variants = industry['variants']
        if not variants or len({item['id'] for item in variants}) != len(variants):
            raise ValueError('行业业务类型缺失或重复')
        for variant in variants:
            if variant.get('status') != 'reference' or not variant.get('requires_review'):
                raise ValueError('行业模板必须保持待工厂确认的参考状态')
            if not variant.get('sources'):
                raise ValueError('行业模板缺少来源')
    return data


def resolve(industry_id, variant_id=None):
    """Return a detached executable reference; unknown selectors raise ValueError."""
    industry = next((i for i in _load()['industries'] if i['id'] == industry_id), None)
    if industry is None:
        raise ValueError('行业不存在，请从行业目录选择')
    if variant_id is None:
        variant_id = industry['variants'][0]['id']
    raw = next((v for v in industry['variants'] if v['id'] == variant_id), None)
    if raw is None:
        raise ValueError('该行业没有此业务类型，请重新选择')
    result = deepcopy(raw)
    result['id'] = result['template_id']
    result['variant_name'] = raw['name']
    result['research_date'] = _load()['research_date']
    result['input'] = industry['input']
    result['family'] = industry['family']
    result['metrics'] = deepcopy(industry['metrics'])
    result['capability_note'] = industry['gap']
    result['content_hash'] = _digest(result)
    result['hash'] = result['content_hash']
    return result


def catalog():
    """List the 19 industries and their independently selectable business routes."""
    result = []
    for industry in _load()['industries']:
        summary = {key: deepcopy(value) for key, value in industry.items() if key != 'variants'}
        summary['catalog_version'] = CATALOG_VERSION
        summary['variants'] = []
        for variant in industry['variants']:
            reference = resolve(industry['id'], variant['id'])
            entry = {key: deepcopy(value) for key, value in reference.items() if key != 'nodes'}
            entry['id'] = variant['id']
            entry['node_count'] = len(reference['nodes'])
            summary['variants'].append(entry)
        result.append(summary)
    return result
