"""Unified, persistent document observations. Never creates manufacturing facts.

Only registered factory sources cross this boundary. The child process receives
immutable copies, checkpoints each document, and writes reviewable observations.
No models are downloaded, no client paths/URLs are accepted, and business SQLite
records are not modified by recognition. Optional model availability is honest.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import importlib.util
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import posixpath
import xml.etree.ElementTree as ET
import base64
import urllib.request
import urllib.error
from urllib.parse import urlsplit

from kanpace.core.errors import APIError
from kanpace.core.validation import now

JOB_RE = re.compile(r'rec_[0-9a-f]{32}')
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_REGIONS = 20000
MAX_TEXT_BYTES = 20 * 1024 * 1024
_LOCK = threading.RLock()
_LIVE = {}
_CAP_CACHE = {}
_NATIVE_CACHE = {}


class RecognitionError(APIError):
    pass


def _atomic(path, value):
    target = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with target.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(target, path)


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _inside(path, root):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise RecognitionError(409, '识别资料路径不安全')
    return path.resolve()


def _directory(store):
    return _inside(store.data_dir / 'recognition-jobs', store.data_dir)


def capabilities():
    """Detection is not a claim that a package has complete models or an adapter."""
    result = {
        'native_text': {'available': True, 'formats': ['txt', 'md', 'csv', 'tsv', 'json', 'xlsx']},
        'native_pdf': {'available': bool(importlib.util.find_spec('pypdfium2') or (shutil.which('pdftotext') and shutil.which('pdfinfo'))),
                       'pdfium_installed': bool(importlib.util.find_spec('pypdfium2')),
                       'poppler_installed': bool(shutil.which('pdftotext') and shutil.which('pdfinfo'))},
        'docling': {'available': False, 'package_installed': bool(importlib.util.find_spec('docling')),
                    'code': 'adapter_not_configured', 'reason': '结构化Docling worker和离线模型manifest尚未接入，不能宣称模型可用'},
        'paddleocr_vl': {'available': False, 'code': 'adapter_not_configured',
                         'reason': '云端PaddleOCR-VL完整pipeline尚未配置，图像识别需要单独部署并核验'},
        'manufacturing_release': False,
    }
    for name in ('docling', 'paddleocr', 'paddleocr_vl'):
        result[name] = _service_status(name)
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RecognitionError(502, '识别worker不得重定向原件或凭据')


def _service_config(name):
    config_path = os.environ.get('KANPACE_RECOGNITION_SERVICE_CONFIG')
    if not config_path:
        return None
    path = Path(config_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RecognitionError(503, '服务manifest必须为服务器管理的绝对路径文件')
    try:
        manifest = _read(path)
    except (OSError, ValueError):
        raise RecognitionError(503, '识别服务manifest不是有效JSON')
    if not isinstance(manifest, dict) or not isinstance(manifest.get('services'), dict):
        raise RecognitionError(503, '识别服务manifest结构无效')
    config = manifest['services'].get(name)
    if not config:
        return None
    if not isinstance(config, dict) or manifest.get('schema_version') != 1 or config.get('protocol') != 'kanpace-document-v1':
        raise RecognitionError(503, '识别服务manifest协议无效')
    if not isinstance(config.get('url'), str):
        raise RecognitionError(503, '服务器识别端点无效')
    url = urlsplit(config['url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise RecognitionError(503, '服务器识别端点无效')
    if not all(isinstance(config.get(k), str) and config[k] for k in ('engine_version', 'model_revision', 'license')):
        raise RecognitionError(503, '识别服务必须固定引擎、模型revision与许可证')
    timeout = config.get('timeout_seconds', 120)
    if type(timeout) is not int or not 1 <= timeout <= 180:
        raise RecognitionError(503, '识别服务超时预算必须为1—180秒')
    if config.get('token_env') is not None and (not isinstance(config['token_env'], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}', config['token_env'])):
        raise RecognitionError(503, '服务凭据环境变量名无效')
    return config


def _service_request(config, suffix, payload=None, timeout=None):
    headers = {'Accept': 'application/json'}
    token_env = config.get('token_env')
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise RecognitionError(503, '识别服务凭据尚未配置')
        headers['Authorization'] = 'Bearer ' + token
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    request = urllib.request.Request(config['url'].rstrip('/') + suffix, data=body, headers=headers)
    # Ignore ambient HTTP proxies: only the server-owned manifest chooses the
    # document destination. A redirect must not forward a source or credential.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout or config.get('timeout_seconds', 120)) as response:
            if 'application/json' not in response.headers.get('Content-Type', ''):
                raise RecognitionError(502, '识别服务未返回JSON证据')
            raw = response.read(MAX_TEXT_BYTES + 1)
            if len(raw) > MAX_TEXT_BYTES:
                raise RecognitionError(502, '识别服务结果超过安全大小')
        return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise RecognitionError(503, '识别worker不可用或返回无效结果', {'code': 'worker_unavailable'})


def _service_status(name):
    package = bool(importlib.util.find_spec('docling')) if name == 'docling' else None
    try:
        config = _service_config(name)
        if config is None:
            return {'available': False, 'package_installed': package, 'code': 'adapter_not_configured',
                    'reason': '完整识别worker及固定模型manifest尚未配置'}
        key = json.dumps(config, sort_keys=True)
        cached = _CAP_CACHE.get(name)
        if cached and cached[0] == key and time.monotonic() - cached[1] < 10:
            return dict(cached[2])
        health = _service_request(config, '/health', timeout=2)
        ready = isinstance(health, dict) and health.get('ready') is True and health.get('schema_version') == 'document_evidence.v1' and all(
            health.get(k) == config[k] for k in ('engine_version', 'model_revision'))
        result = {'available': ready, 'configured': True, 'engine_version': config['engine_version'],
                  'model_revision': config['model_revision'], 'license': config['license'],
                  'code': 'ready' if ready else 'worker_not_ready', 'package_installed': package}
        _CAP_CACHE[name] = (key, time.monotonic(), result)
        return dict(result)
    except RecognitionError as exc:
        return {'available': False, 'code': 'worker_unavailable', 'reason': exc.message, 'package_installed': package}


def sources(store, con, project_id, private=False):
    store.get(con, 'projects', project_id)
    result = []
    for doc in store.all(con, 'documents', project_id):
        if doc.get('superseded') or doc.get('archived'):
            continue
        name = doc.get('storage_name')
        if not isinstance(name, str) or Path(name).name != name:
            continue
        path = store.uploads / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve():
            continue
        row = {'source_id': 'doc:' + doc['id'], 'id': 'doc:' + doc['id'], 'document_id': doc['id'],
               'filename': doc['filename'], 'source_sha256': doc.get('sha256'),
               'source_revision': doc.get('revision'), 'source_role': doc.get('purpose', 'drawing'),
               'source_page': None, 'format': Path(doc['filename']).suffix.lower().lstrip('.'),
               'preview_url': '/api/documents/' + doc['id'] + '/preview'}
        if private:
            row['_path'] = path
        result.append(row)
    # Cached drawing pages retain their true original page, but do not pretend
    # to have an uploaded document identity when the manifest lacks one.
    import intelligence
    for source in intelligence.sources(store, con, project_id, private=True):
        if not source['id'].startswith('asset:'):
            continue
        row = {'source_id': source['id'], 'id': source['id'], 'document_id': None,
               'filename': source['filename'], 'source_sha256': hashlib.sha256(source['_path'].read_bytes()).hexdigest(),
               'source_revision': store.get(con, 'projects', project_id)['revision'],
               'source_role': 'drawing', 'source_page': source.get('source_page'),
               'source_label': source.get('source_label'), 'format': Path(source['filename']).suffix.lower().lstrip('.'),
               'preview_url': source.get('preview_url')}
        if private:
            row['_path'] = source['_path']
        result.append(row)
    return result


def snapshot_jobs(store, con, project_id):
    """Small read-only summaries: no recovery, model probes or result loading."""
    store.get(con, 'projects', project_id)
    root = _directory(store)
    if not root.exists():
        return []
    rows = []
    for folder in root.iterdir():
        if not JOB_RE.fullmatch(folder.name) or folder.is_symlink():
            continue
        try:
            job = _read(_inside(folder / 'job.json', root))
            if job.get('metadata', {}).get('project_id') == project_id:
                rows.append(job)
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda row: row.get('created_at', ''), reverse=True)[:100]


def overview(store, con, project_id):
    return {'sources': sources(store, con, project_id), 'jobs': snapshot_jobs(store, con, project_id),
            'capabilities': capabilities(), 'read_only': True}


def _options(data):
    value = data.get('options', {})
    if not isinstance(value, dict) or set(value) - {'parser', 'pages', 'max_pages'}:
        raise RecognitionError(400, '识别选项无效')
    parser = value.get('parser', 'auto')
    if parser not in ('auto', 'native', 'docling', 'paddleocr', 'paddleocr_vl'):
        raise RecognitionError(400, '请选择已配置的识别方式')
    max_pages = value.get('max_pages', 20)
    pages = value.get('pages')
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise RecognitionError(400, '单次识别页数必须为1—100')
    if pages is not None and (not isinstance(pages, list) or not pages or len(pages) > max_pages
                              or any(type(p) is not int or not 1 <= p <= 10000 for p in pages)
                              or len(set(pages)) != len(pages)):
        raise RecognitionError(400, '页码必须为不重复的正整数')
    return {'parser': parser, 'pages': sorted(pages) if pages else None, 'max_pages': max_pages}


def _current(store, con, project_id, job, check_bytes=False):
    project = store.get(con, 'projects', project_id)
    reasons = []
    if project['revision'] != job['metadata']['revision']:
        reasons.append('project_revision_changed')
    current = {s['source_id']: s for s in sources(store, con, project_id, private=True)}
    for old in job['sources']:
        source = current.get(old['source_id'])
        if not source or any(source.get(k) != old.get(k) for k in ('source_sha256', 'source_revision')):
            reasons.append('source_changed:' + old['source_id'])
        elif check_bytes and hashlib.sha256(source['_path'].read_bytes()).hexdigest() != old['source_sha256']:
            reasons.append('source_integrity_changed:' + old['source_id'])
    return {'current': not reasons, 'issues': reasons, 'review_status': 'unreviewed'}


def get_job(store, con, project_id, job_id):
    if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
        raise RecognitionError(404, '此项目没有这条识别任务')
    root = _directory(store)
    folder = _inside(root / job_id, root)
    try:
        job = _read(_inside(folder / 'job.json', root))
    except (FileNotFoundError, ValueError):
        raise RecognitionError(404, '此项目没有这条识别任务')
    if job.get('metadata', {}).get('project_id') != project_id:
        raise RecognitionError(404, '此项目没有这条识别任务')
    if job['status'] in ('queued', 'running'):
        try:
            process = _read(folder / 'process.json')
            os.kill(process['pid'], 0)
            if time.time() - process['started'] > 900:
                job['status'] = 'interrupted'
                job['error'] = {'code': 'worker_timeout', 'message': '识别worker超时，请重试继续已保存结果'}
        except (OSError, FileNotFoundError, KeyError, ValueError):
            # The parent writes process.json just after spawn. A fast polling
            # request must not call that short registration window a crash.
            if not (folder / 'process.json').exists() and time.time() - (folder / 'job.json').stat().st_mtime < 3:
                return {**job, 'source_integrity': _current(store, con, project_id, job)}
            job['status'] = 'interrupted'
            job['error'] = {'code': 'worker_interrupted', 'message': '识别已中断，已完成文档仍保留，可继续'}
    if (folder / 'result.json').is_file():
        job['result'] = _read(_inside(folder / 'result.json', root))
    job['source_integrity'] = _current(store, con, project_id, job, check_bytes=True)
    return job


def submit(store, con, project_id, data):
    if not isinstance(data, dict) or set(data) - {'source_ids', 'expected_revision', 'options', 'resume_job_id'}:
        raise RecognitionError(400, '整合识别请求字段无效；不接受文件路径或模型URL')
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    if type(data.get('expected_revision')) is not int or data['expected_revision'] != project['revision']:
        raise RecognitionError(409, '资料版本已变化，请刷新后重新选择')
    root = _directory(store)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _LOCK:
        active = 0
        for folder in root.iterdir():
            if not JOB_RE.fullmatch(folder.name) or folder.is_symlink():
                continue
            try:
                rec = _read(folder / 'process.json')
                os.kill(rec['pid'], 0)
                if time.time() - rec['started'] < 900:
                    active += 1
            except (OSError, ValueError, KeyError):
                pass
        if active >= 2:
            raise RecognitionError(429, '正在识别其他资料，请稍后重试')
        resume = data.get('resume_job_id')
        if resume:
            job = get_job(store, con, project_id, resume)
            if not job['source_integrity']['current']:
                raise RecognitionError(409, '原件或版本已变化，不能沿旧任务继续')
            if job['status'] not in ('interrupted', 'failed', 'partial'):
                raise RecognitionError(409, '只可继续中断或部分失败的识别任务')
            if 'source_ids' in data or 'options' in data:
                raise RecognitionError(400, '续跑使用原任务来源与选项，请勿重新指定')
            job.pop('result', None)
            job.pop('source_integrity', None)
            job.pop('error', None)
            folder = root / resume
        else:
            selected = data.get('source_ids')
            if (not isinstance(selected, list) or not 1 <= len(selected) <= 20
                    or any(not isinstance(s, str) for s in selected) or len(set(selected)) != len(selected)):
                raise RecognitionError(400, '请选择1—20份不重复的已上传资料')
            opts = _options(data)
            if opts['parser'] in ('docling', 'paddleocr', 'paddleocr_vl') and not _service_status(opts['parser'])['available']:
                raise RecognitionError(503, '完整识别worker/模型不可用，当前可选择原生解析', {'code': 'worker_unavailable'})
            current = {s['source_id']: s for s in sources(store, con, project_id, private=True)}
            if any(s not in current for s in selected):
                raise RecognitionError(404, '只能识别本项目当前有效的已登记资料')
            chosen = [current[s] for s in selected]
            for source in chosen:
                path = _inside(source['_path'], store.data_dir)
                if path.stat().st_size > MAX_SOURCE_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != source['source_sha256']:
                    raise RecognitionError(409, '原件完整性检查失败，请重新上传')
            folder = root / ('rec_' + uuid.uuid4().hex)
            folder.mkdir(mode=0o700)
            manifest = []
            for index, source in enumerate(chosen):
                row = {k: v for k, v in source.items() if k not in ('_path', 'id')}
                row['input_name'] = f'input-{index}' + Path(source['filename']).suffix.lower()
                content = source['_path'].read_bytes()
                if hashlib.sha256(content).hexdigest() != source['source_sha256']:
                    shutil.rmtree(folder)
                    raise RecognitionError(409, '复制时原件发生变化，请重新选择')
                (folder / row['input_name']).write_bytes(content)
                manifest.append(row)
            job = {'id': folder.name, 'kind': 'document_recognition', 'status': 'queued', 'created_at': now(),
                   'updated_at': now(), 'metadata': {'project_id': project_id, 'revision': project['revision']},
                   'sources': manifest, 'options': opts, 'progress': {'completed': 0, 'total': len(manifest)},
                   'read_only': True, 'review_status': 'unreviewed', 'manufacturing_release': False}
            names = (opts['parser'],) if opts['parser'] in ('docling', 'paddleocr', 'paddleocr_vl') else ('docling', 'paddleocr', 'paddleocr_vl') if opts['parser'] == 'auto' else ()
            job['service_pins'] = {}
            for name in names:
                status = _service_status(name)
                if status['available']:
                    job['service_pins'][name] = {k: status[k] for k in ('engine_version', 'model_revision', 'license')}
        job.update(status='queued', updated_at=now())
        _atomic(folder / 'job.json', job)
        with (folder / 'worker.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(folder)],
                                       cwd=folder, stdout=log, stderr=log, start_new_session=True,
                                       env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        _atomic(folder / 'process.json', {'pid': process.pid, 'started': time.time()})
        _LIVE[job['id']] = process
        threading.Thread(target=_reap, args=(process, folder), daemon=True).start()
        return job


def _reap(process, folder):
    try:
        process.wait(timeout=900)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    with _LOCK:
        _LIVE.pop(folder.name, None)
    try:
        job = _read(folder / 'job.json')
        if job['status'] in ('queued', 'running'):
            job.update(status='interrupted', updated_at=now(), error={'code': 'worker_interrupted', 'message': '任务中断，可继续已保存结果'})
            _atomic(folder / 'job.json', job)
    except (OSError, ValueError):
        pass


def _decode(content):
    if len(content) > MAX_TEXT_BYTES:
        raise RecognitionError(413, '文本解析上限为20 MB')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise RecognitionError(422, '文字编码不可识别，未使用替换字符猜测')


def _evidence(source, key, text, locator, field=None, value=None):
    identity = json.dumps([source['source_id'], source['source_sha256'], source.get('source_revision'), key], ensure_ascii=False)
    return {'evidence_id': 'ev_' + hashlib.sha256(identity.encode()).hexdigest()[:24],
            'document_id': source.get('document_id'), 'source_id': source['source_id'],
            'source_sha256': source['source_sha256'], 'source_revision': source.get('source_revision'),
            'source_role': source['source_role'], 'locator': locator, 'raw_text': text, 'quote': text,
            'candidate': {'field': field, 'value': value if field is not None else text, 'unit': None, 'subject_candidates': []},
            'method': 'native_document_parse', 'engine_version': 'kanpace-native-v1', 'model_revision': None,
            'observation_kind': 'observed', 'review_status': 'unreviewed', 'is_manufacturing_dimension': False}


def _locator(kind, page=1, **extra):
    result = {'kind': kind, 'page': page, 'page_size_pdf_points': None, 'bbox_pdf_points': None,
            'rotation': None, 'cropbox': None, 'crop_to_page_transform': None,
            'canonical_origin': 'top_left', **extra}
    # Compatibility with the shared EvidenceRef normalizer. The canonical
    # bbox_pdf_points is never replaced by image-pixel coordinates.
    result['origin'] = 'top_left'
    result['bbox'] = result.get('bbox_pdf_points')
    if result.get('bbox_pdf_points') is not None:
        result['coordinate_system'] = 'pdf_points'
    return result


def _parse_text(path, source, opts):
    text, encoding = _decode(path.read_bytes())
    suffix = Path(source['filename']).suffix.lower()
    evidence, pages, tables, issues = [], [], [], []
    if suffix in ('.csv', '.tsv'):
        rows = list(csv.reader(io.StringIO(text, newline=''), delimiter='\t' if suffix == '.tsv' else ',', strict=True))
        if len(rows) > 5000:
            raise RecognitionError(413, '表格最多5000行，请分册')
        headers = rows[0] if rows else []
        if len(set(headers)) != len(headers):
            issues.append({'code': 'duplicate_headers', 'message': '重复表头，列含义需要复核'})
        cells = []
        for ri, row in enumerate(rows, 1):
            if len(row) != len(headers):
                issues.append({'code': 'row_width_conflict', 'row': ri, 'expected': len(headers), 'actual': len(row)})
            for ci, value in enumerate(row, 1):
                ref = _evidence(source, f'csv:{ri}:{ci}', value,
                                _locator('table_cell', row=ri, column=ci, table_id='table_1', sheet=source['filename'], cell=f'R{ri}C{ci}'),
                                headers[ci - 1] if ri > 1 and ci <= len(headers) else None, value)
                evidence.append(ref)
                if len(evidence) > MAX_REGIONS:
                    raise RecognitionError(413, '表格字段超过20000，请分册')
                cells.append({'row': ri, 'column': ci, 'row_span': 1, 'col_span': 1,
                              'text_raw': value, 'evidence_id': ref['evidence_id']})
        tables.append({'id': 'table_1', 'source_page': 1, 'headers': headers, 'cells': cells})
        pages.append({'page': 1, 'regions': evidence})
    elif suffix == '.json':
        duplicates = []
        def pairs(items):
            value = {}
            for k, v in items:
                if k in value:
                    duplicates.append(k)
                value[k] = v
            return value
        obj = json.loads(text, object_pairs_hook=pairs,
                         parse_constant=lambda v: (_ for _ in ()).throw(ValueError('非有限JSON数字：' + v)))
        if duplicates:
            raise RecognitionError(422, 'JSON存在重复键，不能静默覆盖：' + ', '.join(duplicates[:5]))
        def visit(value, pointer='', depth=0):
            if depth > 50:
                raise RecognitionError(413, 'JSON层级超过50')
            if isinstance(value, dict):
                for k, v in value.items():
                    visit(v, pointer + '/' + k.replace('~', '~0').replace('/', '~1'), depth + 1)
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    visit(v, pointer + '/' + str(i), depth + 1)
            else:
                evidence.append(_evidence(source, 'json:' + pointer, json.dumps(value, ensure_ascii=False),
                                          _locator('json_pointer', pointer=pointer), pointer, value))
                if len(evidence) > MAX_REGIONS:
                    raise RecognitionError(413, 'JSON字段过多，请分册')
        visit(obj)
        pages.append({'page': 1, 'regions': evidence})
    else:
        split = text.split('\f')
        selected = opts['pages'] or list(range(1, min(len(split), opts['max_pages']) + 1))
        for page_number in selected:
            if page_number > len(split):
                raise RecognitionError(400, '页码超出文字页范围')
            regions = []
            for line_number, line in enumerate(split[page_number - 1].splitlines(), 1):
                if line.strip():
                    ref = _evidence(source, f'text:{page_number}:{line_number}', line,
                                    _locator('text_line', page_number, line=line_number))
                    evidence.append(ref)
                    regions.append(ref)
                    if len(evidence) > MAX_REGIONS:
                        raise RecognitionError(413, '文字区域超过20000，请分册')
            pages.append({'page': page_number, 'regions': regions})
        if len(selected) < len(split):
            issues.append({'code': 'page_selection_partial', 'total_pages': len(split)})
    if len(evidence) > MAX_REGIONS:
        raise RecognitionError(413, '文字区域超过20000，未截断冒充完整结果')
    return {'engine': 'native-' + suffix.lstrip('.'), 'encoding': encoding, 'pages': pages,
            'tables': tables, 'evidence_refs': evidence, 'issues': issues,
            'completeness': 'partial' if issues else 'observed', 'review_status': 'unreviewed'}


def _parse_xlsx(path, source, opts):
    """Read OOXML cells; never execute formulas/macros or follow external links."""
    if opts['pages'] is not None:
        raise RecognitionError(400, 'XLSX没有PDF页码，请省略pages；证据按工作表/单元格定位')
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    evidence, tables, issues = [], [], []
    def address(value):
        match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', value or '')
        if not match:
            raise RecognitionError(422, 'XLSX单元格地址无效')
        col = 0
        for char in match.group(1):
            col = col * 26 + ord(char) - 64
        row = int(match.group(2))
        if col > 16384 or row > 1048576:
            raise RecognitionError(422, 'XLSX单元格超出标准范围')
        return row, col
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise RecognitionError(422, 'XLSX不是有效OOXML ZIP')
    with archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(entries) > 2000 or len(set(names)) != len(names) or sum(e.file_size for e in entries) > 50 * 1024 * 1024:
            raise RecognitionError(413, 'XLSX归档数量/解压大小超过限制或含重复条目')
        for entry in entries:
            name = entry.filename
            if (name.startswith('/') or '\\' in name or '..' in Path(name).parts or entry.flag_bits & 1
                    or entry.file_size > MAX_TEXT_BYTES or entry.file_size > max(entry.compress_size, 1) * 1000):
                raise RecognitionError(422, 'XLSX归档存在不安全路径/加密/异常压缩')
            if name.lower().endswith('vbaproject.bin'):
                raise RecognitionError(422, '宏文件不能作为原生XLSX解析')
        def xml(name):
            if name not in names:
                raise RecognitionError(422, 'XLSX必需文件缺失：' + name)
            raw = archive.read(name)
            declarations = raw.replace(b'\x00', b'').upper()  # also catches UTF-16/32 declarations
            if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
                raise RecognitionError(422, 'XLSX XML禁止DTD/实体声明')
            try:
                return ET.fromstring(raw)
            except ET.ParseError:
                raise RecognitionError(422, 'XLSX XML损坏')
        for name in names:
            if name.endswith('.rels'):
                ignored_hyperlinks = 0
                for rel in xml(name):
                    if rel.get('TargetMode', '').lower() == 'external':
                        # A worksheet hyperlink annotates an existing cell. Its
                        # destination is neither a data dependency nor evidence.
                        # Match canonical OOXML relationship types exactly;
                        # external workbooks, images and OLE stay unsupported.
                        if (rel.tag == '{' + rel_ns + '}Relationship' and rel.get('Type') in (
                                'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',
                                'http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink')):
                            ignored_hyperlinks += 1
                            continue  # Do not read, return, resolve or request Target.
                        raise RecognitionError(422, 'XLSX外部关系不能自动解析')
                if ignored_hyperlinks:
                    issues.append({'code': 'external_hyperlink_ignored', 'relationship_part': name,
                                   'count': ignored_hyperlinks,
                                   'message': '外部超链接目标已忽略且未访问；只保留原单元格显示文字，不作为外部依据'})
        workbook = xml('xl/workbook.xml')
        relationships = xml('xl/_rels/workbook.xml.rels')
        rels = {}
        for rel in relationships:
            if rel.get('TargetMode', '').lower() == 'external':
                continue  # Already validated above; ignored hyperlinks never become workbook sources.
            target = rel.get('Target', '')
            resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not resolved.startswith('xl/') or ':' in target or '\\' in target or rel.get('Id') in rels:
                raise RecognitionError(422, 'XLSX工作表关系不安全或重复')
            rels[rel.get('Id')] = (resolved, rel.get('Type', ''))
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for item in xml('xl/sharedStrings.xml').findall('s:si', ns):
                shared.append(''.join(node.text or '' for node in item.findall('.//s:t', ns)))
                if len(shared) > MAX_REGIONS:
                    raise RecognitionError(413, 'XLSX共享字符串超过限制')
        sheets = workbook.findall('s:sheets/s:sheet', ns)
        if not sheets:
            raise RecognitionError(422, 'XLSX没有可识别工作表或使用未支持XML命名空间')
        if len(sheets) > opts['max_pages']:
            issues.append({'code': 'sheet_selection_partial', 'total_sheets': len(sheets), 'message': '工作表数量超过本次限额，未声称全册完整'})
        sheet_names = set()
        for si, sheet in enumerate(sheets[:opts['max_pages']], 1):
            sheet_name = sheet.get('name')
            relation = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            if not sheet_name or sheet_name in sheet_names or relation not in rels or not rels[relation][1].endswith('/worksheet'):
                raise RecognitionError(422, 'XLSX工作表身份不唯一或关系无效')
            sheet_names.add(sheet_name)
            root = xml(rels[relation][0])
            merges = {}
            for merged in root.findall('s:mergeCells/s:mergeCell', ns):
                cells = merged.get('ref', '').split(':')
                if len(cells) != 2:
                    raise RecognitionError(422, 'XLSX合并单元格无效')
                r0, c0 = address(cells[0]); r1, c1 = address(cells[1])
                if r1 < r0 or c1 < c0 or cells[0] in merges:
                    raise RecognitionError(422, 'XLSX合并范围无效/重复')
                merges[cells[0]] = (r1 - r0 + 1, c1 - c0 + 1)
            cells, seen = [], set()
            for cell in root.findall('s:sheetData/s:row/s:c', ns):
                ref = cell.get('r'); row, col = address(ref)
                if ref in seen:
                    raise RecognitionError(422, 'XLSX单元格地址重复，不能静默覆盖')
                seen.add(ref)
                kind, formula, node = cell.get('t'), cell.find('s:f', ns), cell.find('s:v', ns)
                raw_value = node.text or '' if node is not None else ''
                field, value = 'cell_value', raw_value
                if formula is not None:
                    text, field, value = '=' + (formula.text or ''), 'formula', None
                    issues.append({'code': 'formula_not_evaluated', 'sheet': sheet_name, 'cell': ref,
                                   'message': '保留公式原文；缓存值未重新计算，不能作为制造值'})
                elif kind == 's':
                    if not raw_value.isdigit() or int(raw_value) >= len(shared):
                        raise RecognitionError(422, 'XLSX共享字符串索引无效')
                    text = value = shared[int(raw_value)]
                elif kind == 'inlineStr':
                    text = value = ''.join(n.text or '' for n in cell.findall('s:is//s:t', ns))
                elif kind == 'b':
                    if raw_value not in ('0', '1'):
                        raise RecognitionError(422, 'XLSX布尔值无效')
                    text, value = raw_value, raw_value == '1'
                else:
                    text = raw_value  # Numeric/date serial strings stay exact.
                    if kind == 'e':
                        issues.append({'code': 'spreadsheet_cell_error', 'sheet': sheet_name, 'cell': ref, 'value': text})
                if len(text) > 20000:
                    raise RecognitionError(413, 'XLSX单元格文字过长')
                evidence_ref = _evidence(source, f'xlsx:{si}:{ref}', text,
                    _locator('table_cell', None, sheet=sheet_name, row=row, column=col, cell=ref, table_id=f'sheet_{si}'), field, value)
                evidence_ref.update(method='ooxml_native_cell', engine_version='kanpace-ooxml-v1')
                evidence.append(evidence_ref)
                if len(evidence) > MAX_REGIONS:
                    raise RecognitionError(413, 'XLSX单元格数量超过20000，请分册')
                row_span, col_span = merges.get(ref, (1, 1))
                cells.append({'row': row, 'column': col, 'cell': ref, 'row_span': row_span, 'col_span': col_span,
                              'text_raw': text, 'evidence_id': evidence_ref['evidence_id']})
            tables.append({'id': f'sheet_{si}', 'sheet': sheet_name, 'source_page': None, 'cells': cells})
    return {'engine': 'native-xlsx-ooxml', 'pages': [], 'tables': tables, 'evidence_refs': evidence,
            'issues': issues, 'completeness': 'partial' if len(sheets) > opts['max_pages'] else 'observed', 'review_status': 'unreviewed'}


def _pdf_geometry(path, opts):
    """Original PDF page geometry, independent of text/model predictions.

    Poppler bbox XML reports unrotated page size even though its words follow
    /Rotate. Read MediaBox and rotation separately so overlays use display size.
    Workers must return this exact top-left displayed MediaBox coordinate frame.
    """
    exe = shutil.which('pdfinfo')
    if exe:
        end = max(opts['pages']) if opts['pages'] else opts['max_pages'] + 1
        run = subprocess.run([exe, '-box', '-f', '1', '-l', str(end), str(path)],
                             capture_output=True, timeout=20, env={**os.environ, 'LC_ALL': 'C'})
        if run.returncode or len(run.stdout) > MAX_TEXT_BYTES:
            raise RecognitionError(422, '无法核实PDF原页几何/旋转')
        text = run.stdout.decode('utf-8', errors='strict')
        total_match = re.search(r'^Pages:\s*(\d+)', text, re.M)
        if not total_match:
            raise RecognitionError(422, 'PDF页数无法核实')
        total = int(total_match.group(1))
        selected = opts['pages'] or list(range(1, min(total, opts['max_pages']) + 1))
        result = []
        for number in selected:
            rotation = re.search(r'^Page\s+' + str(number) + r'\s+rot:\s*(\d+)', text, re.M)
            boxes = {}
            for name in ('MediaBox', 'CropBox'):
                match = re.search(r'^Page\s+' + str(number) + r'\s+' + name + r':\s*([^\r\n]+)', text, re.M)
                if not match:
                    raise RecognitionError(400, '选页超出范围或PDF页面框无法核实')
                boxes[name] = [float(v) for v in match.group(1).split()]
            if not rotation or len(boxes['MediaBox']) != 4 or len(boxes['CropBox']) != 4:
                raise RecognitionError(422, 'PDF页面框/旋转无法核实')
            angle = int(rotation.group(1)) % 360
            left, bottom, right, top = boxes['MediaBox']
            size = [right - left, top - bottom]
            if angle not in (0, 90, 180, 270) or any(not math.isfinite(v) for v in boxes['MediaBox'] + boxes['CropBox']) or min(size) <= 0:
                raise RecognitionError(422, 'PDF页面框/旋转无效')
            if angle in (90, 270):
                size.reverse()
            result.append({'page': number, 'page_size_pdf_points': size, 'rotation': angle,
                           'mediabox': boxes['MediaBox'], 'cropbox': boxes['CropBox'],
                           'coordinate_system': 'pdf_points', 'canonical_origin': 'top_left',
                           'coordinate_space': 'pdf_media_display_page', 'crop_to_page_transform': None})
        return result, total
    if importlib.util.find_spec('pypdfium2'):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            selected = opts['pages'] or list(range(1, min(len(pdf), opts['max_pages']) + 1))
            result = []
            for number in selected:
                if number > len(pdf):
                    raise RecognitionError(400, 'PDF页码超出范围')
                page = pdf[number - 1]
                try:
                    observed_media = page.get_mediabox(fallback_ok=False)
                    if observed_media is None:
                        # Some PDFium APIs do not inherit boxes from parent
                        # nodes; a default Letter page would invent provenance.
                        raise RecognitionError(422, 'PDFium无法核实MediaBox；需要pdfinfo核对原页框')
                    media, crop, angle = list(observed_media), list(page.get_cropbox()), page.get_rotation()
                    size = [media[2] - media[0], media[3] - media[1]]
                    if angle in (90, 270):
                        size.reverse()
                    result.append({'page': number, 'page_size_pdf_points': size, 'rotation': angle,
                                   'mediabox': media, 'cropbox': crop, 'coordinate_system': 'pdf_points',
                                   'canonical_origin': 'top_left', 'coordinate_space': 'pdf_media_display_page',
                                   'crop_to_page_transform': None})
                finally:
                    page.close()
            return result, len(pdf)
        finally:
            pdf.close()
    raise RecognitionError(503, '缺少PDFium/pdfinfo，无法守恒校验模型页框，请部署原生PDF几何引擎')


def _pdf_poppler(path, source, opts):
    exe = shutil.which('pdftotext')
    if not exe:
        raise RecognitionError(503, 'PDF原生引擎未安装；扫描图还需要OCR模型', {'code': 'native_pdf_unavailable'})
    if exe not in _NATIVE_CACHE:
        version = subprocess.run([exe, '-v'], capture_output=True, timeout=5)
        output = (version.stdout + version.stderr).decode('utf-8', errors='replace').splitlines()
        _NATIVE_CACHE[exe] = output[0][:200] if output else 'poppler-version-unknown'
    requested = opts['pages']
    geometry, original_total = _pdf_geometry(path, opts)
    page_geometry = {p['page']: p for p in geometry}
    ranges = requested or [None]
    pages, evidence = [], []
    total = None
    for requested_page in ranges:
        cmd = [exe, '-bbox-layout', '-enc', 'UTF-8']
        if requested_page:
            cmd += ['-f', str(requested_page), '-l', str(requested_page)]
        else:
            cmd += ['-f', '1', '-l', str(opts['max_pages'] + 1)]
        run = subprocess.run(cmd + [str(path), '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if run.returncode:
            raise RecognitionError(422, 'PDF文字解析失败，可能加密、文件损坏或页码无效')
        if len(run.stdout) > MAX_TEXT_BYTES:
            raise RecognitionError(413, 'PDF文字结果过大，请减少选页')
        xml = ET.fromstring(run.stdout)
        parsed = [n for n in xml.iter() if n.tag.rsplit('}', 1)[-1] == 'page']
        if requested_page and len(parsed) != 1:
            raise RecognitionError(400, 'PDF页码超出范围')
        total = len(parsed)
        for offset, page in enumerate(parsed):
            if requested_page is None and offset >= opts['max_pages']:
                continue
            page_number = requested_page or offset + 1
            original = page_geometry[page_number]
            width, height = original['page_size_pdf_points']
            refs = []
            for word in page.iter():
                if word.tag.rsplit('}', 1)[-1] != 'word':
                    continue
                text = ''.join(word.itertext())
                bbox = [float(word.attrib[k]) for k in ('xMin', 'yMin', 'xMax', 'yMax')]
                if any(not math.isfinite(v) for v in bbox + [width, height]):
                    raise RecognitionError(422, 'PDF坐标无效')
                loc = _locator('pdf_region', **{k: v for k, v in original.items() if k != 'page'},
                               page=page_number, bbox_pdf_points=bbox)
                ref = _evidence(source, f'pdf:{page_number}:{len(refs)}', text, loc)
                ref.update(method='poppler_native_bbox', engine_version=_NATIVE_CACHE[exe])
                refs.append(ref)
                evidence.append(ref)
                if len(evidence) > MAX_REGIONS:
                    raise RecognitionError(413, 'PDF区域超过20000，请减少选页')
            pages.append({**original, 'regions': refs})
    issues = []
    if not evidence:
        issues.append({'code': 'ocr_required', 'message': '未找到原生文字，需要已配置OCR或人工核对，未伪造文字'})
    if requested or original_total > opts['max_pages']:
        issues.append({'code': 'page_selection_partial', 'message': '只处理所选页/限页，不能称整份完整'})
    return {'engine': 'poppler-native-bbox', 'pages': pages, 'tables': [], 'evidence_refs': evidence,
            'issues': issues, 'completeness': 'partial' if not evidence or requested or original_total > opts['max_pages'] else 'observed',
            'review_status': 'unreviewed'}


@contextmanager
def _pdfium_media_frame(page, original=None):
    """Use PDFium's rendering conversion in our displayed MediaBox frame.

    FPDF_PageToDevice uses the same render parameters as RenderPageBitmap.
    Additional rotation=0 already includes the PDF page's intrinsic /Rotate.
    The Web preview displays MediaBox, whereas PDFium normally uses CropBox;
    temporarily use MediaBox only on this loaded page and restore it on exit.
    No document is saved, and no handwritten rotation formula is used.
    """
    from ctypes import c_int
    import pypdfium2.raw as raw
    media = list(original['mediabox']) if original else page.get_mediabox(fallback_ok=False)
    if media is None:
        raise RecognitionError(422, 'PDFium无法核实MediaBox，未编造页面框')
    media = list(media)
    crop = list(original['cropbox']) if original else list(page.get_cropbox())
    rotation = page.get_rotation()
    if (len(media) != 4 or len(crop) != 4 or any(not math.isfinite(v) for v in media + crop)
            or rotation not in (0, 90, 180, 270) or media[2] <= media[0] or media[3] <= media[1]
            or crop[2] <= crop[0] or crop[3] <= crop[1]
            or original and original['rotation'] != rotation):
        raise RecognitionError(422, 'PDFium原页框/旋转无效，未映射字符')
    expected = [media[2] - media[0], media[3] - media[1]]
    if rotation in (90, 270):
        expected.reverse()
    previous_crop = page.get_cropbox()
    try:
        page.set_cropbox(*media)
        width, height = page.get_size()
        if (any(not math.isfinite(v) or v <= 0 for v in (width, height))
                or any(abs(a - b) > max(.001, abs(b) * 1e-6) for a, b in zip((width, height), expected))):
            raise RecognitionError(422, 'PDFium显示框与MediaBox不一致，未映射字符')
        # A virtual canvas gives sub-point precision without allocating a bitmap.
        size_x, size_y = math.ceil(width * 1000), math.ceil(height * 1000)
        if max(size_x, size_y) > 2 ** 30:
            raise RecognitionError(422, 'PDFium页面映射范围过大')
        def point(x, y):
            if any(not math.isfinite(v) for v in (x, y)):
                raise RecognitionError(422, 'PDFium字符坐标无效')
            dx, dy = c_int(), c_int()
            ok = raw.FPDF_PageToDevice(page, 0, 0, size_x, size_y, 0, x, y, dx, dy)
            if not ok:
                raise RecognitionError(422, 'PDFium原生坐标转换失败，未编造定位')
            return dx.value * width / size_x, dy.value * height / size_y
        yield {'page_size_pdf_points': [width, height], 'rotation': rotation, 'mediabox': media,
               'cropbox': crop, 'coordinate_space': 'pdf_media_display_page',
               'crop_to_page_transform': None, 'point': point}
    finally:
        page.set_cropbox(*previous_crop)


def _pdf_pdfium(path, source, opts, allow_transformed=False):
    import pypdfium2 as pdfium
    pages, evidence, empty_pages = [], [], []
    originals = {g['page']: g for g in _pdf_geometry(path, opts)[0]} if allow_transformed else {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        selected = opts['pages'] or list(range(1, min(len(pdf), opts['max_pages']) + 1))
        for page_number in selected:
            if page_number > len(pdf):
                raise RecognitionError(400, 'PDF页码超出范围')
            page = pdf[page_number - 1]
            try:
                rotation = page.get_rotation()
                # Preserve the proven Poppler route for ordinary transformed
                # PDFs; the SDK conversion is a verified rescue if it fails.
                if not allow_transformed and (rotation or page.get_mediabox() != page.get_cropbox() or list(page.get_mediabox())[:2] != [0, 0]):
                    raise AttributeError('PDFium rotated/crop coordinate conversion requires verified fallback')
                with _pdfium_media_frame(page, originals.get(page_number)) as frame:
                    width, height = frame['page_size_pdf_points']
                    tp = page.get_textpage()
                    try:
                        count = tp.count_chars()
                        if count + len(evidence) > MAX_REGIONS:
                            raise RecognitionError(413, 'PDF字符区域过多，请减少选页')
                        refs = []
                        for index in range(count):
                            text = tp.get_text_range(index, 1)
                            if not text.strip():
                                continue
                            left, bottom, right, top = tp.get_charbox(index)
                            if not (left < right and bottom < top):
                                raise RecognitionError(422, 'PDFium字符框退化，未编造定位')
                            points = [frame['point'](x, y) for x, y in ((left, bottom), (left, top), (right, bottom), (right, top))]
                            bbox = [min(p[0] for p in points), min(p[1] for p in points),
                                    max(p[0] for p in points), max(p[1] for p in points)]
                            if not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height):
                                raise AttributeError('PDFium character geometry needs word-frame fallback')
                            ref = _evidence(source, f'pdf:{page_number}:{index}', text,
                                _locator('pdf_region', page_number, **{k: v for k, v in frame.items() if k != 'point'},
                                         bbox_pdf_points=bbox))
                            ref.update(method='pdfium_native_char', engine_version=importlib.metadata.version('pypdfium2'))
                            refs.append(ref)
                            evidence.append(ref)
                        if not refs:
                            empty_pages.append(page_number)
                        pages.append({'page': page_number, **{k: v for k, v in frame.items() if k != 'point'}, 'regions': refs})
                    finally:
                        tp.close()
            finally:
                page.close()
        partial = len(selected) < len(pdf)
    finally:
        pdf.close()
    issues = [{'code': 'ocr_required', 'pages': empty_pages, 'message': '这些页未找到原生文字，需要OCR或人工核对'}] if empty_pages else []
    if partial:
        issues.append({'code': 'page_selection_partial'})
    return {'engine': 'pdfium-native-char', 'pages': pages, 'tables': [], 'evidence_refs': evidence,
            'issues': issues, 'completeness': 'partial' if partial or empty_pages else 'observed', 'review_status': 'unreviewed'}


def parse(path, source, opts, service_pins=None):
    suffix = Path(source['filename']).suffix.lower()
    parser = opts['parser']
    if parser in ('docling', 'paddleocr', 'paddleocr_vl'):
        return _remote_parse(path, source, opts, parser, service_pins)
    if suffix == '.xlsx':
        return _parse_xlsx(path, source, opts)
    if suffix in ('.txt', '.md', '.csv', '.tsv', '.json'):
        return _parse_text(path, source, opts)
    if suffix == '.pdf':
        if parser == 'auto' and (service_pins is None or 'docling' in service_pins) and _service_status('docling')['available']:
            return _remote_parse(path, source, opts, 'docling', service_pins)
        if importlib.util.find_spec('pypdfium2'):
            try:
                return _pdf_pdfium(path, source, opts)
            except (ImportError, OSError, AttributeError):
                try:
                    result = _pdf_poppler(path, source, opts)
                except RecognitionError as exc:
                    if exc.status not in (422, 503):
                        raise
                    result = _pdf_pdfium(path, source, opts, allow_transformed=True)
                    result['issues'].append({'code': 'poppler_compatibility_fallback',
                                            'message': 'Poppler未完成解析；采用PDFium原生渲染坐标转换，原件未修改'})
                    return result
                result['issues'].append({'code': 'pdfium_fallback', 'message': 'PDFium路径不可用，使用真实Poppler原生坐标'})
                return result
        return _pdf_poppler(path, source, opts)
    if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp') and parser == 'auto':
        for name in ('paddleocr_vl', 'paddleocr'):
            if (service_pins is None or name in service_pins) and _service_status(name)['available']:
                return _remote_parse(path, source, opts, name, service_pins)
    raise RecognitionError(503 if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp') else 422,
                           '此格式需要额外模型/几何适配，当前未接入；原件仍保存供复核', {'code': 'adapter_not_configured'})


def _remote_parse(path, source, opts, name, service_pins=None):
    config = _service_config(name)
    if not config or not _service_status(name)['available']:
        raise RecognitionError(503, '识别worker或固定模型不可用', {'code': 'worker_unavailable'})
    if service_pins is not None and service_pins.get(name) != {k: config[k] for k in ('engine_version', 'model_revision', 'license')}:
        raise RecognitionError(409, '识别模型/许可证配置已变化；不能在原任务中混用不同模型，请新建任务')
    if Path(source['filename']).suffix.lower() == '.pdf':
        geometry, total_pages = _pdf_geometry(path, opts)
        coordinate_system, bbox_key, size_key = 'pdf_points', 'bbox_pdf_points', 'page_size_pdf_points'
    elif Path(source['filename']).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'):
        try:
            from PIL import Image
            with Image.open(path) as image:
                if getattr(image, 'n_frames', 1) != 1:
                    raise RecognitionError(422, '多帧图像需先逐页登记，不能丢失原页映射')
                width, height = image.size
        except (ImportError, OSError):
            raise RecognitionError(503, '图像原件尺寸无法核实；需部署Pillow/逐页图像适配')
        if opts['pages'] not in (None, [1]) or width <= 0 or height <= 0 or width * height > 100000000:
            raise RecognitionError(422, '图像页码或尺寸无效')
        geometry = [{'page': 1, 'page_size_pixels': [width, height], 'rotation': None,
                     'coordinate_system': 'pixels', 'canonical_origin': 'top_left', 'coordinate_space': 'original_image_pixels'}]
        total_pages = 1
        coordinate_system, bbox_key, size_key = 'pixels', 'bbox_pixels', 'page_size_pixels'
    else:
        raise RecognitionError(422, '模型适配只接受可核实原页几何的PDF/图像；文字和表格请用native')
    originals = {p['page']: p for p in geometry}
    request_source = {k: source.get(k) for k in ('document_id', 'source_id', 'source_sha256', 'source_revision', 'source_role', 'source_page')}
    payload = {'protocol': 'kanpace-document-v1', 'source': request_source,
               'input': {'filename': source['filename'], 'content_base64': base64.b64encode(path.read_bytes()).decode('ascii')},
               'options': opts, 'source_geometry': geometry,
               'required_engine_version': config['engine_version'], 'required_model_revision': config['model_revision']}
    response = _service_request(config, '/recognize', payload)
    if not isinstance(response, dict) or response.get('schema_version') != 'document_evidence.v1':
        raise RecognitionError(502, '识别worker证据schema不匹配')
    if response.get('source') != request_source or any(response.get(k) != config[k] for k in ('engine_version', 'model_revision')):
        raise RecognitionError(502, '识别worker返回来源或模型版本不一致')
    incoming = response.get('pages')
    if not isinstance(incoming, list) or not incoming or len(incoming) > opts['max_pages']:
        raise RecognitionError(502, '识别worker未返回有效原页证据')
    pages, evidence, seen = [], [], set()
    for page in incoming:
        number = page.get('page') if isinstance(page, dict) else None
        size = page.get(size_key) if isinstance(page, dict) else None
        if (type(number) is not int or number < 1 or number in seen or
                (opts['pages'] and number not in opts['pages']) or
                not isinstance(size, list) or len(size) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in size)
                or page.get('canonical_origin') != 'top_left' or page.get('coordinate_system') != coordinate_system):
            raise RecognitionError(502, '识别worker原页/坐标单位无效，禁止猜测映射')
        original = originals.get(number)
        if (original is None or any(abs(a - b) > .01 for a, b in zip(size, original[size_key]))
                or page.get('coordinate_space') != original['coordinate_space']
                or page.get('rotation') != original['rotation']):
            raise RecognitionError(502, '识别worker页面大小/旋转/坐标空间与原件不守恒')
        seen.add(number)
        regions = page.get('regions')
        if not isinstance(regions, list):
            raise RecognitionError(502, '识别worker区域证据无效')
        refs = []
        for index, region in enumerate(regions):
            bbox = region.get(bbox_key) if isinstance(region, dict) else None
            text = region.get('text_raw') if isinstance(region, dict) else None
            if (not isinstance(text, str) or len(text) > 20000 or not isinstance(bbox, list) or len(bbox) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox)
                    or not (0 <= bbox[0] < bbox[2] <= size[0] and 0 <= bbox[1] < bbox[3] <= size[1])):
                raise RecognitionError(502, '识别worker区域框或文字无效')
            effective_page = source.get('source_page') or number
            locator = _locator('pdf_region' if coordinate_system == 'pdf_points' else 'image_region', effective_page,
                               **{k: v for k, v in original.items() if k != 'page'}, **{bbox_key: bbox})
            ref = _evidence(source, f'{name}:{number}:{index}', text,
                            locator)
            ref.update(method=name + '_full_pipeline', engine_version=config['engine_version'], model_revision=config['model_revision'])
            evidence.append(ref)
            refs.append(ref)
            if len(evidence) > MAX_REGIONS:
                raise RecognitionError(502, '识别worker区域数超过安全限额')
        pages.append({**original, 'page': source.get('source_page') or number, 'regions': refs})
    # Worker cells reference server-generated region indices, never unchecked
    # model-generated evidence IDs. Unknown relationships are left for review.
    tables = []
    incoming_tables = response.get('tables', [])
    if not isinstance(incoming_tables, list) or len(incoming_tables) > 1000:
        raise RecognitionError(502, '识别worker表格数量/结构无效')
    for table in incoming_tables:
        if not isinstance(table, dict) or type(table.get('page')) is not int or table['page'] not in seen or not isinstance(table.get('cells'), list):
            raise RecognitionError(502, '识别worker表格结构无效')
        cells = []
        page_refs = next(p['regions'] for p in pages if p['page'] == (source.get('source_page') or table['page']))
        for cell in table['cells']:
            if not isinstance(cell, dict):
                raise RecognitionError(502, '识别worker单元格无效')
            indices = cell.get('region_indices', [])
            if (any(type(cell.get(k)) is not int or cell[k] < 1 for k in ('row', 'column', 'row_span', 'col_span'))
                    or not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(page_refs) for i in indices)
                    or not isinstance(cell.get('text_raw'), str)):
                raise RecognitionError(502, '识别worker单元格或证据关联无效')
            cells.append({k: cell[k] for k in ('row', 'column', 'row_span', 'col_span', 'text_raw')})
            cells[-1]['evidence_refs'] = [page_refs[i]['evidence_id'] for i in indices]
        tables.append({'id': str(table.get('id', 'table'))[:100], 'source_page': source.get('source_page') or table['page'], 'cells': cells})
    return {'engine': name, 'pages': pages, 'tables': tables, 'evidence_refs': evidence,
            'issues': [{'code': 'review_required', 'message': '云端模型输出为未复核观察，不能自动发布制造'}],
            'completeness': 'partial' if opts['pages'] or total_pages > len(pages) else 'observed', 'review_status': 'unreviewed'}


def _combine(job, documents):
    refs = [ref for doc in documents if doc.get('result') for ref in doc['result'].get('evidence_refs', [])]
    issues = [dict(issue, source_id=doc['source_id']) for doc in documents if doc.get('result')
              for issue in doc['result'].get('issues', [])]
    return {'schema_version': 'document_evidence.v1', 'documents': documents, 'evidence_refs': refs,
            'conflicts': [i for i in issues if i['code'] in ('duplicate_headers', 'row_width_conflict')],
            'warnings': issues, 'metadata': job['metadata'], 'read_only': True,
            'review_status': 'unreviewed', 'manufacturing_release': False}


def worker(folder):
    folder = Path(folder).resolve()
    if not JOB_RE.fullmatch(folder.name) or folder.parent.name != 'recognition-jobs':
        raise ValueError('Invalid private job directory')
    job = _read(folder / 'job.json')
    job.update(status='running', updated_at=now())
    _atomic(folder / 'job.json', job)
    documents = []
    for index, source in enumerate(job['sources']):
        checkpoint = folder / f'document-{index}.json'
        if checkpoint.is_file():
            previous = _read(checkpoint)
            if previous.get('status') == 'completed' and previous.get('source_sha256') == source['source_sha256']:
                documents.append(previous)
                continue
        row = {'source_id': source['source_id'], 'document_id': source.get('document_id'),
               'source_sha256': source['source_sha256'], 'source_revision': source.get('source_revision'),
               'filename': source['filename'], 'status': 'failed'}
        try:
            name = source['input_name']
            if Path(name).name != name:
                raise RecognitionError(409, '任务原件路径无效')
            path = _inside(folder / name, folder)
            if hashlib.sha256(path.read_bytes()).hexdigest() != source['source_sha256']:
                raise RecognitionError(409, '任务原件完整性检查失败')
            row['result'] = parse(path, source, job['options'], job.get('service_pins', {}))
            row['status'] = 'completed'
        except Exception as exc:
            row['error'] = {'code': (getattr(exc, 'details', None) or {}).get('code', 'parse_failed') if isinstance(getattr(exc, 'details', None), (dict, type(None))) else 'parse_failed',
                            'message': str(exc)[:500]}
        documents.append(row)
        _atomic(checkpoint, row)
        job.update(progress={'completed': len(documents), 'total': len(job['sources'])}, updated_at=now())
        _atomic(folder / 'result.json', _combine(job, documents))
        _atomic(folder / 'job.json', job)
    done = sum(d['status'] == 'completed' for d in documents)
    job.update(status='completed' if done == len(documents) else 'partial' if done else 'failed',
               progress={'completed': len(documents), 'total': len(documents)}, updated_at=now())
    _atomic(folder / 'result.json', _combine(job, documents))
    _atomic(folder / 'job.json', job)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('Only a private recognition worker may run this module')
    worker(sys.argv[2])
