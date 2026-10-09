"""Reviewed whole-project visual sources; never changes engineering approval.

PDF selections point to original, project-owned document pages. External tours
are browser links only: the server never downloads or executes remote content.
"""
from pathlib import Path
import re
from urllib.parse import urlsplit

from kanpace.core.errors import APIError
from drawing_media import render_media
from order_packet import source_bytes


def panorama_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return ''
    value = value.strip()
    try:
        u = urlsplit(value)
        if (u.scheme == 'https' and u.netloc == 'vr.3d66.com'
                and re.fullmatch(r'/vr/index_detail_\d+\.html', u.path)
                and not u.query and not u.fragment):
            return value
    except ValueError:
        pass
    return ''


def media(project, documents):
    docs = {d['id']: d for d in documents if d.get('project_id') == project['id']
            and not any(d.get(k) for k in ('superseded', 'archived', 'demo'))}
    result = []
    for source in project.get('overview_sources', []):
        doc = docs.get(source.get('document_id'))
        page = source.get('page')
        if (not doc or source.get('document_sha256') != doc.get('sha256')
                or Path(doc.get('filename', '')).suffix.lower() != '.pdf'
                or type(page) is not int or not 1 <= page <= doc.get('page_count', 0)):
            continue
        url = f'/api/documents/{doc["id"]}/preview-image?page={page}'
        result.append({'id': f'overview_{doc["id"]}_{page}', 'project_id': project['id'],
                       'document_id': doc['id'], 'document_sha256': doc['sha256'],
                       'kind': '空间效果图', 'scope': 'project', 'source_role': 'overview_pdf_page',
                       'title': f'整体效果 · 第 {page} 页', 'page': page,
                       'source_file': doc.get('relative_path') or doc['filename'],
                       'url': url, 'thumb_url': url + '&thumb=1',
                       'original_url': f'/api/documents/{doc["id"]}/download'})
    return result


def get(store, con, project_id):
    project = store.get(con, 'projects', project_id)
    documents = store.all(con, 'documents', project_id)
    return {'project': project, 'version': project.get('overview_version', 0),
            'media': media(project, documents),
            'candidates': [{k: d.get(k) for k in ('id', 'filename', 'relative_path', 'sha256', 'page_count')}
                           for d in documents if not any(d.get(k) for k in ('superseded', 'archived', 'demo'))
                           and d.get('filename', '').lower().endswith('.pdf') and d.get('page_count', 0) > 0]}


def save(store, con, project_id, data):
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    allowed = {'expected_version', 'document_id', 'document_sha256', 'pages', 'cover_id', 'panorama_url'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise APIError(400, '整体效果设置字段无效')
    version = project.get('overview_version', 0)
    if type(data.get('expected_version')) is not int or data['expected_version'] != version:
        raise APIError(409, '整体效果设置已变化，请重新打开后选择')
    if not any(k in data for k in ('document_id', 'cover_id', 'panorama_url')):
        raise APIError(400, '请选择整体效果来源')
    documents = store.all(con, 'documents', project_id)
    if 'document_id' in data:
        doc = next((d for d in documents if d['id'] == data['document_id']), None)
        if (not doc or any(doc.get(k) for k in ('superseded', 'archived', 'demo'))
                or not doc['filename'].lower().endswith('.pdf')):
            raise APIError(400, '请选择本项目当前版本的 PDF')
        if data.get('document_sha256') != doc.get('sha256'):
            raise APIError(409, 'PDF 已换版，请重新选择效果页')
        pages = data.get('pages')
        if (not isinstance(pages, list) or len(pages) > 100 or len(pages) != len(set(str(p) for p in pages))
                or any(type(p) is not int or not 1 <= p <= doc.get('page_count', 0) for p in pages)):
            raise APIError(400, '请在 PDF 的有效页码范围内选择，最多 100 页')
        source_bytes(store, doc)
        project['overview_sources'] = [s for s in project.get('overview_sources', []) if s.get('document_id') != doc['id']]
        project['overview_sources'].extend({'document_id': doc['id'], 'document_sha256': doc['sha256'], 'page': p} for p in sorted(pages))
    elif 'pages' in data or 'document_sha256' in data:
        raise APIError(400, '页码必须关联到本项目 PDF')
    if 'panorama_url' in data:
        raw = data['panorama_url']
        if raw != '' and not panorama_url(raw):
            raise APIError(400, '请填写有效的 3D 溜溜全景链接（https://vr.3d66.com/vr/index_detail_编号.html）')
        project['overview_panorama'] = panorama_url(raw)
    choices = media(project, documents)
    choices.extend({**render_media(d), 'document_sha256': d['sha256']} for d in documents
                   if d.get('purpose') == 'render' and d.get('image') and d.get('render_scope')!='cabinet'
                   and not any(d.get(k) for k in ('superseded', 'archived', 'demo')))
    cover = next((m for m in choices if m['id'] == data.get('cover_id')), None)
    if 'cover_id' in data and not cover:
        raise APIError(400, '请选择本项目可用的整体效果图作为封面')
    if cover is None:
        current = (project.get('overview_cover') or {}).get('id')
        cover = next((m for m in choices if m['id'] == current), None) or next(iter(choices), None)
    project['overview_cover'] = cover
    project['overview_version'] = version + 1
    store.put(con, 'projects', project)
    store.event(con, project_id, 'project_overview_updated', '更新项目整体效果', overview_version=version+1)
    return get(store, con, project_id)
