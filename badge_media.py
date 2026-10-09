"""Resolve project-owned source images and prepare bounded ESP32 display JPEGs.

This module derives display files only. It never publishes tasks, changes a
project, follows a client URL, or reads arbitrary paths supplied by the client.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import warnings

import drawing_media
from upload_preview import PreviewError, preview_pdf

CANVAS = (1280, 1792)
MAX_BYTES = 180000
_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


class BadgeMediaError(ValueError):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        self.details = None
        super().__init__(message)


def _upload_path(store, doc):
    name = doc.get('storage_name')
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None
    root = (Path(store.data_dir) / 'uploads').resolve()
    try:
        path = (root / name).resolve(strict=True)
        return path if path.parent == root and path.is_file() else None
    except OSError:
        return None


def _entry_path(store, entry, docs):
    url = entry.get('url')
    prefix = '/api/drawing-media/assets/'
    if isinstance(url, str) and url.startswith(prefix):
        return drawing_media.asset_path(store.data_dir, url[len(prefix):])
    match = re.fullmatch(r'/api/documents/([^/]+)/image', url) if isinstance(url, str) else None
    if match and match[1] in docs:
        return _upload_path(store, docs[match[1]])
    return None


def _basename(value):
    return Path(str(value or '').replace('\\', '/')).name


def _task_links(store, con, project_id, task):
    links = {'part_keys': set(), 'documents': set(), 'files': set(), 'pages': set()}
    if not task:
        return links
    source = task.get('source') if isinstance(task.get('source'), dict) else {}
    links['documents'].update(x for x in (source.get('document_ids') or []) if isinstance(x, str))
    for key in ('document_id', 'source_doc_id'):
        if task.get(key):
            links['documents'].add(task[key])
    if source.get('file'):
        links['files'].add(_basename(source['file']))
    parts = {part['id']: part for part in store.all(con, 'parts', project_id)}
    part = parts.get(task.get('part_id'))
    if part:
        links['part_keys'].add(part['id'])
        part_source = part.get('source') if isinstance(part.get('source'), dict) else {}
        for key in ('external_id', 'part_number'):
            value = part_source.get(key)
            if value:
                links['part_keys'].add(value)
        for key in ('document_id', 'source_doc_id'):
            if part.get(key):
                links['documents'].add(part[key])
        for value in (part.get('source_file'), part_source.get('file'), part_source.get('model_file')):
            if value:
                links['files'].add(_basename(value))
        reference = part_source.get('reference')
        if isinstance(reference, dict):
            file = _basename(reference.get('file') or part_source.get('file'))
            if file and isinstance(reference.get('page'), int):
                links['pages'].add((file, reference['page']))
        for evidence in part.get('evidence') or []:
            if not isinstance(evidence, dict):
                continue
            file = _basename(evidence.get('file'))
            if file:
                links['files'].add(file)
                if isinstance(evidence.get('page'), int):
                    links['pages'].add((file, evidence['page']))
    return links


def _linked(entry, links, part_key=None):
    if part_key in links['part_keys']:
        return 'part'
    file = _basename(entry.get('source_file'))
    if (file, entry.get('page')) in links['pages']:
        return 'source_page'
    if entry.get('page') is not None and any(source == file for source, _ in links['pages']):
        return 'project'  # Explicit page evidence does not authorize every PDF page.
    if entry.get('document_id') in links['documents']:
        return 'document'
    if any(identifier in links['documents'] for identifier in entry.get('linked_source_document_ids', ())):
        return 'document'
    if file and file in links['files']:
        return 'source_file'
    return 'project'


def _catalog(store, con, project_id, task_id=None):
    project = store.get(con, 'projects', project_id)
    task = store.get(con, 'tasks', task_id) if task_id else None
    if task and task.get('project_id') != project_id:
        raise BadgeMediaError(409, '所选任务不属于这个项目，请重新选择任务与图纸')
    documents = [doc for doc in store.all(con, 'documents', project_id)
                 if not doc.get('superseded') and not doc.get('archived')]
    docs = {doc['id']: doc for doc in documents}
    candidates, messages = [], []
    try:
        import order_packet
        media = order_packet.project_media(store, con, project_id)
    except (ValueError, AttributeError, TypeError, OSError):
        media = {'parts': {}, 'sources': [], 'renders': []}
        messages.append('项目图片索引无法读取，请重新生成图纸预览；已上传的原图仍可使用')
    links = _task_links(store, con, project_id, task)

    def add(entry, kind, *, part_key=None, path=None, pdf_doc=None):
        # Order packets link an exact page of a registered PDF. Keep that
        # association and render lazily, just like the upload catalogue below.
        doc=docs.get(entry.get('document_id'))
        # Explicit exports from a DWG/SolidWorks original may supply the
        # viewable task page. The original hash must still match; a revised
        # native file must not inherit an old PDF by name or position.
        if doc and isinstance(doc.get('companion_for'), list):
            linked = [source['document_id'] for source in doc['companion_for']
                      if isinstance(source, dict) and isinstance(source.get('document_id'), str)
                      and (original := docs.get(source['document_id']))
                      and original.get('sha256') == source.get('sha256')]
            if linked:
                entry = {**entry, 'linked_source_document_ids': linked}
        page=entry.get('page')
        if (path is None and pdf_doc is None and doc and type(page) is int and page > 0
                and Path(doc.get('filename','')).suffix.lower()=='.pdf'
                and entry.get('url')==f'/api/documents/{doc["id"]}/preview-image?page={page}'):
            source=_upload_path(store,doc)
            if source:
                try:
                    count=doc.get('page_count') or preview_pdf(store.data_dir,doc,source,1)['page_count']
                    if page <= count:path,pdf_doc=source,doc
                except (PreviewError,OSError,KeyError):pass
        path = path or _entry_path(store, entry, docs)
        if not path:
            messages.append(f"{_basename(entry.get('source_file')) or entry.get('title', '图片')}：原图预览不可用，请重新上传或生成预览")
            return
        if pdf_doc:
            identity = 'pdf:' + pdf_doc['sha256'] + ':' + str(entry['page'])
        else:
            identity = drawing_media.content_hash(path)
            if not identity:
                messages.append(f"{_basename(entry.get('source_file')) or '图片'}：图片无法读取，请重新导出 JPG、PNG 或 WebP")
                return
        identifier = hashlib.sha256(('badge-media-v1\0' + project_id + '\0' + kind + '\0' + identity).encode()).hexdigest()
        association = _linked(entry, links, part_key)
        item = {'id': identifier, 'kind': kind, 'title': str(entry.get('title') or _basename(entry.get('source_file')) or ('施工图' if kind == 'drawing' else '效果图')),
                'url': entry.get('url', ''), 'thumb_url': entry.get('thumb_url') or entry.get('url', ''),
                'source_file': _basename(entry.get('source_file')), 'page': entry.get('page'),
                'document_id': entry.get('document_id'), 'width': entry.get('width'), 'height': entry.get('height'),
                'task_id': task_id, 'association': association, 'task_linked': association != 'project', 'task_match': association != 'project',
                'source_kind': entry.get('kind') or ('施工图' if kind == 'drawing' else '效果图'),
                'reference_note': str(entry.get('reference_note') or ''),
                '_path': path, '_pdf_doc': pdf_doc}
        if part_key:
            item['part_key'] = part_key
        candidates.append(item)

    # Explicit part associations rank ahead of general project sources. Product
    # reference thumbnails are not re-labelled as construction drawings.
    for part_key, entries in media.get('parts', {}).items():
        for entry in entries:
            original_kind = str(entry.get('kind') or '')
            if '效果图' in original_kind:
                add(entry, 'render', part_key=part_key)
            elif any(word in original_kind for word in ('施工图', '工程图', '加工图')):
                add(entry, 'drawing', part_key=part_key)
    for entry in media.get('sources', []):
        original_kind = str(entry.get('kind') or '')
        if any(word in original_kind for word in ('施工图', '工程图', '加工图')):
            add(entry, 'drawing')
    for entry in media.get('renders', []):
        add(entry, 'render')

    # Registered uploads are confined to the uploads directory. For a PDF,
    # validate/render page 1 once to obtain its page count; other pages are
    # rendered only when selected for delivery.
    for doc in documents:
        extension = Path(doc.get('filename', '')).suffix.lower()
        if extension not in _IMAGE_EXTENSIONS | {'.pdf'}:
            continue
        source = _upload_path(store, doc)
        if not source:
            messages.append(f"{_basename(doc.get('filename'))}：上传文件不存在，请重新上传")
            continue
        kind = 'render' if doc.get('purpose') == 'render' else 'drawing'
        if extension in _IMAGE_EXTENSIONS:
            if doc.get('purpose') == 'render' and doc.get('image'):
                # Also register directly so a damaged derived manifest cannot
                # hide a valid upload. Exact pixel keys merge this with media.
                add(drawing_media.render_media(doc), kind, path=source)
                continue
            add({'title': Path(doc['filename']).stem, 'source_file': doc['filename'], 'document_id': doc['id'],
                 'url': '/api/documents/' + doc['id'] + '/badge-image'}, kind, path=source)
            continue
        try:
            preview = preview_pdf(store.data_dir, doc, source, 1)
        except (PreviewError, OSError, KeyError) as exc:
            messages.append(f"{_basename(doc.get('filename'))}：{exc}")
            continue
        for page in range(1, preview['page_count'] + 1):
            url = '/api/documents/' + doc['id'] + '/preview-image?page=' + str(page)
            add({'title': Path(doc['filename']).stem + f' · 第 {page} 页', 'source_file': doc['filename'],
                 'document_id': doc['id'], 'page': page, 'url': url, 'thumb_url': url + '&thumb=1'},
                kind, path=source, pdf_doc=doc)

    ranks = {'part': 0, 'source_page': 0, 'document': 1, 'source_file': 2, 'project': 3}
    candidates.sort(key=lambda item: (ranks[item['association']], item['kind'] != 'drawing'))
    items, seen = [], set()
    for item in candidates:
        if item['id'] in seen:
            continue
        seen.add(item['id'])
        items.append(item)
    for kind, label in [('drawing', '施工图'), ('render', '效果图')]:
        if not any(item['kind'] == kind for item in items):
            messages.append(f'这个项目尚无可发送的{label}')
    return {'project_id': project_id, 'project_name': project.get('name') or project.get('title') or '',
            'revision': project.get('revision', 0), 'task_id': task_id, 'items': items,
            'warnings': list(dict.fromkeys(messages))}


def catalog(store, con, project_id, task_id=None):
    """Return project-owned, de-duplicated candidates; no private path is public."""
    result = _catalog(store, con, project_id, task_id)
    result['items'] = [{key: value for key, value in item.items() if not key.startswith('_')} for item in result['items']]
    return result


def _jpeg(path, max_bytes=MAX_BYTES):
    try:
        from PIL import Image, ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as source:
                width, height = source.size
                if source.format not in ('JPEG', 'PNG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                    raise BadgeMediaError(422, '工牌图片仅支持 JPG、PNG、WebP 静态图片')
                if min(width, height) <= 0 or max(width, height) > 20000 or width * height > 36000000:
                    raise BadgeMediaError(422, '图片尺寸过大，请导出单边不超过 20000 像素、总计不超过 3600 万像素的图片')
                source.load()
                corrected = ImageOps.exif_transpose(source).convert('RGBA')
                source_size = corrected.size
                fitted = ImageOps.contain(corrected, CANVAS, method=Image.Resampling.LANCZOS)
                canvas = Image.new('RGB', CANVAS, 'white')
                canvas.paste(fitted, ((CANVAS[0] - fitted.width) // 2, (CANVAS[1] - fitted.height) // 2), fitted)
        for quality in (90, 85, 80, 75, 70, 65, 60, 50, 40, 30, 20, 10, 5, 1):
            output = io.BytesIO()
            canvas.save(output, format='JPEG', quality=quality, subsampling=2, optimize=True, progressive=False)
            encoded = output.getvalue()
            if len(encoded) <= max_bytes:
                return encoded, quality, source_size, 1.0
        # Rare high-entropy images can exceed the cap even at JPEG quality 1.
        # Reduce spatial detail while retaining the entire picture and the
        # exact decoder canvas. No crop or replacement imagery is introduced.
        for detail_scale in (0.75, 0.5, 0.375, 0.25):
            smaller = canvas.resize((round(CANVAS[0] * detail_scale), round(CANVAS[1] * detail_scale)), Image.Resampling.LANCZOS)
            reduced = smaller.resize(CANVAS, Image.Resampling.BILINEAR)
            for quality in (70, 50, 30, 10, 1):
                output = io.BytesIO()
                reduced.save(output, format='JPEG', quality=quality, subsampling=2, optimize=True, progressive=False)
                encoded = output.getvalue()
                if len(encoded) <= max_bytes:
                    return encoded, quality, source_size, detail_scale
        raise BadgeMediaError(422, '图片无法压缩到工牌容量内，请导出更简洁的 JPG 后重试')
    except BadgeMediaError:
        raise
    except ImportError as exc:
        raise BadgeMediaError(503, '本机缺少 Pillow 图片组件，请运行 setup_media.py 后重启服务') from exc
    except Exception as exc:
        raise BadgeMediaError(422, '图片无法完整读取，请重新导出 JPG、PNG 或 WebP 后重试') from exc


def automatic_selection(result, max_images=2):
    """Only task-associated engineering views and this project's appearance views."""
    drawings = [item for item in result['items'] if item['kind'] == 'drawing' and item.get('task_match')]
    renders = [item for item in result['items'] if item['kind'] == 'render']
    ordered = drawings[:1] + renders[:1] + drawings[1:] + renders[1:]
    if max_images <= 2:
        selected = drawings[:1] + renders[:1]
    else:
        selected = ordered[:max_images]
    warnings = list(result.get('warnings', []))
    omitted = len(ordered) - len(selected)
    if omitted:
        warnings.append(f'胸牌本次最多接收 {max_images} 张，还有 {omitted} 张相关图片保留在 Web 查看')
    if not drawings:
        warnings.append('未找到已关联本任务的施工／工程图，不能用其他部件图代替')
    return {'asset_ids': [item['id'] for item in selected], 'selected_count': len(selected),
            'available_count': len(ordered), 'omitted_count': omitted, 'warnings': list(dict.fromkeys(warnings))}


def prepare(store, con, project_id, asset_ids, task_id=None, *, max_images=2, max_gallery_bytes=None):
    """Derive bounded JPEGs; gallery limits are negotiated with actual firmware."""
    if type(max_images) is not int or not 1 <= max_images <= 6:
        raise BadgeMediaError(400, '图片容量必须为 1 至 6 张')
    if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= max_images or any(not isinstance(value, str) for value in asset_ids):
        raise BadgeMediaError(400, f'请选择 1 至 {max_images} 张图片')
    if len(set(asset_ids)) != len(asset_ids):
        raise BadgeMediaError(400, '同一张图片不能重复发送')
    result = _catalog(store, con, project_id, task_id)
    registered = {item['id']: item for item in result['items']}
    if any(identifier not in registered for identifier in asset_ids):
        raise BadgeMediaError(409, '所选图片不属于当前项目或已经更新，请刷新图片列表后重选')
    selected = [registered[identifier] for identifier in asset_ids]
    if max_images <= 2 and len({item['kind'] for item in selected}) != len(selected):
        raise BadgeMediaError(400, '施工图和效果图各最多发送 1 张，请分别选择')
    budget = MAX_BYTES if max_gallery_bytes is None else min(MAX_BYTES, int(max_gallery_bytes) // len(selected))
    if budget < 20000:
        raise BadgeMediaError(409, '胸牌图库空间不足，无法保留可读图片')
    images = []
    for item in selected:
        source = item['_path']
        if item['_pdf_doc']:
            try:
                preview = preview_pdf(store.data_dir, item['_pdf_doc'], source, item['page'])
                source = drawing_media.asset_path(store.data_dir, preview['url'].rsplit('/', 1)[-1])
            except (PreviewError, OSError) as exc:
                raise BadgeMediaError(422, f"{item['source_file']} 第 {item['page']} 页：{exc}") from exc
            if source is None:
                raise BadgeMediaError(422, '所选施工图无法生成预览，请重新导出 PDF 后重试')
        encoded, quality, original_size, detail_scale = _jpeg(source, budget)
        images.append({'id': item['id'], 'kind': item['kind'], 'title': item['title'],
                       'source_file': item['source_file'], 'source_page': item['page'],
                       'width': CANVAS[0], 'height': CANVAS[1], 'source_width': original_size[0], 'source_height': original_size[1],
                       'sha256': hashlib.sha256(encoded).hexdigest(), 'size': len(encoded), 'quality': quality, 'detail_scale': detail_scale,
                       'bytes': encoded, 'association': item['association'], 'document_id': item['document_id'],
                       'reference_note': item['reference_note']})
    return {key: result[key] for key in ('project_id', 'project_name', 'revision', 'task_id')} | {'images': images}
