"""Authenticated loopback Docling CPU service; no implicit model downloads.

The default StandardPdfPipeline uses local layout, OCR and table models. Readiness
requires verified local files, exact package version, model initialization and
real conversion self-tests. Boundary tests do not claim model verification.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading

PINNED_DOCLING = '2.133.0'
MAX_INPUT = 100 * 1024 * 1024
MAX_BODY = 140 * 1024 * 1024
MAX_REGIONS = 20000


class WorkerError(ValueError):
    pass


def trusted_file(value):
    if not isinstance(value, str):
        raise WorkerError('配置路径需要绝对路径')
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise WorkerError('配置文件不存在或不安全')
    return path


def load_config(path):
    config = json.loads(trusted_file(str(path)).read_text())
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise WorkerError('worker配置schema无效')
    if config.get('engine_version') != PINNED_DOCLING:
        raise WorkerError('需要固定Docling ' + PINNED_DOCLING)
    if not isinstance(config.get('license'), str) or not config['license']:
        raise WorkerError('需要已审查的组件许可证清单标识')
    env = config.get('token_env', 'KANPACE_DOCLING_WORKER_TOKEN')
    if not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}', env):
        raise WorkerError('凭据环境变量名无效')
    token = os.environ.get(env, '')
    if len(token) < 32:
        raise WorkerError('worker需要至少32字符的固定秘密token')
    root = Path(config.get('artifacts_path', ''))
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise WorkerError('显式offline artifacts_path不存在或不安全')
    manifest_path = trusted_file(config.get('model_manifest_path'))
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.get('model_revision'):
        raise WorkerError('模型manifest revision不匹配')
    manifest = json.loads(raw)
    files = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(files, list) or not files or len(files) > 10000:
        raise WorkerError('模型manifest需要有限文件清单')
    declared = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not re.fullmatch(r'[0-9a-f]{64}', str(entry.get('sha256', ''))):
            raise WorkerError('模型文件清单无效')
        rel = Path(entry['path'])
        candidate = root / rel
        if rel.is_absolute() or '..' in rel.parts or candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()) or not candidate.is_file():
            raise WorkerError('模型文件路径不安全或缺失')
        if entry['path'] in declared:
            raise WorkerError('模型manifest存在重复文件')
        digest = hashlib.sha256()
        with candidate.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != entry['sha256']:
            raise WorkerError('模型文件哈希不一致')
        declared[entry['path']] = str(candidate)
    actual = set()
    for candidate in root.rglob('*'):
        if candidate.is_symlink():
            raise WorkerError('offline模型目录不能包含符号链接')
        if candidate.is_file():
            actual.add(candidate.relative_to(root).as_posix())
    if actual != set(declared):
        raise WorkerError('offline目录存在未登记或缺失文件')
    ocr = config.get('ocr')
    if not isinstance(ocr, dict) or any(ocr.get(k) not in declared for k in ('det_model_path', 'rec_model_path', 'cls_model_path', 'rec_keys_path')):
        raise WorkerError('OCR det/rec/cls/keys必须为manifest登记的本地文件')
    config['_ocr_paths'] = {k: declared[ocr[k]] for k in ('det_model_path', 'rec_model_path', 'cls_model_path', 'rec_keys_path')}
    config['_token'] = token
    return config


def top_left_bbox(bbox, size):
    """Docling PyPdfium provenance is already rotated display frame.

    Do not rotate it again. Convert only BOTTOMLEFT to TOPLEFT, per docling-core
    BoundingBox.to_top_left_origin, then fail on invalid/unbounded coordinates.
    """
    if not isinstance(bbox, dict) or not isinstance(size, (list, tuple)) or len(size) != 2:
        raise WorkerError('缺少可验证bbox')
    values = [bbox.get(k) for k in ('l', 't', 'r', 'b')]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise WorkerError('非有限bbox')
    left, top, right, bottom = values
    if bbox.get('coord_origin') == 'BOTTOMLEFT':
        top, bottom = size[1] - top, size[1] - bottom
    elif bbox.get('coord_origin') != 'TOPLEFT':
        raise WorkerError('无法核实bbox origin')
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        raise WorkerError('bbox无正面积或超出原页，不猜测/裁造框')
    return [left, top, right, bottom]


def selftest_pdf(rotate=0):
    stream = b'BT /F1 18 Tf 40 90 Td (KANPACESELFTEST 600 450) Tj ET'
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Rotate {rotate} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>'.encode(),
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    output, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for index, value in enumerate(objs, 1):
        offsets.append(len(output)); output.extend(f'{index} 0 obj\n'.encode() + value + b'\nendobj\n')
    start = len(output); output.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(output)


class Runtime:
    def __init__(self, config):
        self.config, self.converter, self.ready = config, None, False
        self.reason, self.selftest = 'models_not_loaded', None
        self.lock = threading.Lock()

    def health(self):
        return {'ready': self.ready, 'schema_version': 'document_evidence.v1',
                'engine_version': self.config['engine_version'], 'model_revision': self.config['model_revision'],
                'reason': self.reason, 'selftest': self.selftest, 'formats': ['pdf'], 'device': 'cpu'}

    def initialize(self):
        self.ready = False
        try:
            if importlib.metadata.version('docling') != PINNED_DOCLING:
                raise WorkerError('Docling安装版本与固定版本不一致')
            os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', DOCLING_ARTIFACTS_PATH=self.config['artifacts_path'])
            # This dedicated worker never needs outbound connections. Enforce
            # offline operation even if a dependency ignores offline flags.
            def deny_outbound(*_args, **_kwargs):
                raise WorkerError('worker outbound network is disabled')
            socket.socket.connect = deny_outbound
            socket.socket.connect_ex = deny_outbound
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, AcceleratorOptions, AcceleratorDevice, TableFormerMode
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend, _rect_to_display_frame
            # A verified local model directory is mandatory. The backend symbol
            # above guarantees this pinned release contains the rotation fix.
            options = PdfPipelineOptions(artifacts_path=Path(self.config['artifacts_path']), do_ocr=True,
                do_table_structure=True, generate_page_images=True, images_scale=1.0,
                enable_remote_services=False, document_timeout=120)
            options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4)
            options.ocr_options = RapidOcrOptions(backend='onnxruntime', lang=['ch'],
                use_det=True, use_rec=True, use_cls=True, **self.config['_ocr_paths'])
            options.table_structure_options.mode = TableFormerMode.ACCURATE
            options.table_structure_options.do_cell_matching = True
            self.converter = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={InputFormat.PDF:
                PdfFormatOption(backend=PyPdfiumDocumentBackend, pipeline_options=options)})
            self.converter.initialize_pipeline(InputFormat.PDF)
            checks = []
            for rotation in (0, 90):
                raw = selftest_pdf(rotation)
                with tempfile.TemporaryDirectory(prefix='kanpace-docling-selftest-') as temp:
                    path = Path(temp) / 'selftest.pdf'; path.write_bytes(raw)
                    geometry = self.pdf_geometry(path, [1])
                    result = self.convert(path, geometry)
                observed = ' '.join(r['text_raw'] for p in result['pages'] for r in p['regions'])
                if 'KANPACESELFTEST' not in observed.replace(' ', ''):
                    raise WorkerError('真实PDF selftest未识别固定原文字')
                checks.append({'rotation': rotation, 'regions': sum(len(p['regions']) for p in result['pages'])})
            self.selftest, self.reason, self.ready = checks, None, True
        except Exception as exc:
            self.reason = 'initialization_failed:' + type(exc).__name__
            self.converter = None
            raise

    def pdf_geometry(self, path, numbers):
        import pypdfium2 as pdfium
        result = []
        pdf = pdfium.PdfDocument(str(path))
        try:
            for number in numbers:
                if type(number) is not int or not 1 <= number <= len(pdf):
                    raise WorkerError('页码超出范围')
                page = pdf[number - 1]
                try:
                    media, crop = list(page.get_mediabox()), list(page.get_cropbox())
                    # A cropped/offset page requires an independently validated
                    # transform. Until available, reject rather than guess.
                    if media != crop or media[:2] != [0, 0]:
                        raise WorkerError('非平凡CropBox/MediaBox映射尚未验证')
                    size, rotation = list(page.get_size()), page.get_rotation()
                    bitmap = page.render(scale=1, rotation=0)
                    try:
                        # Inspect the actual native render dimensions. This also
                        # works with PDFium 4.30 before Pillow/model installation.
                        if any(abs(a - b) > 1 for a, b in zip((bitmap.width, bitmap.height), size)):
                            raise WorkerError('PDFium render与原页显示大小不一致')
                    finally:
                        bitmap.close()
                    result.append({'page': number, 'page_size_pdf_points': size, 'rotation': rotation,
                        'mediabox': media, 'cropbox': crop, 'crop_to_page_transform': None,
                        'canonical_origin': 'top_left', 'coordinate_system': 'pdf_points', 'coordinate_space': 'pdf_media_display_page'})
                finally:
                    page.close()
        finally:
            pdf.close()
        return result

    def convert(self, path, geometry):
        if self.converter is None:
            raise WorkerError('完整pipeline未加载')
        pages = {g['page']: {**g, 'regions': []} for g in geometry}
        tables = []
        for number in pages:
            result = self.converter.convert(path, max_file_size=MAX_INPUT, max_num_pages=10000, page_range=(number, number), raises_on_error=True)
            status = getattr(result.status, 'value', str(result.status))
            if status != 'success':
                raise WorkerError('Docling返回部分失败，不能宣称完整结果')
            document = result.document.export_to_dict()
            doc_page = document.get('pages', {}).get(str(number), document.get('pages', {}).get(number))
            if not isinstance(doc_page, dict):
                raise WorkerError('Docling原页身份丢失')
            size = pages[number]['page_size_pdf_points']
            reported = doc_page.get('size', {})
            if any(abs(reported.get(k, -1) - size[i]) > .01 for i, k in enumerate(('width', 'height'))):
                raise WorkerError('Docling页尺寸与PDFium显示页不一致')
            refs = pages[number]['regions']
            for item in document.get('texts', []):
                text = item.get('orig', item.get('text'))
                provs = item.get('prov', [])
                if not isinstance(text, str) or len(text) > 20000 or not provs:
                    raise WorkerError('文字缺少原文/来源定位')
                for prov in provs:
                    if prov.get('page_no') != number:
                        raise WorkerError('Docling文字原页不一致')
                    span = prov.get('charspan')
                    if len(provs) > 1:
                        if item.get('orig', text) != item.get('text', text):
                            raise WorkerError('多区域原文与规范化文本不同，不能猜测charspan')
                        if not isinstance(span, (list, tuple)) or len(span) != 2 or not 0 <= span[0] <= span[1] <= len(text):
                            raise WorkerError('多区域文字缺少合法charspan')
                        raw = text[span[0]:span[1]]
                    else:
                        raw = text
                    refs.append({'text_raw': raw, 'bbox_pdf_points': top_left_bbox(prov.get('bbox'), size)})
            for index, table in enumerate(document.get('tables', [])):
                provs = table.get('prov', [])
                if len(provs) != 1 or provs[0].get('page_no') != number:
                    raise WorkerError('多页表格单元格映射需人工核验')
                cells = []
                for cell in table.get('data', {}).get('table_cells', []):
                    text = cell.get('text')
                    if not isinstance(text, str) or len(text) > 20000:
                        raise WorkerError('单元格原文无效')
                    bbox = cell.get('bbox')
                    if bbox is None:
                        raise WorkerError('单元格缺bbox，不能制造表格关联证据')
                    region_index = len(refs)
                    refs.append({'text_raw': text, 'bbox_pdf_points': top_left_bbox(bbox, size)})
                    row, col = cell.get('start_row_offset_idx'), cell.get('start_col_offset_idx')
                    if type(row) is not int or type(col) is not int or row < 0 or col < 0:
                        raise WorkerError('单元格行列无效')
                    cells.append({'row': row + 1, 'column': col + 1, 'row_span': cell.get('row_span', 1),
                                  'col_span': cell.get('col_span', 1), 'text_raw': text, 'region_indices': [region_index]})
                tables.append({'id': f'table_{number}_{index}', 'page': number, 'cells': cells})
            if sum(len(p['regions']) for p in pages.values()) > MAX_REGIONS:
                raise WorkerError('区域数量超过安全限制')
        return {'pages': list(pages.values()), 'tables': tables}

    def recognize(self, payload):
        if not self.ready:
            raise WorkerError('models_not_ready')
        if not isinstance(payload, dict) or payload.get('protocol') != 'kanpace-document-v1' or payload.get('required_engine_version') != self.config['engine_version'] or payload.get('required_model_revision') != self.config['model_revision']:
            raise WorkerError('协议/固定版本不一致')
        source, incoming = payload.get('source'), payload.get('input')
        if not isinstance(source, dict) or not isinstance(incoming, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(source.get('source_sha256', ''))):
            raise WorkerError('来源身份无效')
        if not isinstance(incoming.get('filename'), str) or Path(incoming['filename']).suffix.lower() != '.pdf' or not isinstance(incoming.get('content_base64'), str):
            raise WorkerError('worker仅接受PDF字节，不接受URL或路径')
        try:
            raw = base64.b64decode(incoming['content_base64'], validate=True)
        except ValueError:
            raise WorkerError('base64无效')
        if not raw or len(raw) > MAX_INPUT or hashlib.sha256(raw).hexdigest() != source['source_sha256']:
            raise WorkerError('原件字节哈希/大小无效')
        original = payload.get('source_geometry')
        if not isinstance(original, list) or not 1 <= len(original) <= 100 or any(not isinstance(g, dict) for g in original):
            raise WorkerError('缺少原页几何')
        numbers = [g.get('page') for g in original]
        if len(set(numbers)) != len(numbers):
            raise WorkerError('原页重复')
        with self.lock, tempfile.TemporaryDirectory(prefix='kanpace-docling-input-') as temp:
            path = Path(temp) / 'source.pdf'; path.write_bytes(raw)
            actual = self.pdf_geometry(path, numbers)
            for a, b in zip(actual, original):
                if any(a[k] != b.get(k) for k in ('page', 'rotation', 'canonical_origin', 'coordinate_system', 'coordinate_space')):
                    raise WorkerError('请求几何与独立PDFium原件坐标空间不一致')
                for key in ('page_size_pdf_points', 'mediabox', 'cropbox'):
                    if not isinstance(b.get(key), list) or len(a[key]) != len(b[key]) or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v - x) > .01 for x, v in zip(a[key], b[key])):
                        raise WorkerError('请求几何与独立PDFium原件页面框不一致')
            converted = self.convert(path, original)
        return {'schema_version': 'document_evidence.v1', 'source': source, 'engine_version': self.config['engine_version'],
                'model_revision': self.config['model_revision'], **converted}


def create_server(runtime, host='127.0.0.1', port=8091):
    if host != '127.0.0.1':
        raise WorkerError('worker只允许127.0.0.1；云网关必须通过显式认证通道接入')
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def authorized(self):
            value = self.headers.get('Authorization', '')
            if not hmac.compare_digest(value, 'Bearer ' + runtime.config['_token']):
                self.reply(401, {'error': 'worker_auth_required'}); return False
            return True
        def do_GET(self):
            if self.authorized():
                self.reply(200, runtime.health()) if self.path == '/health' else self.reply(404, {'error': 'not_found'})
        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/recognize':
                return self.reply(404, {'error': 'not_found'})
            try:
                if self.headers.get('Transfer-Encoding') or not self.headers.get('Content-Type', '').startswith('application/json'):
                    raise WorkerError('只接受定长JSON')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    return self.reply(413, {'error': 'input_size_limit'})
                self.connection.settimeout(15)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise WorkerError('请求不完整')
                payload = json.loads(raw)
                self.reply(200, runtime.recognize(payload))
            except (WorkerError, ValueError, TypeError, KeyError):
                self.reply(422 if runtime.ready else 503, {'error': 'invalid_or_unready_evidence'})
            except Exception:
                self.reply(500, {'error': 'conversion_failed'})
        def log_message(self, *_):
            pass  # No source filenames, bodies or secrets in access logs.
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--port', type=int, default=8091)
    parser.add_argument('--host', default='127.0.0.1'); parser.add_argument('--drycheck', action='store_true')
    parser.add_argument('--no-autoload', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        installed = importlib.util.find_spec('docling') is not None and importlib.metadata.version('docling') == PINNED_DOCLING
        if args.drycheck:
            print(json.dumps({'config_valid': True, 'package_pinned': installed, 'ready': False, 'models_loaded': False}))
            return 0 if installed else 2
        runtime = Runtime(config)
        if not args.no_autoload:
            runtime.initialize()
        server = create_server(runtime, args.host, args.port)
        print(json.dumps(runtime.health()), flush=True)
        server.serve_forever()
    except Exception as exc:
        print(json.dumps({'ready': False, 'error': type(exc).__name__, 'reason': str(exc)[:300]}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
