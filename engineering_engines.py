"""Local, asynchronous OCR and exact CAD inspection; no production mutations.

The caller authenticates access to the document/project. This module additionally
confines source files and all job records to its factory directory. Heavy native
libraries run in a disposable, network-denied worker, never in the HTTP process.
"""

# Third-party licensing: see THIRD_PARTY_NOTICES.md and licenses/engineering/.
# Paddle code and each pinned OCR model have separate Apache-2.0 evidence.
# OCP wrapper Apache-2.0 does not replace embedded OCCT LGPL + exception,
# FreeImage FIPL, LibRaw LGPL/CDDL or other native dependency requirements.
# This source release excludes native environments and model weights.
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DEFAULT_PYTHON = ROOT / '.venv-engineering/bin/python'
DEFAULT_MODELS = ROOT / 'models/engineering'
MODEL_NAMES = ('PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_rec')
JOB_RE = re.compile(r'^eng_[0-9a-f]{32}$')
_LOCK = threading.RLock()
_PROBES = {}
_PROBE_LOCK = threading.Lock()
MAX_BYTES = 100 * 1024 * 1024
PROBE_PACKAGES = ('cadquery-ocp', 'paddleocr', 'paddlepaddle', 'pypdfium2', 'Pillow')


def _complete_probe(versions):
    return isinstance(versions, dict) and all(isinstance(versions.get(name), str) and versions[name] for name in PROBE_PACKAGES)


def _probe_fingerprint(python, models, env):
    """Invalidate actual native health when runtime, libraries or config change."""
    runtime = python.absolute().parent.parent
    paths = [python, python.resolve(), Path(__file__).resolve(), models / 'manifest.json']
    for pattern in ('python*/site-packages/OCP/OCP*.so',
                    'python*/site-packages/OCP/.dylibs/*.dylib',
                    'python*/site-packages/paddle/base/libpaddle.*',
                    'python*/site-packages/*.dist-info/METADATA'):
        paths.extend(sorted((runtime / 'lib').glob(pattern)))
    for name in MODEL_NAMES:
        paths.extend(models / name / asset for asset in ('inference.json', 'inference.pdiparams', 'inference.yml'))
    records = []
    for path in paths:
        try:
            stat = path.stat()
            records.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_mode))
        except OSError:
            records.append((str(path), None))
    # Per-job cache paths vary; executable lookup, locale and home affect imports.
    context = {key: env.get(key) for key in ('PATH', 'HOME', 'LANG', 'LC_ALL')}
    return hashlib.sha256(json.dumps([records, context, MODEL_NAMES], sort_keys=True).encode()).hexdigest()


class EngineeringError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _json(path, value):
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _load(path):
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def _sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _inside(path, root):
    """Reject symlinks as well as resolved cross-factory traversal."""
    path = Path(os.path.abspath(path))
    root = Path(root).resolve()
    # macOS /var and /tmp are system aliases of /private/*; normalize only the
    # prefix above the factory, then inspect every component within the factory.
    anchor = path
    while anchor != anchor.parent and anchor.resolve() != root:
        anchor = anchor.parent
    if anchor.resolve() != root:
        raise EngineeringError('outside_factory', '文件不属于当前工厂')
    path = root / path.relative_to(anchor)
    current = path
    while current != root:
        if current.is_symlink():
            raise EngineeringError('symlink_rejected', '不支持链接到其他位置的文件')
        current = current.parent
    if not path.resolve().is_relative_to(root):
        raise EngineeringError('outside_factory', '文件不属于当前工厂')
    return path


def _options(kind, options):
    options = options or {}
    if not isinstance(options, dict):
        raise EngineeringError('bad_options', '处理选项必须是对象')
    if kind == 'cad':
        if options:
            raise EngineeringError('bad_options', 'CAD 检查暂不接受额外选项')
        return {}
    if set(options) - {'pages', 'dpi'}:
        raise EngineeringError('bad_options', '未知的图纸识别选项')
    dpi = options.get('dpi', 144)
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 96 <= dpi <= 300:
        raise EngineeringError('bad_options', '图纸清晰度需为 96—300 DPI')
    pages = options.get('pages')
    if pages is not None:
        if (not isinstance(pages, list) or not pages or len(pages) > 12
                or any(type(p) is not int or p < 1 for p in pages)
                or len(set(pages)) != len(pages)):
            raise EngineeringError('bad_options', '请选择不重复的 1—12 个页码')
    return {'dpi': dpi, 'pages': pages}


class EngineeringJobs:
    """Persistent jobs. Instantiate with Store.data_dir, never a caller-supplied root."""

    def __init__(self, factory_dir, python_path=None, model_dir=None):
        self.factory_dir = Path(factory_dir).resolve()
        self.directory = _inside(self.factory_dir / 'engineering-jobs', self.factory_dir)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.python = Path(python_path or DEFAULT_PYTHON)
        self.models = Path(model_dir or DEFAULT_MODELS).resolve()

    def status(self):
        base = {'local_only': True, 'python_ready': self.python.is_file(),
                'ocr': {'ready': False, 'models': list(MODEL_NAMES)},
                'cad': {'ready': False, 'formats': ['STEP', 'STP']}}
        if not base['python_ready']:
            base['message'] = '工程引擎尚未安装，请运行 tools/setup_engineering.py'
            return base
        probe_dir = _inside(self.directory / '_probe', self.factory_dir)
        probe_dir.mkdir(exist_ok=True, mode=0o700)
        env = _environment(probe_dir)
        fingerprint = _probe_fingerprint(self.python, self.models, env)
        key = (str(self.python.absolute()), fingerprint)
        cached = _PROBES.get(key)
        if cached and time.monotonic() - cached[0] < (600 if cached[2]['state'] == 'verified' else 5):
            versions, detail = cached[1], dict(cached[2], cached=True)
        else:
            health = _inside(probe_dir / 'health.json', self.factory_dir)
            try:
                saved = _load(health)
                valid = (saved['fingerprint'] == fingerprint and 0 <= time.time() - saved['checked_epoch'] < 86400
                         and _complete_probe(saved['versions']))
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
            if valid:
                versions = saved['versions']
                detail = {'state': 'verified', 'checked_at': saved['checked_at'], 'cached': True}
            elif not _PROBE_LOCK.acquire(blocking=False):
                versions, detail = {}, {'state': 'running', 'message': '本地引擎正在检查，请稍后刷新'}
            else:
                try:
                    versions, detail = self._run_probe(probe_dir, env)
                    if _complete_probe(versions) and detail['state'] == 'verified':
                        _json(health, {'fingerprint': fingerprint, 'versions': versions,
                                      'checked_epoch': time.time(), 'checked_at': detail['checked_at']})
                finally:
                    _PROBE_LOCK.release()
            _PROBES[key] = (time.monotonic(), versions, detail)
        base['versions'], base['probe'] = versions, detail
        base['cad']['ready'] = bool(base['versions'].get('cadquery-ocp'))
        models_ready = (self.models / 'manifest.json').is_file() and all((self.models / name / 'inference.json').is_file()
                           and (self.models / name / 'inference.pdiparams').is_file()
                           for name in MODEL_NAMES)
        base['ocr']['ready'] = bool(base['versions'].get('paddleocr')
                                   and base['versions'].get('paddlepaddle') and models_ready)
        base['ocr']['models_ready'] = models_ready
        return base

    def _run_probe(self, directory, env):
        command = [str(self.python), str(Path(__file__).resolve()), '--probe']
        if sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').exists():
            command = ['/usr/bin/sandbox-exec', '-p', _sandbox_profile(self.python, self.models, directory)] + command
        started = time.monotonic()
        output, error, code, state = '', '', None, 'failed'
        try:
            probe = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                                   timeout=40, env=env)
            output, error, code = probe.stdout, probe.stderr, probe.returncode
            if code == 0:
                state = 'verified'
        except subprocess.TimeoutExpired as exc:
            output, error, state = exc.stdout or '', exc.stderr or '', 'timeout'
        except OSError as exc:
            error = repr(exc)
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='replace')
        if isinstance(error, bytes):
            error = error.decode('utf-8', errors='replace')
        versions = {}
        for line in output.splitlines():
            try:
                payload = json.loads(line)
                versions.update({name: payload[name] for name in PROBE_PACKAGES
                                 if isinstance(payload.get(name), str)})
            except (ValueError, TypeError, AttributeError):
                continue
        if state == 'verified' and not _complete_probe(versions):
            state = 'failed'
        checked_at = _now()
        # Private diagnostics contain native stderr; only state is returned via API.
        _json(directory / 'probe-log.json', {'checked_at': checked_at, 'state': state,
              'seconds': round(time.monotonic() - started, 3), 'exit_code': code,
              'versions': versions, 'stdout': output[-30000:], 'stderr': error[-30000:]})
        detail = {'state': state, 'checked_at': checked_at, 'cached': False}
        if state == 'timeout':
            detail['message'] = '本地引擎首次加载超时，请稍后刷新；已完成的引擎仍可用'
        elif state == 'failed':
            detail['message'] = '部分工程引擎检查未通过，管理员可查看私有探针日志'
        return versions, detail

    def submit(self, kind, source_path, filename, options=None, metadata=None):
        if kind not in ('ocr', 'cad'):
            raise EngineeringError('unsupported_kind', '处理类型需为 ocr 或 cad')
        if (not isinstance(filename, str) or not filename or len(filename) > 240
                or any(c in filename for c in '/\\\x00') or any(ord(c) < 32 for c in filename)):
            raise EngineeringError('bad_filename', '文件名无效')
        suffix = Path(filename).suffix.lower()
        supported = {'.step', '.stp'} if kind == 'cad' else {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.pdf'}
        if suffix not in supported:
            msg = ('请由 SolidWorks 导出 STEP 文件后检查；原生文件需使用导出桥接'
                   if kind == 'cad' else '文字识别支持 PDF、PNG、JPG、WebP、TIFF、BMP')
            raise EngineeringError('unsupported_format', msg)
        opts = _options(kind, options)
        source = _inside(source_path, self.factory_dir)
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES:
            raise EngineeringError('bad_source', '文件不存在、为空或超过 100 MB')
        if not self.python.is_file():
            raise EngineeringError('engine_not_installed', '工程引擎尚未安装')
        # Only identifiers are retained. Caller must have already checked these.
        metadata = metadata or {}
        meta = {k: str(metadata[k])[:180] for k in ('document_id', 'project_id', 'revision', 'source_label', 'source_id') if k in metadata}
        if 'source_page' in metadata:
            source_page = metadata['source_page']
            if type(source_page) is not int or source_page < 1:
                raise EngineeringError('bad_metadata', '来源页码必须为正整数')
            meta['source_page'] = source_page
        with _LOCK:
            active = [p for p in self.list() if p['status'] in ('queued', 'running')]
            if len(active) >= 2:
                raise EngineeringError('busy', '当前工厂已有两个处理任务，请等待完成后重试')
            job_id = 'eng_' + uuid.uuid4().hex
            job_dir = self.directory / job_id
            job_dir.mkdir(mode=0o700)
            # Worker reads an immutable task copy, not the live uploaded source.
            target = job_dir / ('input' + suffix)
            fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            try:
                with os.fdopen(fd, 'rb') as src, target.open('xb') as out:
                    copied = 0
                    while block := src.read(1024 * 1024):
                        copied += len(block)
                        if copied > MAX_BYTES:
                            raise EngineeringError('bad_source', '文件超过 100 MB')
                        out.write(block)
                os.chmod(target, 0o600)
                job = {'id': job_id, 'kind': kind, 'status': 'queued', 'created_at': _now(),
                       'updated_at': _now(), 'source': {'filename': filename, 'sha256': _sha(target),
                       'size': copied}, 'metadata': meta, 'progress': {'completed': 0, 'total': None}}
                _json(job_dir / 'job.json', job)
                _json(job_dir / 'request.json', {'kind': kind, 'input_name': target.name, 'options': opts,
                                                'model_dir': str(self.models)})
                command = [str(self.python), str(Path(__file__).resolve()), '--worker', str(job_dir)]
                if sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').exists():
                    command = ['/usr/bin/sandbox-exec', '-p', _sandbox_profile(self.python, self.models, job_dir)] + command
                with (job_dir / 'worker.log').open('wb') as log:
                    process = subprocess.Popen(command, cwd=job_dir, env=_environment(job_dir),
                                               stdout=log, stderr=log, start_new_session=True)
                # pid is private to the job and omitted from HTTP results.
                _json(job_dir / 'process.json', {'pid': process.pid, 'started': time.time()})
                threading.Thread(target=_reap, args=(process, job_dir), daemon=True).start()
                return job
            except Exception:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise

    def get(self, job_id):
        if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
            raise EngineeringError('not_found', '未找到当前工厂的处理任务')
        directory = _inside(self.directory / job_id, self.factory_dir)
        path = _inside(directory / 'job.json', self.factory_dir)
        if not path.is_file():
            raise EngineeringError('not_found', '未找到当前工厂的处理任务')
        job = _load(path)
        if job['status'] in ('queued', 'running'):
            procfile = directory / 'process.json'
            if procfile.exists():
                proc = _load(procfile)
                try:
                    os.kill(proc['pid'], 0)
                    alive = True
                except (ProcessLookupError, PermissionError):
                    alive = False
                if not alive or time.time() - proc['started'] > 960:
                    job.update(status='failed', updated_at=_now(), error={
                        'code': 'worker_interrupted', 'message': '处理进程中断或超时，请重新提交'})
                    _json(path, job)
        if job['status'] == 'completed':
            job['result'] = _load(_inside(directory / 'result.json', self.factory_dir))
        return job

    def list(self):
        result = []
        for path in sorted(self.directory.glob('eng_*'), reverse=True):
            if JOB_RE.fullmatch(path.name):
                # A completed OCR/CAD result can be large. Listing is used on
                # every project engineering view and for job selection, so
                # load only its small job.json summary. Still call get() for
                # active jobs to perform the existing worker-liveness check.
                job = _load(_inside(path / 'job.json', self.factory_dir))
                if job.get('status') in ('queued', 'running'):
                    job = self.get(path.name)
                job.pop('result', None)
                result.append(job)
        return sorted(result, key=lambda p: p['created_at'], reverse=True)


def _environment(private_dir):
    # No inherited API credentials, proxies, or user-global model/cache stores.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'SYSTEMROOT') if k in os.environ}
    env.update({'TMPDIR': str(private_dir), 'XDG_CACHE_HOME': str(private_dir / 'cache'),
                'HF_HOME': str(private_dir / 'cache/hf'), 'HF_HUB_OFFLINE': '1',
                'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True', 'PADDLE_PDX_MODEL_SOURCE': 'HF',
                'PADDLE_PDX_CACHE_HOME': str(private_dir / 'cache/paddlex'),
                'PADDLE_HOME': str(private_dir / 'cache/paddle'), 'MPLCONFIGDIR': str(private_dir / 'cache/matplotlib'),
                'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONNOUSERSITE': '1'})
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def _sandbox_profile(python, models, job_dir):
    """Native CAD external references cannot bypass factory source validation."""
    allowed = [python.resolve().parent.parent, python.absolute().parent.parent,
               models, job_dir.resolve()]
    paths = ' '.join('(subpath ' + json.dumps(str(path)) + ')' for path in allowed)
    literal = json.dumps(str(Path(__file__).resolve()))
    private = json.dumps(str(job_dir.resolve()))
    protected = [Path.home().resolve(), Path('/Volumes'), job_dir.resolve().parent.parent.parent]
    roots = ' '.join('(subpath ' + json.dumps(str(path)) + ')' for path in protected)
    return ('(version 1)(allow default)(deny network*)'
            '(deny file-read-data (require-all (require-any ' + roots + ')'
            ' (require-not (require-any ' + paths + ' (literal ' + literal + ')))))'
            '(deny file-write* (require-all (require-any ' + roots + ')'
            ' (require-not (subpath ' + private + '))))')


def _reap(process, directory):
    try:
        process.wait(timeout=925)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    try:
        path = directory / 'job.json'
        job = _load(path)
        if job['status'] in ('queued', 'running'):
            job.update(status='failed', updated_at=_now(), error={
                'code': 'worker_interrupted', 'message': '处理进程中断或超时，请重新提交'})
            _json(path, job)
    except (OSError, ValueError):
        pass


def _deny_network():
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError('本地工程处理禁止网络访问；请先在安装步骤下载模型')
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.socket.sendto = denied


def _run_ocr(source, options, model_dir, progress):
    from PIL import Image
    import importlib.metadata
    for name in MODEL_NAMES:
        if not (model_dir / name / 'inference.pdiparams').is_file():
            raise EngineeringError('models_missing', '本地 OCR 模型尚未下载，请运行工程引擎安装脚本')
    try:
        manifest = _load(model_dir / 'manifest.json')
        revisions = {}
        for name in MODEL_NAMES:
            entry = next(m for m in manifest['models'] if m['name'] == name)
            for asset in ('inference.json', 'inference.pdiparams', 'inference.yml'):
                if _sha(model_dir / name / asset) != entry['files_sha256'][asset]:
                    raise EngineeringError('model_checksum_mismatch', '本地模型校验未通过，请重新下载模型')
            revisions[name] = entry['revision']
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        if isinstance(exc, EngineeringError):
            raise
        raise EngineeringError('models_missing', '本地模型安装记录不完整，请重新运行下载命令') from exc
    from paddleocr import PaddleOCR
    pipeline = PaddleOCR(text_detection_model_name=MODEL_NAMES[0],
                         text_detection_model_dir=str(model_dir / MODEL_NAMES[0]),
                         text_recognition_model_name=MODEL_NAMES[1],
                         text_recognition_model_dir=str(model_dir / MODEL_NAMES[1]),
                         use_doc_orientation_classify=False, use_doc_unwarping=False,
                         use_textline_orientation=False, device='cpu', cpu_threads=1,
                         enable_mkldnn=False)
    pages = []
    pdf = None
    if source.suffix == '.pdf':
        import pypdfium2
        pdf = pypdfium2.PdfDocument(str(source))
        page_count = len(pdf)
    else:
        with Image.open(source) as im:
            page_count = getattr(im, 'n_frames', 1)
    selected = options.get('pages') or list(range(1, min(page_count, 12) + 1))
    if any(p > page_count for p in selected):
        raise EngineeringError('page_out_of_range', '所选页码超过文件实际页数')
    progress(0, len(selected))
    try:
        for position, number in enumerate(selected):
            if pdf:
                page = pdf[number - 1]
                point_size = list(page.get_size())
                scale = options['dpi'] / 72
                if point_size[0] * point_size[1] * scale * scale > 24_000_000:
                    raise EngineeringError('page_too_large', '图纸像素过大，请降低 DPI 或分割后处理')
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert('RGB')
                bitmap.close()
                page.close()
            else:
                with Image.open(source) as original:
                    original.seek(number - 1)
                    if original.width * original.height > 24_000_000:
                        raise EngineeringError('page_too_large', '图片超过 2400 万像素，请分割后处理')
                    image = original.convert('RGB')
                point_size = None
            import numpy as np
            preview_name = 'page-' + str(number) + '.jpg'
            image.save(source.parent / preview_name, 'JPEG', quality=92)
            raw = list(pipeline.predict(np.asarray(image)[:, :, ::-1]))
            regions = []
            for batch in raw:
                data = batch.json
                if isinstance(data, str):
                    data = json.loads(data)
                data = data.get('res', data)
                texts = data.get('rec_texts', [])
                scores = data.get('rec_scores', [])
                polys = data.get('rec_polys', data.get('dt_polys', []))
                for idx, value in enumerate(texts):
                    polygon = [[float(x), float(y)] for x, y in polys[idx]]
                    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                    region = {'text': str(value), 'score': float(scores[idx]), 'polygon': polygon,
                              'bbox': bbox, 'page': number, 'coordinate_system': 'pixels_top_left',
                              'bbox_normalized': [bbox[0]/image.width, bbox[1]/image.height,
                                                  bbox[2]/image.width, bbox[3]/image.height],
                              'review_status': 'pending', 'is_manufacturing_dimension': False}
                    if point_size:
                        region['bbox_pdf_points'] = [v / scale for v in bbox]
                    regions.append(region)
            pages.append({'page': number, 'width': image.width, 'height': image.height,
                          'preview_filename': preview_name,
                          'dpi': options['dpi'] if pdf else None, 'pdf_size_points': point_size,
                          'regions': regions})
            image.close()
            progress(position + 1, len(selected))
    finally:
        if pdf:
            pdf.close()
    warnings = (['仅处理了前 12 页；其余页可另行选择处理']
                if options.get('pages') is None and page_count > 12 else [])
    if not any(page['regions'] for page in pages):
        warnings.append('没有识别出文字，请检查清晰度或提高 DPI 后重试')
    return {'engine': 'PaddleOCR', 'version': importlib.metadata.version('paddleocr'),
            'runtime_version': importlib.metadata.version('paddlepaddle'), 'models': list(MODEL_NAMES),
            'model_revisions': revisions,
            'page_count': page_count, 'processed_pages': selected, 'pages': pages,
            'region_count': sum(len(p['regions']) for p in pages), 'local_only': True,
            'review_required': True, 'warnings': warnings}


def _cad_oriented_form_hint(shape, valid, solid_count):
    """Optional geometry-only hint; never a cut size or a material assignment."""
    if not valid or solid_count != 1:
        return None
    try:
        import math
        from OCP.Bnd import Bnd_OBB
        from OCP.BRepBndLib import BRepBndLib

        box = Bnd_OBB()
        # Use the source B-rep edges, not display triangulation. This OBB can
        # follow a rotated part but its axes are not the designer's L/W/T axes.
        BRepBndLib.AddOBB_s(shape, box, False, False, False)
        if box.IsVoid():
            return None
        extents = sorted(float(2 * half) for half in
                         (box.XHSize(), box.YHSize(), box.ZHSize()))
        if any(not math.isfinite(value) or value <= 0 for value in extents):
            return None
        short, middle, long = extents
        hint = None
        if short / middle <= 0.10 and middle / long >= 0.10:
            hint = {'kind': 'thin_plate_shape', 'thinness_ratio': round(short / middle, 6),
                    'basis': 'oriented_bbox', 'review_required': True}
        return {'extents_mm': extents, 'form_candidate': hint}
    except Exception:
        # OBB is an optional review aid. A kernel failure must not discard the
        # already validated assembly, exact area/volume or world-axis box.
        return None


def _run_cad(source, options, progress):
    import importlib.metadata
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_LabelSequence, TDF_Label, TDF_Tool
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    doc = TDocStd_Document(TCollection_ExtendedString('KANPACE'))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise EngineeringError('invalid_step', '无法读取 STEP，请检查文件是否完整')
    lengths, angles, solid_angles = (TColStd_SequenceOfAsciiString() for _ in range(3))
    reader.Reader().FileUnits(lengths, angles, solid_angles)
    source_units = [str(lengths.Value(i).ToCString()) for i in range(1, lengths.Length() + 1)]
    # OCCT exchange system unit is millimetres; explicit to avoid session defaults.
    reader.ChangeReader().SetSystemLengthUnit(1.0)
    if not reader.Transfer(doc):
        raise EngineeringError('invalid_step', 'STEP 实体转换失败')
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        raise EngineeringError('empty_geometry', 'STEP 文件没有可检查的几何实体')
    parts, assembly_nodes = [], []
    warnings = []
    if not source_units:
        warnings.append('文件未明确报告源长度单位；请核对导出设置，当前计算统一为毫米')

    def label_id(label):
        value = TCollection_AsciiString()
        TDF_Tool.Entry_s(label, value)
        return str(value.ToCString())

    def label_name(label):
        attr = TDataStd_Name()
        return str(attr.Get().ToExtString()) if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ''

    def count(shape, kind):
        exp = TopExp_Explorer(shape, kind)
        n = 0
        while exp.More():
            n += 1
            exp.Next()
        return n

    def walk(label, parent_path, parent_location, ancestry):
        if len(parts) + len(assembly_nodes) > 5000:
            raise EngineeringError('model_too_large', '模型超过 5000 个节点，请按子装配拆分')
        definition = TDF_Label()
        reference = tool.IsReference_s(label)
        if reference:
            tool.GetReferredShape_s(label, definition)
        else:
            definition = label
        key = label_id(definition)
        if key in ancestry:
            raise EngineeringError('cyclic_assembly', '装配结构存在循环引用')
        path = parent_path + [label_id(label)]
        instance_name = label_name(label)
        # XCAF generates reference labels such as =>[0:1:1:2]. They identify
        # another label rather than a part name; retain actual instance names.
        if reference and re.fullmatch(r'=>\[\d+(?::\d+)*\]', instance_name.strip()):
            instance_name = ''
        name = instance_name or label_name(definition) or '未命名构件'
        if tool.IsAssembly_s(definition):
            node = {'instance_path': '/'.join(path), 'definition_id': key, 'name': name}
            assembly_nodes.append(node)
            children = TDF_LabelSequence()
            tool.GetComponents_s(definition, children)
            location = parent_location.Multiplied(tool.GetLocation_s(label))
            for i in range(1, children.Length() + 1):
                walk(children.Value(i), path, location, ancestry | {key})
            return
        shape = tool.GetShape_s(label)
        if shape.IsNull():
            warnings.append('存在未携带几何的构件：' + name)
            return
        shape = shape.Moved(parent_location)
        valid = bool(BRepCheck_Analyzer(shape).IsValid())
        solids = count(shape, TopAbs_SOLID)
        surface = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, surface)
        volume = GProp_GProps()
        if solids:
            BRepGProp.VolumeProperties_s(shape, volume, True)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        bounds = list(box.Get()) if not box.IsVoid() else None
        oriented = _cad_oriented_form_hint(shape, valid, solids)
        item = {'instance_path': '/'.join(path), 'definition_id': key, 'name': name,
                'valid': valid, 'solid_count': solids, 'face_count': count(shape, TopAbs_FACE),
                'edge_occurrence_count': count(shape, TopAbs_EDGE),
                'surface_area_mm2': float(surface.Mass()),
                'volume_mm3': abs(float(volume.Mass())) if valid and solids else None,
                'bbox_mm': bounds, 'bbox_extents_mm': [bounds[i+3]-bounds[i] for i in range(3)] if bounds else None,
                'bbox_meaning': '世界坐标轴对齐外包尺寸；不是下料尺寸',
                'oriented_bbox_extents_mm': oriented['extents_mm'] if oriented else None,
                'oriented_bbox_meaning': '模型定向外包短/中/长边；不对应已确认长宽厚，也不是下料尺寸',
                'geometry_form_candidate': oriented['form_candidate'] if oriented else None,
                'material': None, 'density': None, 'weight': None,
                'review_status': 'pending', 'is_manufacturing_dimension': False}
        parts.append(item)
        if not valid:
            warnings.append('实体检查未通过：' + name)

    progress(0, roots.Length())
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i), [], TopLoc_Location(), set())
        progress(i, roots.Length())
    if not parts:
        raise EngineeringError('empty_geometry', 'STEP 没有可检查的零件几何')
    counts = {}
    for part in parts:
        counts[part['definition_id']] = counts.get(part['definition_id'], 0) + 1
    return {'engine': 'Open CASCADE / OCP', 'version': importlib.metadata.version('cadquery-ocp'),
            'format': 'STEP', 'source_length_units': source_units, 'output_length_unit': 'mm',
            'root_count': roots.Length(), 'assembly_count': len(assembly_nodes),
            'instance_count': len(parts), 'unique_definition_count': len(counts),
            'definition_instance_counts': counts, 'assemblies': assembly_nodes, 'parts': parts,
            'totals': {'surface_area_mm2': sum(p['surface_area_mm2'] for p in parts),
                       'volume_mm3': sum(p['volume_mm3'] for p in parts) if all(p['volume_mm3'] is not None for p in parts) else None},
            'local_only': True, 'review_required': True, 'warnings': warnings,
            'limits': ['实例计数来自源装配定义，不自动合并同形但不同料号的零件',
                       '面积体积来自源 B-rep，外包尺寸不是下料尺寸',
                       '不恢复 SolidWorks 参数历史，不自动生成工艺或制造 BOM',
                       '本次未解析 PMI、材料密度或重量；空值表示未知']}


def worker(job_dir):
    directory = Path(job_dir).resolve()
    job = _load(directory / 'job.json')
    req = _load(directory / 'request.json')
    def progress(completed, total):
        job.update(status='running', updated_at=_now(), progress={'completed': completed, 'total': total})
        _json(directory / 'job.json', job)
    def timeout(signum, frame):
        raise EngineeringError('timeout', '工程处理超时，请减少页数或拆分模型')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(900)
    try:
        progress(0, None)
        _deny_network()
        source = directory / req['input_name']
        if source.parent != directory or not source.is_file():
            raise EngineeringError('bad_source', '处理文件缺失')
        if req['kind'] == 'ocr':
            result = _run_ocr(source, req['options'], Path(req['model_dir']), progress)
        else:
            result = _run_cad(source, req['options'], progress)
        result['source'] = job['source']
        if req['kind'] == 'ocr' and source.suffix != '.pdf' and job['metadata'].get('source_page'):
            for page in result['pages']:
                page['source_page'] = job['metadata']['source_page']
                page['source_label'] = job['metadata'].get('source_label', '')
                for region in page['regions']:
                    region['source_page'] = job['metadata']['source_page']
        _json(directory / 'result.json', result)
        job.update(status='completed', updated_at=_now())
    except BaseException as exc:
        if isinstance(exc, EngineeringError):
            error = {'code': exc.code, 'message': str(exc)}
        elif isinstance(exc, ImportError):
            error = {'code': 'dependency_missing', 'message': '工程引擎依赖缺失或不兼容，请重新运行安装脚本'}
        else:
            # Traceback stays in the private worker log, no absolute path leaks in API.
            import traceback
            traceback.print_exc()
            error = {'code': 'processing_failed', 'message': '本地引擎未能处理该文件，请检查文件格式或联系管理员查看处理日志'}
        job.update(status='failed', updated_at=_now(), error=error)
    finally:
        signal.alarm(0)
        _json(directory / 'job.json', job)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    if args.probe:
        _deny_network()
        import importlib.metadata as metadata
        versions = {}
        # Probe engines independently; an OCR dependency problem must not hide a
        # working CAD engine. Importing only distribution metadata is not enough.
        try:
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
            assert not BRepPrimAPI_MakeBox(1, 1, 1).Shape().IsNull()
            versions['cadquery-ocp'] = metadata.version('cadquery-ocp')
        except Exception:
            import traceback
            traceback.print_exc()
        # Flush completed CAD evidence before the larger Paddle runtime loads.
        # A later cold-start timeout must not erase a working CAD result.
        print(json.dumps(versions), flush=True)
        try:
            import paddle
            import importlib.util
            import pypdfium2
            from PIL import Image
            assert importlib.util.find_spec('paddleocr') is not None
            assert float(paddle.to_tensor([1.0]).sum()) == 1.0
            versions.update({p: metadata.version(p) for p in
                             ('paddleocr', 'paddlepaddle', 'pypdfium2', 'Pillow')})
        except Exception:
            import traceback
            traceback.print_exc()
        print(json.dumps(versions), flush=True)
        sys.exit(0)
    if not args.worker:
        parser.error('--worker is required')
    worker(args.worker)
