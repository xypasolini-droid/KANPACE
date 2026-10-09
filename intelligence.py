"""Business boundary for local engineering engines and reviewable evidence.

HTTP callers supply registered identifiers, never filesystem paths. Results and
derived evidence remain in the current Store; no task is released by an engine.
"""
from pathlib import Path
import hashlib
import json
import re

import engineering_engines
import cad_split_proposals
import drawing_match
from drawing_media import project_media, asset_path
from kanpace.core.errors import APIError


class IntelligenceError(ValueError):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


MAX_CROSS_SOURCE_OCR_JOBS = 48
MAX_CROSS_SOURCE_OCR_REGIONS = 20_000


def jobs(store):
    return engineering_engines.EngineeringJobs(store.data_dir)


def sources(store, con, project_id, private=False):
    store.get(con, 'projects', project_id)
    docs = store.all(con, 'documents', project_id)
    result = []
    for d in docs:
        if d.get('purpose') == 'render' or d.get('superseded'):
            continue
        suffix = Path(d.get('filename', '')).suffix.lower()
        kind = 'cad' if suffix in ('.step', '.stp') else 'ocr' if suffix in ('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tiff', '.tif', '.bmp') else None
        name = d.get('storage_name')
        if not kind or not isinstance(name, str) or Path(name).name != name:
            continue
        path = store.uploads / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != store.uploads.resolve():
            continue
        row = {'id': 'doc:' + d['id'], 'kind': kind, 'filename': d['filename'],
               'document_id': d['id'], 'source_label': d['filename'], 'source_page': None}
        if private: row['_path'] = path
        result.append(row)
    seen = set()
    for e in project_media(store.data_dir, project_id, docs).get('sources', []):
        media_kind = str(e.get('kind', ''))
        if any(label in media_kind for label in ('效果', '产品参考', '共用参考')) or e.get('purpose') == 'render':
            continue
        url = e.get('url', '')
        prefix = '/api/drawing-media/assets/'
        if not url.startswith(prefix):
            continue
        name = url[len(prefix):]
        path = asset_path(store.data_dir, name)
        if path is None or name in seen: continue
        seen.add(name)
        label = str(e.get('source_file') or e.get('title') or '施工图')
        page = e.get('page')
        row = {'id': 'asset:' + name, 'kind': 'ocr', 'filename': name,
               'source_label': label, 'source_page': page, 'preview_url': url,
               'display_name': label + (f' · 第 {page} 页' if page else '')}
        if private: row['_path'] = path
        result.append(row)
    return sorted(result, key=lambda row: (row['source_label'], row['source_page'] or 0))


def project_jobs(store, project_id):
    return [j for j in jobs(store).list() if j.get('metadata', {}).get('project_id') == project_id]


def get_job(store, con, project_id, job_id):
    store.get(con, 'projects', project_id)
    if not isinstance(job_id, str) or not re.fullmatch(r'eng_[0-9a-f]{32}', job_id):
        raise IntelligenceError(404, '此项目没有这条识别记录')
    try:
        job = jobs(store).get(job_id)
    except (engineering_engines.EngineeringError, FileNotFoundError):
        raise IntelligenceError(404, '此项目没有这条识别记录')
    if job.get('metadata', {}).get('project_id') != project_id:
        raise IntelligenceError(404, '此项目没有这条识别记录')
    return job


def submit(store, con, project_id, data):
    project = store.get(con, 'projects', project_id)
    store.require_project_open(project)
    if type(data.get('expected_revision')) is not int or data['expected_revision'] != project['revision']:
        raise IntelligenceError(409, '工程版本已变化，请刷新后重新选择资料')
    source = next((s for s in sources(store, con, project_id, True) if s['id'] == data.get('source_id')), None)
    if source is None:
        raise IntelligenceError(404, '请先上传本项目的施工图或 STEP 模型')
    if data.get('kind') != source['kind']:
        raise IntelligenceError(400, '处理方式与文件类型不匹配')
    metadata = {k: source[k] for k in ('document_id', 'source_label', 'source_page') if source.get(k) is not None}
    metadata.update(project_id=project_id, revision=project['revision'], source_id=source['id'])
    return jobs(store).submit(source['kind'], source['_path'], source['filename'], data.get('options'), metadata)


def page_image(store, con, project_id, job_id, page_number):
    job = get_job(store, con, project_id, job_id)
    if not str(page_number).isascii() or not str(page_number).isdigit():
        raise IntelligenceError(400, '页码无效')
    page = next((p for p in (job.get('result') or {}).get('pages', []) if p.get('page') == int(page_number)), None)
    name = page.get('preview_filename', '') if page else ''
    if not re.fullmatch(r'page-[0-9]+\.jpg', name):
        raise IntelligenceError(404, '本页预览尚未生成')
    root = store.data_dir / 'engineering-jobs' / job_id
    path = root / name
    if root.is_symlink() or path.is_symlink() or path.resolve().parent != root.resolve() or not path.is_file():
        raise IntelligenceError(404, '预览不存在')
    return path


def _current_job_source(store, con, project_id, job):
    """Recheck today's registered source before a job can author proposals."""
    doc_id = job.get('metadata', {}).get('document_id')
    if doc_id:
        doc = store.get(con, 'documents', doc_id)
        if doc.get('project_id') != project_id or doc.get('superseded') or doc.get('sha256') != job['source']['sha256']:
            raise IntelligenceError(409, '来源文件已变更，请重新识别')
    # A cached drawing page must still belong to the project's current media
    # manifest. A historical job alone cannot re-authorize a removed source.
    current = sources(store, con, project_id, private=True)
    source_id = job.get('metadata', {}).get('source_id') or ('doc:' + doc_id if doc_id else None)
    source = next((s for s in current if s['id'] == source_id), None)
    if source is None:
        raise IntelligenceError(409, '来源文件已变更或移除，请重新识别')
    with source['_path'].open('rb') as stream:
        source_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    if source_hash != job['source']['sha256']:
        raise IntelligenceError(409, '来源文件已变更，请重新识别')
    return doc_id


def proposals(store, con, project_id, job_id):
    job = get_job(store, con, project_id, job_id)
    if job.get('status') != 'completed' or job.get('kind') != 'cad':
        raise IntelligenceError(409, '仅能从处理完成的 STEP 模型生成待核对构件建议')
    _current_job_source(store, con, project_id, job)
    try:
        return cad_split_proposals.build(job)
    except ValueError as exc:
        raise IntelligenceError(422, str(exc)) from exc


def drawing_matches(store, con, project_id, cad_job_id):
    """Link current STEP proposals to current OCR regions without changing parts."""
    snapshot = proposals(store, con, project_id, cad_job_id)
    eligible = []
    excluded_stale = 0
    excluded_unbound = 0
    job_manager = jobs(store)
    region_count = 0
    # list() deliberately returns summaries. Load each validated OCR job's
    # complete result below; passing summaries to the matcher yields no pages.
    for summary in job_manager.list():
        if summary.get('metadata', {}).get('project_id') != project_id \
                or summary.get('kind') != 'ocr' or summary.get('status') != 'completed':
            continue
        metadata = summary.get('metadata') or {}
        source = summary.get('source') or {}
        label = str(metadata.get('source_label') or source.get('filename') or '')
        if drawing_match.is_effect_source(label) or drawing_match.is_effect_source(source.get('filename')):
            continue
        doc_id = metadata.get('document_id')
        # A derived preview asset may remain in a media manifest after the
        # original engineering PDF is replaced. Its own unchanged bytes do not
        # prove the drawing revision is current, so never use it for matching.
        if not doc_id:
            excluded_unbound += 1
            continue
        try:
            doc = store.get(con, 'documents', doc_id)
        except APIError:
            excluded_stale += 1
            continue
        if doc.get('project_id') != project_id or doc.get('purpose', 'drawing') not in ('drawing', 'engineering', 'model'):
            continue
        try:
            _current_job_source(store, con, project_id, summary)
        except (IntelligenceError, APIError):
            excluded_stale += 1
            continue
        if len(eligible) >= MAX_CROSS_SOURCE_OCR_JOBS:
            raise IntelligenceError(422, '本项目当前工程图 OCR 记录过多，请先清理重复识别记录再进行跨源匹配')
        try:
            job = job_manager.get(summary['id'])
        except (engineering_engines.EngineeringError, FileNotFoundError, OSError):
            excluded_stale += 1
            continue
        if job.get('kind') != 'ocr' or job.get('status') != 'completed' \
                or job.get('metadata', {}).get('project_id') != project_id \
                or job.get('source', {}).get('sha256') != source.get('sha256'):
            excluded_stale += 1
            continue
        try:
            _current_job_source(store, con, project_id, job)
        except (IntelligenceError, APIError):
            excluded_stale += 1
            continue
        pages = (job.get('result') or {}).get('pages')
        if not isinstance(pages, list):
            excluded_stale += 1
            continue
        count = sum(len(page.get('regions', [])) for page in pages if isinstance(page, dict)
                    and isinstance(page.get('regions'), list))
        region_count += count
        if region_count > MAX_CROSS_SOURCE_OCR_REGIONS:
            raise IntelligenceError(422, '本项目图纸文字区域超过跨源匹配上限，请按工程文件分批处理')
        eligible.append(job)
    try:
        result = drawing_match.build(snapshot, eligible)
    except ValueError as exc:
        raise IntelligenceError(422, str(exc)) from exc
    result['excluded_stale_ocr_job_count'] = excluded_stale
    result['excluded_unbound_ocr_job_count'] = excluded_unbound
    if excluded_unbound:
        result['warnings'].append('有缓存图页未绑定原始工程文件版本，已排除跨源匹配；请对当前原文件运行文字识别')
    return result


def evidence(store, con, project_id, data):
    ref = data.get('engineering_evidence')
    if not isinstance(ref, dict):
        raise IntelligenceError(400, '请选择识别依据')
    job = get_job(store, con, project_id, ref.get('job_id'))
    if job.get('status') != 'completed':
        raise IntelligenceError(409, '识别未完成，暂不能作为构件依据')
    doc_id = _current_job_source(store, con, project_id, job)
    entries = []
    if job['kind'] == 'ocr':
        selections = ref.get('regions')
        if not isinstance(selections, list) or not 1 <= len(selections) <= 30:
            raise IntelligenceError(400, '请选 1—30 处原图文字作为依据')
        for item in selections:
            if not isinstance(item, dict) or type(item.get('page')) is not int or type(item.get('index')) is not int:
                raise IntelligenceError(400, '文字位置无效')
            p = next((v for v in job['result']['pages'] if v['page'] == item['page']), None)
            if p is None or not 0 <= item['index'] < len(p['regions']):
                raise IntelligenceError(400, '文字位置无效')
            r = p['regions'][item['index']]
            entries.append({k:r.get(k) for k in ('page','text','score','bbox','polygon','bbox_pdf_points')})
    else:
        ps = job['result'].get('parts', [])
        try:
            proposal = cad_split_proposals.selected(cad_split_proposals.build(job),
                                                    ref.get('proposal_id'), ref.get('part_indices'))
        except ValueError as exc:
            raise IntelligenceError(400, str(exc)) from exc
        if ref.get('quantity_confirmed') is not True or ref.get('manufacturing_dimensions_confirmed') is not True:
            raise IntelligenceError(400, '请明确确认订单数量和加工尺寸均已按工程资料核对')
        numeric = {}
        for key in ('quantity', 'length', 'width', 'thickness'):
            value = data.get(key, data.get(key + '_mm'))
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 10_000_000:
                raise IntelligenceError(400, '请填写有效的订单数量和加工尺寸（毫米）')
            numeric[key] = value
        if not float(numeric['quantity']).is_integer():
            raise IntelligenceError(400, '订单数量必须是整件数')
        # Deliberately never copy STEP bbox data into production dimensions.
        entries.extend(ps[index] for index in proposal['instance_indices'])
        proposal_meta = {'id': proposal['id'], 'definition_id': proposal['definition_id'],
                         'instance_indices': proposal['instance_indices'],
                         'instance_paths': proposal['instance_paths'],
                         'suggested_quantity': proposal['suggested_quantity'],
                         'quantity_basis': 'human_confirmed_order_quantity',
                         'manufacturing_dimensions_basis': 'human_confirmed_engineering_drawing',
                         'confirmed_values': numeric}
    result = {'file': job.get('metadata', {}).get('source_label') or job['source']['filename'],
            'reference': ('施工图文字复核' if job['kind']=='ocr' else 'STEP 工程几何核对'),
            'engineering_job_id': job['id'], 'engine': job['result'].get('engine'),
            'sha256': job['source']['sha256'], 'original_page': job.get('metadata', {}).get('source_page'),
            'entries': entries, 'manufacturing_dimensions_confirmed': bool(job['kind'] == 'cad' and proposal_meta)}
    if job['kind'] == 'cad' and proposal_meta:
        result['step_proposal'] = proposal_meta
    return result, doc_id


def create_part(store, con, data):
    pid = data.get('project_id')
    project = store.get(con, 'projects', pid)
    store.require_project_open(project)
    source, doc_id = evidence(store, con, pid, data)
    key = hashlib.sha256(json.dumps({'evidence':source, 'edits':{k:v for k,v in data.items() if k!='expected_revision'}},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    proposal = source.get('step_proposal')
    proposal_key = None
    if proposal:
        proposal_key = hashlib.sha256((str(pid) + '\x1f' + source['sha256'] + '\x1f' + proposal['id']).encode()).hexdigest()
        prior = next((part for part in store.all(con, 'parts', pid)
                      if part.get('engineering_proposal_key') == proposal_key), None)
        if prior:
            if prior.get('archived') or prior.get('engineering_draft_key') != key:
                raise IntelligenceError(409, '这组 STEP 候选已有构件，请打开原构件修改，勿重复导入')
            return prior
    existing = next((p for p in store.all(con, 'parts', pid) if p.get('engineering_draft_key') == key), None)
    if existing: return existing
    if type(data.get('expected_revision')) is not int or data['expected_revision'] != project['revision']:
        raise IntelligenceError(409, '工程版本已变化，请刷新后核对')
    part = store.create_part(con, data)
    source['revision'] = part['revision']
    part.update(source=source, document_id=doc_id, engineering_draft_key=key)
    if proposal_key:
        part['engineering_proposal_key'] = proposal_key
    store.put(con, 'parts', part)
    return part
