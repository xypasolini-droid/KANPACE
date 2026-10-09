"""Render registered uploaded PDFs locally; never infer manufacturing facts."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


class PreviewError(ValueError):
    pass


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    candidate = Path('/opt/homebrew/bin') / name
    return str(candidate) if candidate.is_file() else None


def preview_pdf(data_dir, doc, source, page=1):
    if Path(doc['filename']).suffix.lower() != '.pdf':
        raise PreviewError('该文件不能直接预览，请导出 PDF 图纸。')
    source = Path(source)
    with source.open('rb') as stream:
        if b'%PDF-' not in stream.read(1024):
            raise PreviewError('文件不是有效 PDF；原文件已保留，请检查后重新导出。')
    info_tool, render_tool = executable('pdfinfo'), executable('pdftoppm')
    if not info_tool or not render_tool:
        raise PreviewError('本机缺少 PDF 预览工具，请安装 Poppler 后重新查看。原文件已保留。')
    try:
        info = subprocess.run([info_tool, str(source)], capture_output=True, timeout=15, check=False,
                              env={**os.environ, 'LC_ALL': 'C'})
        if info.returncode:
            raise PreviewError('PDF 无法打开，可能已加密或损坏；请导出可打开的 PDF。')
        match = re.search(rb'^Pages:\s*(\d+)', info.stdout, re.M)
        count = int(match.group(1)) if match else 0
        if not 1 <= page <= count:
            raise PreviewError('页码超出图纸范围。')
        assets = Path(data_dir) / 'drawing-previews' / 'assets'
        assets.mkdir(parents=True, exist_ok=True)
        stem = hashlib.sha256(f"upload-pdf-v1:{doc['sha256']}:{page}".encode()).hexdigest()
        full, thumb = assets / (stem + '.jpg'), assets / (stem + '-thumb.jpg')
        if not full.is_file() or not thumb.is_file():
            with tempfile.TemporaryDirectory(prefix='render-', dir=assets) as temp:
                for target, size in [(full, 2400), (thumb, 640)]:
                    if target.is_file():
                        continue
                    prefix = Path(temp) / target.stem
                    result = subprocess.run([render_tool, '-f', str(page), '-l', str(page), '-singlefile',
                                             '-scale-to', str(size), '-jpeg', '-jpegopt', 'quality=88',
                                             str(source), str(prefix)], capture_output=True, timeout=35, check=False)
                    output = prefix.with_suffix('.jpg')
                    if result.returncode or not output.is_file() or output.stat().st_size == 0:
                        raise PreviewError('这一页无法生成预览，请打开原始 PDF 查看。')
                    output.replace(target)
        return {'page_count': count, 'page': page, 'preview_status': 'ready',
                'url': '/api/drawing-media/assets/' + full.name,
                'thumb_url': '/api/drawing-media/assets/' + thumb.name,
                'filename': doc['filename'], 'label': '原始图纸', 'document_id': doc['id']}
    except subprocess.TimeoutExpired:
        raise PreviewError('图纸预览处理超时；原文件已保留，可重试这一页。')
