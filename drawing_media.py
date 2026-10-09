"""Read derived drawing previews; never expose arbitrary local source paths."""
from __future__ import annotations

import json
import hashlib
import struct
from functools import lru_cache
import re
import io
import warnings
from pathlib import Path

_ASSET_NAME = re.compile(r"[0-9a-f]{64}(?:-thumb)?\.(?:webp|png|jpg)\Z")
_RENDER_FORMATS = {'.jpg': ('JPEG', 'image/jpeg'), '.jpeg': ('JPEG', 'image/jpeg'),
                   '.png': ('PNG', 'image/png'), '.webp': ('WEBP', 'image/webp')}


class RenderImageError(ValueError):
    pass


def validate_render(filename: str, content: bytes) -> dict:
    """Fully decode a bounded still image before registering an inline URL."""
    expected = _RENDER_FORMATS.get(Path(filename).suffix.lower())
    if expected is None:
        raise RenderImageError('效果图仅支持 JPG、PNG、WebP 静态图片')
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError('效果图上传需要本地 Pillow 图片校验组件；请运行 python3 setup_media.py 后重启服务') from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format != expected[0]:
                    raise RenderImageError('图片内容与文件扩展名不一致，请使用原始 JPG、PNG 或 WebP 文件')
                width, height = source.size
                if width <= 0 or height <= 0 or max(width, height) > 20000 or width * height > 36000000:
                    raise RenderImageError('效果图最大支持 3600 万像素，单边不超过 20000 像素')
                if getattr(source, 'n_frames', 1) != 1:
                    raise RenderImageError('请上传静态效果图，不支持动画图片')
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                source.load()
                if source.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
        return {'width': width, 'height': height, 'mime_type': expected[1]}
    except RenderImageError:
        raise
    except Exception as exc:
        raise RenderImageError('图片无法完整读取，请重新导出 JPG、PNG 或 WebP 效果图') from exc


def render_media(doc: dict) -> dict:
    """Public display metadata for a registered project reference image."""
    image_url = '/api/documents/' + doc['id'] + '/image'
    return {'id': doc['id'], 'document_id': doc['id'], 'title': Path(doc['filename']).stem,
            'kind': '柜体效果图' if doc.get('render_scope')=='cabinet' else '效果图',
            'scope': doc.get('render_scope','project'), 'source_file': doc['filename'], 'url': image_url,
            'thumb_url': image_url, 'width': doc['image']['width'], 'height': doc['image']['height']}


@lru_cache(maxsize=2048)
def _pixel_hash_cached(path: str, mtime_ns: int, size: int, ctime_ns: int) -> str | None:
    """Hash decoded display pixels; cache keys change when a local image changes."""
    try:
        from PIL import Image, ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as source:
                width, height = source.size
                if width <= 0 or height <= 0 or max(width, height) > 20000 or width * height > 36000000:
                    return None
                if getattr(source, 'n_frames', 1) != 1:
                    return None
                pixels = ImageOps.exif_transpose(source).convert('RGBA')
                digest = hashlib.sha256(b'KANPACE-RGBA-v1\0' + struct.pack('>II', *pixels.size))
                digest.update(pixels.tobytes())
                return digest.hexdigest()
    except Exception:
        # Missing/corrupt/unsupported media stays separate; never invent a hash.
        return None


def content_hash(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        info = path.stat()
        return _pixel_hash_cached(str(path), info.st_mtime_ns, info.st_size, info.st_ctime_ns)
    except OSError:
        return None


def _entry_path(data_dir: str | Path, entry: dict, documents: dict) -> Path | None:
    url = entry.get('url')
    prefix = '/api/drawing-media/assets/'
    if isinstance(url, str) and url.startswith(prefix):
        return asset_path(data_dir, url[len(prefix):])
    match = re.fullmatch(r'/api/documents/([^/]+)/image', url) if isinstance(url, str) else None
    if not match or match[1] not in documents:
        return None
    doc = documents[match[1]]
    storage_name = doc.get('storage_name')
    if not isinstance(storage_name, str) or Path(storage_name).name != storage_name:
        return None
    root = (Path(data_dir) / 'uploads').resolve()
    try:
        path = (root / storage_name).resolve(strict=True)
        return path if path.parent == root and path.is_file() else None
    except OSError:
        return None


def _attach_hashes(data_dir: str | Path, entries: list, documents: dict) -> list:
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        clean = {key: value for key, value in entry.items() if key != 'content_hash'}
        digest = content_hash(_entry_path(data_dir, clean, documents))
        if digest:
            clean['content_hash'] = digest
        result.append(clean)
    return result


def project_media(data_dir: str | Path, project_id: str, documents: list | None = None) -> dict:
    """Return the generated, read-only media associations for one project."""
    result = {"version": 1, "project_id": project_id, "parts": {}, "sources": [], "renders": []}
    manifest = Path(data_dir) / "drawing-previews" / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        project = data.get("projects", {}).get(project_id, {})
        result["parts"] = project.get("parts", {})
        result["sources"] = project.get("sources", [])
        result["renders"] = project.get("renders", [])
    except (OSError, ValueError, AttributeError):
        pass
    uploaded = [doc for doc in (documents or []) if doc.get('project_id') == project_id
                and doc.get('purpose') == 'render' and not doc.get('superseded') and doc.get('image')]
    uploaded.sort(key=lambda doc: (doc.get('created_at', ''), doc.get('id', '')), reverse=True)
    result['renders'] = [render_media(doc) for doc in uploaded] + result['renders']
    registered = {doc['id']: doc for doc in uploaded}
    result['parts'] = {key: _attach_hashes(data_dir, entries, registered)
                       for key, entries in result['parts'].items() if isinstance(entries, list)}
    for collection in ('sources', 'renders'):
        result[collection] = _attach_hashes(data_dir, result[collection], registered)
    return result


def asset_path(data_dir: str | Path, filename: str) -> Path | None:
    """Resolve only an existing hash-named generated image inside the cache."""
    if not isinstance(filename, str) or not _ASSET_NAME.fullmatch(filename):
        return None
    root = (Path(data_dir) / "drawing-previews" / "assets").resolve()
    candidate = root / filename
    try:
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved
