"""Import a teammate's *results* ZIP as project-scoped, review-only evidence.

This deliberately does not execute code from the archive, read arbitrary archive
paths, or turn a draft outline into a bill of materials or production task. The
supplied archive has no generator source or original MAX file, so the internal
hash chain can be checked but the original model cannot be reauthenticated here.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import io
import json
import ntpath
import re
import shutil
import stat
import struct
import zipfile
import xml.etree.ElementTree as ET
import zlib

from kanpace.core.errors import APIError
from kanpace.core.validation import now, uid


MAX_ARCHIVE = 12 * 1024 * 1024
MAX_MEMBERS = 250
MAX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_MEMBER = 12 * 1024 * 1024
MAX_MESH_JSON = 20 * 1024 * 1024
HEX_SHA = re.compile(r'^[0-9a-f]{64}$')
SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,60}$')
PACKAGE_ID = re.compile(r'^dpr_[0-9a-f]{12}$')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
ASSETS = {'preview': ('preview.png', 'image/png'),
          'dxf': ('drawing.dxf', 'application/octet-stream'),
          'svg': ('drawing.svg', 'application/octet-stream')}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(data, name):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('重复字段：' + key)
            result[key] = value
        return result

    try:
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_keys,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise APIError(422, name + ' 不是有效 JSON') from exc
    if not isinstance(value, dict):
        raise APIError(422, name + ' 必须是 JSON 对象')
    return value


def _sha(value, label):
    if not isinstance(value, str) or not HEX_SHA.fullmatch(value):
        raise APIError(422, label + ' 缺少合法的 SHA-256')
    return value


def _require_equal(actual, expected, label):
    if actual != expected:
        raise APIError(422, label + ' 与归档来源指纹不一致')


def _gzip_json(data, name):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            expanded = stream.read(MAX_MESH_JSON + 1)
        if len(expanded) > MAX_MESH_JSON:
            raise APIError(413, name + ' 展开后超过安全限制')
        return _json(expanded, name)
    except (OSError, EOFError, ValueError) as exc:
        raise APIError(422, name + ' 解压失败') from exc


def _archive_entries(archive):
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise APIError(413, '出图包文件数量超过安全限制')
    total = 0
    names = {}
    for info in infos:
        name = info.filename
        components = name.rstrip('/').split('/')
        if (not name or len(name) > 700 or name.startswith('/') or '\\' in name
                or any(c in ('', '.', '..') or len(c) > 240 for c in components)
                or ':' in components[0] or any(ord(c) < 32 for c in name)):
            raise APIError(422, '出图包含非法成员路径')
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise APIError(422, '出图包含不支持的加密或压缩成员')
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise APIError(422, '出图包含链接或特殊文件')
        if info.is_dir():
            continue
        if name.lower().endswith(('.max', '.exe', '.dll', '.pyd', '.so', '.dylib')):
            raise APIError(422, '出图结果包不能包含原生模型或可执行程序')
        if name in names:
            raise APIError(422, '出图包有重名成员')
        if info.file_size > MAX_MEMBER or (info.compress_size and info.file_size > info.compress_size * 500):
            raise APIError(413, '出图包成员超过安全限制')
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise APIError(413, '出图包展开后超过安全限制')
        names[name] = info
    return names


def _read(archive, names, name, limit):
    info = names.get(name)
    if info is None:
        raise APIError(422, '出图包缺少 ' + name.split('/')[-1])
    if info.file_size > limit:
        raise APIError(413, name.split('/')[-1] + ' 超过安全限制')
    try:
        data = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise APIError(422, '出图包文件损坏：' + name.split('/')[-1]) from exc
    if len(data) != info.file_size:
        raise APIError(422, '出图包成员长度不符')
    return data


def _validate_png(data):
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b'IHDR':
        raise APIError(422, '预览 PNG 无效')
    width, height = struct.unpack('>II', data[16:24])
    if not 1 <= width <= 10000 or not 1 <= height <= 10000 or width * height > 25_000_000:
        raise APIError(422, '预览 PNG 尺寸无效')
    offset, chunks, ended = 8, 0, False
    while offset + 12 <= len(data) and chunks < 10_000:
        length = struct.unpack('>I', data[offset:offset+4])[0]
        end = offset + length + 12
        if end > len(data):
            break
        kind = data[offset+4:offset+8]
        expected = struct.unpack('>I', data[end-4:end])[0]
        if (zlib.crc32(data[offset+4:end-4]) & 0xffffffff) != expected:
            break
        offset, chunks = end, chunks + 1
        if kind == b'IEND':
            ended = True
            break
    if not ended or offset != len(data):
        raise APIError(422, '预览 PNG 文件损坏')
    return {'width': width, 'height': height}


def _validate_svg(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise APIError(422, 'SVG 含不支持的外部声明')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise APIError(422, 'SVG 图纸无效') from exc
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        raise APIError(422, 'SVG 图纸根节点无效')
    allowed = {'svg', 'g', 'defs', 'line', 'rect', 'path', 'polyline', 'polygon',
               'circle', 'ellipse', 'text', 'tspan', 'marker'}
    for elem in root.iter():
        if elem.tag.split('}')[-1] not in allowed:
            raise APIError(422, 'SVG 含不支持的可执行或外部内容')
        if any(k.lower().startswith('on') or k.split('}')[-1] in ('href', 'src')
               or 'url(' in str(v).lower() for k, v in elem.attrib.items()):
            raise APIError(422, 'SVG 含不支持的链接或脚本')


def _validate_selection(selection, catalog):
    if selection.get('schema') != 'kanpace.round1-selection.v1':
        raise APIError(422, '选择记录版本不支持')
    candidates = catalog.get('items')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
        raise APIError(422, '候选清单无效')
    known = {}
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not SAFE_ID.fullmatch(item['id']):
            raise APIError(422, '候选编号无效')
        ids = item.get('node_ids')
        if item['id'] in known or not isinstance(ids, list) or not ids or len(ids) > 1000 \
                or any(not isinstance(x, str) or not x.isascii() or not x.isdigit() for x in ids) or len(set(ids)) != len(ids):
            raise APIError(422, '候选对象范围无效')
        known[item['id']] = item
    selected = selection.get('items')
    if not isinstance(selected, list) or not 1 <= len(selected) <= len(known):
        raise APIError(422, '选柜记录无效')
    used = set()
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) \
                or item['id'] not in known or item['id'] in used:
            raise APIError(422, '选柜编号不属于候选清单')
        used.add(item['id'])
        ids = item.get('node_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) \
                or len(set(ids)) != len(ids) \
                or not set(ids).issubset(known[item['id']]['node_ids']):
            raise APIError(422, '选柜对象超出候选范围')
        if type(item.get('quantity')) is not int or not 1 <= item['quantity'] <= 999:
            raise APIError(422, '选柜数量无效')
        if item.get('scope_confirmed') is not True or item.get('orientation_confirmed') is not True \
                or type(item.get('rotation_z_degrees')) is not int \
                or item['rotation_z_degrees'] not in (0, 90, 180, 270):
            raise APIError(422, '选柜范围或正面尚未确认')
        if item.get('dimension_basis') not in ('model_only', 'verified_order_site'):
            raise APIError(422, '尺寸依据无效')
        if item['dimension_basis'] == 'verified_order_site':
            dims = item.get('expected_dimensions_mm')
            if not isinstance(dims, dict) or any(type(dims.get(k)) not in (int, float)
                or not 0 < dims[k] < 1e7 for k in ('width', 'depth', 'height')) \
                    or not isinstance(item.get('dimension_evidence'), str) or not item['dimension_evidence'].strip():
                raise APIError(422, '实物尺寸依据不完整')
    return known, {item['id']: item for item in selected}


def prepare(data):
    """Validate the entire untrusted package before opening a write transaction."""
    filename = data.get('filename')
    if not isinstance(filename, str) or not filename.lower().endswith('.zip') \
            or '/' in filename or '\\' in filename or len(filename) > 180 \
            or any(ord(c) < 32 for c in filename):
        raise APIError(400, '请上传 ZIP 出图结果包')
    encoded = data.get('content_base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_ARCHIVE * 4 // 3 + 8):
        raise APIError(413, '出图包不能超过 12 MB')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise APIError(400, '出图包不是有效 Base64') from exc
    if not raw or len(raw) > MAX_ARCHIVE:
        raise APIError(413, '出图包不能超过 12 MB')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise APIError(422, '出图包不是有效 ZIP') from exc
    with archive:
        names = _archive_entries(archive)
        try:
            damaged = archive.testzip()
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise APIError(422, '出图包校验失败') from exc
        if damaged:
            raise APIError(422, '出图包成员校验失败')
        catalogs = [name for name in names if name.endswith('/catalog.json')]
        if len(catalogs) != 1:
            raise APIError(422, '出图包应有且仅有一份候选清单')
        base = catalogs[0][:-len('catalog.json')]
        catalog_data = _read(archive, names, base + 'catalog.json', 1024 * 1024)
        catalog = _json(catalog_data, 'catalog.json')
        if catalog.get('schema') != 'kanpace.scope-catalog.v1':
            raise APIError(422, '候选清单版本不支持')
        source_sha = _sha(catalog.get('source_sha256'), '原模型')
        claimed_name = ntpath.basename(str(catalog.get('source') or ''))[:180]
        index_sha = _sha(catalog.get('index_sha256'), '场景索引')
        indexed = [name for name in names if name.endswith('/scene_index.json')
                   and _digest(_read(archive, names, name, 3 * 1024 * 1024)) == index_sha]
        if len(indexed) != 1:
            raise APIError(422, '出图包没有与候选清单匹配的场景索引')
        scene_data = _read(archive, names, indexed[0], 3 * 1024 * 1024)
        scene = _json(scene_data, 'scene_index.json')
        if scene.get('schema') != 'kanpace.scene-index.v1':
            raise APIError(422, '场景索引版本不支持')
        _require_equal(scene.get('source_sha256'), source_sha, '场景索引原模型')
        native_scene = _json(_read(archive, names, base + 'native/scene_index.json', 3 * 1024 * 1024),
                             '提取场景索引')
        if native_scene.get('schema') != 'kanpace.scene-index.v1':
            raise APIError(422, '提取场景索引版本不支持')
        _require_equal(native_scene.get('source_sha256'), source_sha, '提取场景索引原模型')
        bundle_data = _read(archive, names, base + 'native/geometry.json.gz', 5 * 1024 * 1024)
        bundle_sha = _digest(bundle_data)
        bundle = _gzip_json(bundle_data, 'geometry.json.gz')
        if bundle.get('schema') != 'kanpace.mesh-bundle.v1' or bundle.get('units') != 'mm' \
                or bundle.get('origin') != 'native_max':
            raise APIError(422, '几何包版本、单位或来源不支持')
        _require_equal((bundle.get('source') or {}).get('sha256'), source_sha, '几何包原模型')
        mesh_count = len(bundle.get('meshes', [])) if isinstance(bundle.get('meshes'), list) else 0
        if not 1 <= mesh_count <= 10000:
            raise APIError(422, '几何包没有有效对象')
        native = _json(_read(archive, names, base + 'native/job_status.json', 256 * 1024), 'job_status.json')
        if native.get('success') is not True or native.get('source_unchanged') is not True:
            raise APIError(422, '原生提取任务未成功')
        _require_equal(native.get('source_sha256'), source_sha, '原生任务原模型')
        _require_equal(native.get('geometry_sha256'), bundle_sha, '原生任务几何包')
        native_result = native.get('native_result') or {}
        if (native_result.get('mesh_count') is not None and native_result['mesh_count'] != mesh_count) \
                or (native_result.get('node_count') is not None and native_result['node_count'] != len(scene.get('nodes', []))):
            raise APIError(422, '原生任务对象数量与场景/几何包不符')
        visual = _json(_read(archive, names, base + 'visual-data.json', 10 * 1024 * 1024), 'visual-data.json')
        for key, expected in (('source_sha256', source_sha), ('catalog_sha256', _digest(catalog_data)),
                              ('bundle_sha256', bundle_sha)):
            _require_equal(visual.get(key), expected, '预览清单 ' + key)
        selection = _json(_read(archive, names, base + 'user-selection-001.json', 256 * 1024), 'user-selection-001.json')
        for key, expected in (('source_sha256', source_sha), ('catalog_sha256', _digest(catalog_data)),
                              ('bundle_sha256', bundle_sha)):
            _require_equal(selection.get(key), expected, '选柜记录 ' + key)
        known, chosen = _validate_selection(selection, catalog)
        drafts = []
        for name in names:
            if not name.endswith('/review_manifest.json'):
                continue
            manifest = _json(_read(archive, names, name, 256 * 1024), 'review_manifest.json')
            candidate_id = manifest.get('project')
            if candidate_id not in chosen:
                continue
            folder = name[:-len('review_manifest.json')]
            if manifest.get('schema') != 'kanpace.review-manifest.v1' \
                    or manifest.get('release_status') != 'blocked':
                raise APIError(422, '草稿核对状态无效')
            draft_sha = _sha((manifest.get('evidence') or {}).get('bundle_sha256'), '草稿几何包')
            matches = [member for member in names if member.endswith('/geometry.json.gz')
                       and _digest(_read(archive, names, member, 5 * 1024 * 1024)) == draft_sha]
            if len(matches) != 1:
                raise APIError(422, '草稿预览缺少匹配的几何依据')
            draft_bundle = _gzip_json(_read(archive, names, matches[0], 5 * 1024 * 1024), '草稿几何包')
            _require_equal((draft_bundle.get('source') or {}).get('sha256'), source_sha, '草稿原模型')
            draft_meshes = draft_bundle.get('meshes')
            if not isinstance(draft_meshes, list) or \
                    {m.get('id') for m in draft_meshes if isinstance(m, dict)} != set(chosen[candidate_id]['node_ids']):
                raise APIError(422, '草稿对象范围与选柜记录不一致')
            validation = _json(_read(archive, names, folder + 'validation.json', 256 * 1024), 'validation.json')
            _require_equal(validation.get('input_bundle_sha256'), draft_sha, '草稿校验几何包')
            if validation.get('status') != 'draft_only':
                raise APIError(422, '草稿必须标明仅供核对')
            png = _read(archive, names, folder + 'preview.png', 2 * 1024 * 1024)
            size = _validate_png(png)
            svg = _read(archive, names, folder + 'drawing.svg', 2 * 1024 * 1024)
            _validate_svg(svg)
            dxf = _read(archive, names, folder + 'drawing.dxf', 2 * 1024 * 1024)
            if not dxf.strip().endswith(b'EOF'):
                raise APIError(422, 'DXF 图纸缺少结束标记')
            drafts.append({'candidate_id': candidate_id, 'size': size,
                           'dimensions_mm': (manifest.get('evidence') or {}).get('dimensions_mm'),
                           'assets': {'preview': png, 'svg': svg, 'dxf': dxf}})
        if len(drafts) > 1:
            raise APIError(422, '当前版本每个出图包仅支持一张外形核对草稿')
        coverage = str(catalog.get('coverage') or '')[:300]
        candidates = []
        for item in known.values():
            selection_item = chosen.get(item['id'])
            label = str(item.get('name') or item['id'])[:100]
            candidates.append({'id': item['id'], 'label': label, 'kind': str(item.get('kind') or '')[:60],
                               'object_count': len(item['node_ids']), 'selected': bool(selection_item),
                               'quantity': selection_item.get('quantity') if selection_item else None,
                               'rotation_z_degrees': selection_item.get('rotation_z_degrees') if selection_item else None,
                               'dimension_basis': selection_item.get('dimension_basis') if selection_item else None,
                               'confirmed': bool(selection_item and selection_item['scope_confirmed'] and selection_item['orientation_confirmed']),
                               'engineering_approved': False,
                               'scope_ids': list(selection_item['node_ids']) if selection_item else []})
        return {'filename': filename, 'archive_sha256': _digest(raw), 'source_sha256': source_sha,
                'claimed_model_filename': claimed_name,
                'index_sha256': index_sha, 'catalog_sha256': _digest(catalog_data),
                'bundle_sha256': bundle_sha, 'units': 'mm', 'units_confirmed': bundle.get('units_confirmed') is True,
                'mesh_count': mesh_count, 'candidate_count': len(candidates), 'coverage': coverage,
                'candidates': candidates, 'drafts': drafts,
                'catalog': {'schema':catalog['schema'], 'source_sha256':source_sha,
                            'index_sha256':index_sha, 'coverage':coverage,
                            'items':[{'id':item['id'], 'name':str(item.get('name') or item['id'])[:100],
                                      'kind':str(item.get('kind') or '')[:60], 'node_ids':item['node_ids']}
                                     for item in known.values()]},
                'selection': selection}


def _package_root(store, project_id, package_id):
    if not PACKAGE_ID.fullmatch(package_id):
        raise APIError(404, '核对包不存在')
    root = store.data_dir / 'drawing-pipeline-review'
    project_folder = root / hashlib.sha256(project_id.encode()).hexdigest()
    path = project_folder / package_id
    if any(p.is_symlink() for p in (root, project_folder, path)):
        raise APIError(404, '核对包不存在')
    if not path.resolve().is_relative_to(store.data_dir.resolve()):
        raise APIError(404, '核对包不存在')
    return path


def _source_link(store, con, project_id, source_sha):
    """A matching assertion needs the actual registered MAX bytes in this factory."""
    for doc in store.all(con, 'documents', project_id):
        if doc.get('superseded') or doc.get('demo') or not str(doc.get('filename', '')).lower().endswith('.max') \
                or doc.get('sha256') != source_sha:
            continue
        name = doc.get('storage_name')
        if not isinstance(name, str) or not name or '/' in name or '\\' in name:
            continue
        path = store.uploads / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve():
            continue
        try:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == source_sha:
                    return doc['id']
        except OSError:
            continue
    return None


def _snapshot(project_id, record, source_document_id=None):
    empty = {'project_id': project_id, 'status': 'empty', 'source': None,
             'candidates': [], 'outputs': [], 'warnings': [], 'review_only': True,
             'manufacturing_release': False, 'can_dispatch': False,
             'source_linked': False, 'source_match': False}
    if not record:
        return empty
    base = f'/api/projects/{project_id}/drawing-pipeline/assets/{record["id"]}'
    drafts = {d['candidate_id']: d for d in record['drafts']}
    candidates = [dict(c, preview_url=(base + '/preview') if c['id'] in drafts else None)
                  for c in record['candidates']]
    outputs = []
    for draft in record['drafts']:
        candidate = next(c for c in record['candidates'] if c['id'] == draft['candidate_id'])
        outputs.append({'id': draft['candidate_id'],
                        'label': draft['candidate_id'] + ' 早期外形核对草稿',
                        'preview_url': base + '/preview', 'dxf_url': base + '/dxf',
                        'svg_url': base + '/svg', 'scope_ids': candidate['scope_ids'],
                        'dimensions_mm': draft.get('dimensions_mm'), 'review_only': True})
    source_linked = bool(source_document_id)
    warnings = [('本项目没有 SHA-256 相同的原始 MAX 文件；这份重庆出图包只是未关联来源的参考资料，不能视为本项目工程依据。'
                 if not source_linked else '本项目原始 MAX 与出图包的来源 SHA-256 一致；仍须核对模型版本和工程设计。'),
                '出图包没有生成器源码；仅校验归档内部哈希链，不能在本机重新运行原生提取。',
                '候选只覆盖原模型的局部展示布置；清单中的几何对象不是制造零件或订单数量。',
                '图纸是较早的外形核对草稿；尺寸、结构、材料和工艺须由工程师按原件复核，不能用于下料或派工。']
    if not record['units_confirmed']:
        warnings.append('模型已换算为毫米，但实际下单尺寸和单位尚未完成实物核对。')
    return {'project_id': project_id, 'status': 'review_only',
            'source': {'id': record['id'], 'archive_filename': record['filename'],
                       'archive_sha256': record['archive_sha256'],
                       'model_sha256': record['source_sha256'],
                       'claimed_model_filename': record.get('claimed_model_filename', ''),
                       'model_file_present': source_linked, 'source_linked': source_linked,
                       'source_match': source_linked, 'source_document_id': source_document_id,
                       'catalog_sha256': record['catalog_sha256'], 'bundle_sha256': record['bundle_sha256'],
                       'units': record['units'], 'units_confirmed': record['units_confirmed'],
                       'candidate_count': record['candidate_count'], 'mesh_count': record['mesh_count'],
                       'coverage': record['coverage'], 'project_revision': record['project_revision'],
                       'imported_at': record['imported_at']},
            'candidates': candidates, 'outputs': outputs, 'warnings': warnings,
            'review_only': True, 'manufacturing_release': False, 'can_dispatch': False,
            'source_linked': source_linked, 'source_match': source_linked}


def get(store, con, project_id):
    store.get(con, 'projects', project_id)
    records = store.all(con, 'drawing_pipeline_reviews', project_id)
    latest = records[-1] if records else None
    return _snapshot(project_id, latest,
                     _source_link(store, con, project_id, latest['source_sha256']) if latest else None)


def save(store, con, project_id, data, prepared=None):
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    if type(data.get('expected_revision')) is not int or data['expected_revision'] != project['revision']:
        raise APIError(409, '项目工程版本已变化，请刷新后重新上传核对包')
    prepared = prepared or prepare(data)
    existing = store.all(con, 'drawing_pipeline_reviews', project_id)
    duplicate = next((r for r in existing if r['archive_sha256'] == prepared['archive_sha256']), None)
    if duplicate:
        return _snapshot(project_id, duplicate, _source_link(store, con, project_id, duplicate['source_sha256'])), False
    record_id = uid('dpr')
    if not PACKAGE_ID.fullmatch(record_id):
        # uid() currently uses 12 hex characters; guard any future change.
        raise APIError(500, '核对包编号生成失败')
    root = _package_root(store, project_id, record_id)
    for directory in (root.parent.parent, root.parent):
        directory.mkdir(exist_ok=True, mode=0o700)
        if directory.is_symlink():
            raise APIError(409, '核对包存储目录不可用')
        directory.chmod(0o700)
    root.mkdir(exist_ok=False, mode=0o700)
    try:
        draft_meta = []
        for draft in prepared['drafts']:
            for name, content in draft['assets'].items():
                target = root / ASSETS[name][0]
                target.write_bytes(content)
                target.chmod(0o600)
            draft_meta.append({k:v for k,v in draft.items() if k != 'assets'})
        for name, value in (('catalog.json', prepared['catalog']), ('selection.json', prepared['selection'])):
            target = root / name
            target.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            target.chmod(0o600)
        record = {'id': record_id, 'project_id': project_id, 'project_revision': project['revision'],
                  'imported_at': now(), 'filename': prepared['filename'],
                  'archive_sha256': prepared['archive_sha256'], 'source_sha256': prepared['source_sha256'],
                  'claimed_model_filename': prepared['claimed_model_filename'],
                  'index_sha256': prepared['index_sha256'], 'catalog_sha256': prepared['catalog_sha256'],
                  'bundle_sha256': prepared['bundle_sha256'], 'units': prepared['units'],
                  'units_confirmed': prepared['units_confirmed'], 'mesh_count': prepared['mesh_count'],
                  'candidate_count': prepared['candidate_count'], 'coverage': prepared['coverage'],
                  'candidates': prepared['candidates'], 'drafts': draft_meta,
                  'review_only': True, 'manufacturing_release': False}
        store.put(con, 'drawing_pipeline_reviews', record)
        store.event(con, project_id, 'drawing_pipeline_review_imported',
                    '导入外形核对包；仅供工程复核，不生成生产任务',
                    package_id=record_id, archive_sha256=prepared['archive_sha256'],
                    source_sha256=prepared['source_sha256'])
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return _snapshot(project_id, record, _source_link(store, con, project_id, record['source_sha256'])), True


def asset(store, con, project_id, package_id, kind):
    store.get(con, 'projects', project_id)
    if kind not in ASSETS:
        raise APIError(404, '核对包资源不存在')
    record = store.get(con, 'drawing_pipeline_reviews', package_id)
    if record.get('project_id') != project_id or not record.get('drafts'):
        raise APIError(404, '核对包资源不存在')
    path = _package_root(store, project_id, package_id) / ASSETS[kind][0]
    if path.is_symlink() or not path.is_file():
        raise APIError(404, '核对包资源不存在')
    return path.read_bytes(), ASSETS[kind][1], ASSETS[kind][0]
