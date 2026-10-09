"""Persist explicit mesh-to-BOM associations without manufacturing new BOM rows."""
from __future__ import annotations

import re
from datetime import datetime, timezone

MODEL_FORMATS = {'stl', 'obj', 'glb', 'step', 'stp', 'iges', 'igs', 'brep'}
UNITS = {'mm', 'cm', 'm', 'inch'}


def _document(store, con, document_id):
    doc = store.get(con, 'documents', document_id)
    if str(doc.get('format', '')).lower() not in MODEL_FORMATS:
        raise ValueError('请选择 STEP、IGES、BREP、GLB、OBJ 或 STL 模型')
    if doc.get('superseded'):
        raise ValueError('模型已有新版本，请打开当前版本重新关联')
    return doc


def get_links(store, con, document_id):
    doc = _document(store, con, document_id)
    active = {p['id']: p for p in store.active_parts(con, doc['project_id'])}
    links = {}
    for key, saved in doc.get('model_links', {}).items():
        part = active.get(saved.get('part_id'))
        links[key] = {**saved, 'stale': part is None or part.get('revision') != saved.get('part_revision')}
        if part is not None:
            links[key]['part_name'] = part.get('name', '')
    fmt = str(doc.get('format', '')).lower()
    fixed_unit = 'mm' if fmt in {'step', 'stp', 'iges', 'igs'} else 'm' if fmt == 'glb' else None
    return {'document_id': doc['id'], 'project_id': doc['project_id'], 'sha256': doc['sha256'],
            'unit': fixed_unit or doc.get('model_unit'), 'unit_fixed': bool(fixed_unit),
            'links': links}


def save_links(store, con, document_id, data):
    doc = _document(store, con, document_id)
    store.require_project_open(store.get(con, 'projects', doc['project_id']))
    if not isinstance(data, dict) or set(data) - {'mesh_key', 'part_id', 'unit'}:
        raise ValueError('模型关联字段无效')
    if ('mesh_key' in data) != ('part_id' in data):
        raise ValueError('模型零件标识与拆单项必须同时提供')
    if not data or not (('mesh_key' in data and 'part_id' in data) or 'unit' in data):
        raise ValueError('请选择模型零件与对应拆单项，或设置模型单位')
    changed = False
    if 'unit' in data:
        unit = data['unit']
        if not isinstance(unit, str) or unit not in UNITS:
            raise ValueError('模型单位须为 mm、cm、m 或 inch')
        fixed = get_links(store, con, document_id)
        if fixed['unit_fixed'] and unit != fixed['unit']:
            raise ValueError('该格式的单位由模型读取，不能手动改写')
        if doc.get('model_unit') != unit:
            doc['model_unit'] = unit
            changed = True
    if 'mesh_key' in data or 'part_id' in data:
        key = data.get('mesh_key')
        if not isinstance(key, str) or not re.fullmatch(r'mesh-(?:0|[1-9][0-9]{0,5})', key):
            raise ValueError('模型零件标识无效')
        part_id = data.get('part_id')
        links = dict(doc.get('model_links', {}))
        if part_id is None:
            changed = links.pop(key, None) is not None or changed
        else:
            if not isinstance(part_id, str):
                raise ValueError('请选择有效拆单项')
            active = {p['id']: p for p in store.active_parts(con, doc['project_id'])}
            part = active.get(part_id)
            if part is None:
                raise ValueError('拆单项必须属于当前项目且为当前版本')
            if len(links) >= 10000 and key not in links:
                raise ValueError('当前模型关联数量已达上限')
            previous = links.get(key, {})
            if previous.get('part_id') != part_id or previous.get('part_revision') != part.get('revision'):
                links[key] = {'part_id': part_id, 'part_name': part.get('name', ''),
                              'part_revision': part.get('revision'),
                              'source_part_number': part.get('source', {}).get('part_number', ''),
                              'linked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
                changed = True
        doc['model_links'] = links
    if changed:
        store.put(con, 'documents', doc)
        store.event(con, doc['project_id'], 'model_link_updated', '更新模型单位或零件与拆单关联：' + doc['filename'],
                    document_id=doc['id'], mesh_key=data.get('mesh_key'), part_id=data.get('part_id'), unit=data.get('unit'))
    return get_links(store, con, document_id)
