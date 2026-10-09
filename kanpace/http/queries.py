"""Read routes and static delivery with the existing factory access checks."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit
import analytics
import model_workspace
import planning
import schedule_reference
import operations
import production
import file_exchange
import scheduling
import calibration
import access_control
import langgraph_agent
import factory_instances
import control_platform
import project_sources
import project_overview
import drawing_pipeline_review
import intelligence
import optimization_engines
import badge_media
import order_packet
import workflow_projection
import document_recognition
from drawing_media import project_media, asset_path, validate_render, RenderImageError
from upload_preview import preview_pdf, PreviewError
from device_bridge import DeviceError
from kanpace.core.constants import BASE, ROLES
from kanpace.core.errors import APIError


class QueryRoutes:
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self.validate_host()
            access_control.authorize(self)
            if access_control.handle(self):
                return
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            pieces = [x for x in path.split('/') if x]
            store = self.server.store
            if path == '/api/factory-instances/status':return self.json_response(factory_instances.status(store))
            if path == '/api/workspace':return self.json_response(control_platform.workspace(store, parse_qs(parsed.query).get('factory_id', [None])[0]))
            if path == '/api/industry-templates':return self.json_response(control_platform.industry_library())
            if len(pieces)==4 and pieces[:2]==['api','industry-templates']:
                return self.json_response(control_platform.industry_library(pieces[2],pieces[3]))
            if path == '/api/control':return self.json_response(control_platform.overview(store))
            if len(pieces) == 5 and pieces[:3] == ['api','control','factories'] and pieces[4] == 'config':
                return self.json_response(control_platform.catalog(store, pieces[3], parse_qs(parsed.query).get('factory_id', [''])[0]))
            if path == '/api/device':
                return self.json_response(self.server.device_bridge.snapshot())
            if path == '/api/device/images':
                return self.json_response(self.server.device_bridge.images.snapshot())
            if path == '/api/device/image-status':
                return self.json_response(self.server.device_bridge._usb_rpc('image_status', reply_type='image_ack'))
            if path == '/api/device/wifi-status':
                return self.json_response(self.server.device_bridge.wifi_status())
            if path == '/api/device/deliveries':
                return self.json_response(self.server.device_bridge.deliveries())
            with store.connect() as con:
                if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'workflow':
                    con.execute('PRAGMA query_only=ON')
                    con.execute('BEGIN')
                    return self.json_response(workflow_projection.get(store, con, pieces[2]))
                if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'recognition':
                    return self.json_response(document_recognition.overview(store, con, pieces[2]))
                if len(pieces) == 5 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'recognition':
                    return self.json_response({'job': document_recognition.get_job(store, con, pieces[2], pieces[4])})
                if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'drawing-pipeline':
                    return self.json_response(drawing_pipeline_review.get(store, con, pieces[2]))
                if len(pieces) == 7 and pieces[:2] == ['api','projects'] and pieces[3:5] == ['drawing-pipeline','assets']:
                    content, mime, filename = drawing_pipeline_review.asset(store, con, pieces[2], pieces[5], pieces[6])
                    headers = {'Content-Disposition': 'attachment; filename="' + filename + '"'} if pieces[6] != 'preview' else None
                    return self.send_bytes(200, content, mime, headers)
                if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'dispatch-preview':
                    con.execute('BEGIN')
                    return self.json_response(self.server.project_dispatch.preview(con, pieces[2], parse_qs(parsed.query).get('date', [None])[0]))
                if len(pieces) == 3 and pieces[:2] == ['api', 'project-dispatches']:
                    return self.json_response(self.server.project_dispatch.get(con, pieces[2]))
                if path == '/api/device-bindings':
                    return self.json_response({'bindings': store.all(con, 'device_bindings'), 'devices': self.server.project_dispatch.devices(con)})
                if path == '/api/material-planning':
                    con.execute('BEGIN')
                    import material_requirements
                    query = parse_qs(parsed.query)
                    return self.json_response(material_requirements.build(store, con, project_id=query.get('project_id', [None])[0],
                        factory_type=query.get('factory_type', [None])[0], include_demo=query.get('include_demo', ['0'])[0] == '1'))
                if path == '/api/daily-workflow':
                    query = parse_qs(parsed.query)
                    con.execute('BEGIN')
                    return self.json_response(store.daily_workflow.build(con, query.get('date', [None])[0],
                        query.get('person_id', [None])[0], query.get('project_id', [None])[0], query.get('factory_type', [None])[0]))
                if len(pieces) == 4 and pieces[:3] == ['api', 'daily-workflow', 'labels']:
                    return self.json_response({'label': store.daily_workflow.label(con, pieces[3], parse_qs(parsed.query).get('task_id', [None])[0])})
                if path == '/api/daily-workflow/locations':
                    return self.json_response(store.daily_workflow.locations(con))
                if len(pieces) == 4 and pieces[:3] == ['api', 'daily-workflow', 'locations']:
                    return self.json_response(store.daily_workflow.location(con, pieces[3]))
                if path == '/api/health':
                    return self.json_response({'ok':True,'version':'1.0.0','mode':('isolated_web_factory' if store.instance_id else 'authenticated_web') if getattr(self.server,'web_mode',False) else ('isolated_local_factory' if store.instance_id else 'local_single_workstation'),**({'instance_id':store.instance_id,'authentication_required':True} if store.instance_id else {})})
                if path == '/api/state':
                    return self.json_response(store.state(con))
                if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'overview':
                    return self.json_response(project_overview.get(store, con, pieces[2]))
                if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'sources':
                    return self.json_response(project_sources.get_sources(store, con, pieces[2]))
                if path == '/api/intelligence/status':
                    return self.json_response({'engineering': intelligence.jobs(store).status(),
                                               'optimization': optimization_engines.status(),
                                               'agent': langgraph_agent.status()})
                if len(pieces) >= 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'engineering':
                    project_id = pieces[2]
                    store.get(con, 'projects', project_id)
                    if len(pieces) == 4:
                        return self.json_response({'sources': intelligence.sources(store, con, project_id),
                            'jobs': intelligence.project_jobs(store, project_id)})
                    if len(pieces) == 5:
                        return self.json_response({'job': intelligence.get_job(store, con, project_id, pieces[4])})
                    if len(pieces) == 6 and pieces[5] == 'proposals':
                        return self.json_response(intelligence.proposals(store, con, project_id, pieces[4]))
                    if len(pieces) == 6 and pieces[5] == 'drawing-matches':
                        return self.json_response(intelligence.drawing_matches(store, con, project_id, pieces[4]))
                    if len(pieces) == 7 and pieces[5] == 'pages':
                        preview = intelligence.page_image(store, con, project_id, pieces[4], pieces[6])
                        return self.send_bytes(200, preview.read_bytes(), 'image/jpeg')
                    raise APIError(404, '工程处理记录不存在')
                if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'packing':
                    project = store.get(con, 'projects', pieces[2])
                    return self.json_response({'previews': store.all(con, 'packing_previews', project['id'])[-30:]})
                if path == '/api/exchange/export':
                    query = parse_qs(parsed.query)
                    result = file_exchange.export_data(store, con, query.get('entity_type', ['projects'])[0],
                        format=query.get('format', ['csv'])[0], project_id=query.get('project_id', [None])[0],
                        factory_id=query.get('factory_id', [None])[0], preview_id=query.get('preview_id', [None])[0])
                    return self.send_bytes(200, result['bytes'], result['content_type'],
                        {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(result['filename'])})
                if path == '/api/exchange':
                    return self.json_response(file_exchange.build(store, con))
                if len(pieces) == 3 and pieces[:2] == ['api', 'exchange']:
                    return self.json_response(file_exchange.get_preview(store, con, pieces[2]))
                if path == '/api/scheduling':
                    query = parse_qs(parsed.query)
                    return self.json_response(scheduling.build(store, con, factory_type=query.get('factory_type', [None])[0],
                        include_demo=query.get('include_demo', ['0'])[0] == '1'))
                if path == '/api/calibration':
                    query = parse_qs(parsed.query)
                    return self.json_response(calibration.build(store, con, factory_type=query.get('factory_type', [None])[0],
                        factory_id=query.get('factory_id', [None])[0]))
                if path in ('/api/operations', '/api/production'):
                    query = parse_qs(parsed.query)
                    con.execute('BEGIN')
                    options = {'factory_type': query.get('factory_type', [None])[0], 'include_demo': query.get('include_demo', ['0'])[0] == '1'}
                    if path == '/api/operations':
                        return self.json_response(operations.build(store, con, **options))
                    return self.json_response(production.build(store, con, project_id=query.get('project_id', [None])[0], **options))
                if path == '/api/schedule-reference':
                    query = parse_qs(parsed.query)
                    con.execute('BEGIN')
                    return self.json_response(schedule_reference.get_references(store, con, query.get('source_id', [None])[0], query.get('sheet', [None])[0]))
                if len(pieces) == 4 and pieces[:2] == ['api', 'schedule-reference'] and pieces[3] == 'download':
                    source = schedule_reference.get_source(store, con, pieces[2])
                    original = schedule_reference.registered_path(store, source, 'original_file')
                    mime = ('application/vnd.ms-excel' if source['filename'].lower().endswith('.xls')
                            else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    return self.send_bytes(200, original.read_bytes(), mime,
                        {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(source['filename'])})
                if len(pieces) == 3 and pieces[:2] == ['api', 'planning']:
                    con.execute('BEGIN')
                    return self.json_response(planning.get_plan(store, con, pieces[2]))
                if path == '/api/planning':
                    query = parse_qs(parsed.query)
                    show_demo = query.get('include_demo', ['0'])[0]
                    if show_demo not in ('0', '1'):
                        raise APIError(400, 'include_demo 须为 0 或 1')
                    trade = query.get('trade', [None])[0]
                    if trade and (len(trade) > 40 or not trade.strip()):
                        raise APIError(400, '请选择有效工种')
                    con.execute('BEGIN')
                    return self.json_response(planning.build(store, con, query.get('start', [None])[0],
                        query.get('end', [None])[0], project_id=query.get('project_id', [None])[0],
                        person_id=query.get('person_id', [None])[0], trade=trade, include_demo=show_demo == '1'))
                if path == '/api/analytics':
                    query = parse_qs(parsed.query)
                    project_id = query.get('project_id', [None])[0]
                    trade = query.get('trade', [None])[0]
                    fulfillment_status = query.get('fulfillment_status', [None])[0]
                    if fulfillment_status not in (None, 'all', 'active', 'closed', 'completed', 'shipped'):
                        raise APIError(400, '无效项目交付状态筛选')
                    raw_days = query.get('days', ['14'])[0]
                    if len(raw_days) > 3 or not raw_days.isascii() or not raw_days.isdigit() or not 1 <= int(raw_days) <= 366:
                        raise APIError(400, '统计天数必须为 1 到 366 的整数')
                    if project_id:
                        store.get(con, 'projects', project_id)
                    if trade and trade not in ROLES:
                        raise APIError(400, '请选择有效工种', ROLES)
                    con.execute('BEGIN')
                    return self.json_response(analytics.build_analytics(store.state(con), project_id=project_id, trade=trade, days=int(raw_days), fulfillment_status=fulfillment_status))
                if path == '/api/tasks/queue':
                    query = parse_qs(parsed.query)
                    return self.json_response(store.task_queue(con, query.get('person_id', [None])[0],
                                                               query.get('project_id', [None])[0], query.get('from_task_id', [None])[0]))
                if len(pieces) == 4 and pieces[:3] == ['api', 'drawing-media', 'assets']:
                    asset = asset_path(store.data_dir, pieces[3])
                    if asset is None:
                        raise APIError(404, '图纸预览不存在')
                    return self.send_bytes(200, asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
                if len(pieces) == 4 and pieces[:2] == ['api', 'projects']:
                    project_id, action = pieces[2:]
                    if action == 'badge-media':
                        query = parse_qs(parsed.query)
                        return self.json_response(badge_media.catalog(store, con, project_id, query.get('task_id', [None])[0]))
                    if action == 'drawing-media':
                        store.get(con, 'projects', project_id)
                        return self.json_response(order_packet.project_media(store, con, project_id))
                    if action == 'quote':
                        return self.json_response(store.quote(con, project_id))
                    if action == 'releases':
                        store.get(con, 'projects', project_id)
                        return self.json_response({'releases': store.all(con, 'releases', project_id)})
                    if action == 'export':
                        project = store.get(con, 'projects', project_id)
                        fmt = parse_qs(parsed.query).get('format', ['json'])[0]
                        return self.export_project(con, project, fmt)
                if len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'model-links':
                    try:
                        return self.json_response(model_workspace.get_links(store, con, pieces[2]))
                    except ValueError as exc:
                        raise APIError(400, str(exc))
                if len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'image':
                    doc = store.get(con, 'documents', pieces[2])
                    if doc.get('purpose') != 'render' or doc.get('image', {}).get('mime_type') not in ('image/jpeg', 'image/png', 'image/webp'):
                        raise APIError(404, '效果图不存在')
                    source = (store.uploads / doc.get('storage_name', '')).resolve()
                    if not source.is_file() or source.parent != store.uploads.resolve():
                        raise APIError(404, '效果图文件不存在')
                    return self.send_bytes(200, source.read_bytes(), doc['image']['mime_type'])
                if len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'badge-image':
                    doc = store.get(con, 'documents', pieces[2])
                    name = doc.get('storage_name', '')
                    if not name or Path(name).name != name:
                        raise APIError(404, '图片源文件不存在')
                    source = (store.uploads / name).resolve()
                    if source.parent != store.uploads.resolve() or not source.is_file():
                        raise APIError(404, '图片源文件不存在')
                    content = source.read_bytes()
                    try:
                        metadata = validate_render(doc['filename'], content)
                    except (RenderImageError, RuntimeError) as exc:
                        raise APIError(422, str(exc))
                    return self.send_bytes(200, content, metadata['mime_type'])
                if len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] in ('preview', 'preview-image'):
                    doc = store.get(con, 'documents', pieces[2])
                    source = (store.uploads / doc.get('storage_name', '')).resolve()
                    if not source.is_file() or source.parent.resolve() != store.uploads.resolve():
                        raise APIError(404, '原始文件不存在')
                    query = parse_qs(parsed.query)
                    raw_page = query.get('page', ['1'])[0]
                    if not raw_page.isascii() or not raw_page.isdigit() or len(raw_page) > 5:
                        raise APIError(400, '页码必须为正整数')
                    try:
                        preview = preview_pdf(store.data_dir, doc, source, int(raw_page))
                    except (PreviewError, OSError) as exc:
                        raise APIError(422, str(exc))
                    if pieces[3] == 'preview-image':
                        url = preview['thumb_url'] if query.get('thumb') == ['1'] else preview['url']
                        asset = asset_path(store.data_dir, url.rsplit('/', 1)[-1])
                        if asset is None:
                            raise APIError(404, '图纸预览不存在')
                        return self.send_bytes(200, asset.read_bytes(), 'image/jpeg')
                    return self.json_response(preview)
                if len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'download':
                    doc = store.get(con, 'documents', pieces[2])
                    file = (store.uploads / doc.get('storage_name', '')).resolve()
                    if not file.is_file() or file.parent.resolve() != store.uploads.resolve():
                        raise APIError(404, '原始文件不存在')
                    return self.send_bytes(200, file.read_bytes(), 'application/octet-stream',
                        {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(doc['filename'])})
            if path.startswith('/api/'):
                raise APIError(404, '接口不存在')
            if path.startswith('/samples/'):
                if store.instance_id:raise APIError(404,'此工厂没有这份资料')
                access_control.require_private_asset_auth(self)
                sample_dir = (BASE / 'samples').resolve()
                sample = (sample_dir / path.removeprefix('/samples/')).resolve()
                if not sample.is_relative_to(sample_dir) or not sample.is_file() or sample.suffix.lower() not in ('.csv', '.json', '.dxf'):
                    raise APIError(404, '样本不存在')
                return self.send_bytes(200, sample.read_bytes(), 'application/octet-stream',
                    {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(sample.name)})
            relative = path.lstrip('/') or 'index.html'
            if relative in ('factory','factory/','factory/index.html'):relative='index.html'
            if relative in ('control','control/'):relative='control/index.html'
            if relative.startswith('control/') and store.instance_id:raise APIError(404,'此工厂没有中台入口')
            target = (self.server.static_dir / relative).resolve()
            if not target.is_relative_to(self.server.static_dir) or not target.is_file():
                raise APIError(404, '页面不存在')
            if not factory_instances.static_allowed(target.relative_to(self.server.static_dir)):
                if store.instance_id:raise APIError(404,'此工厂没有这份资料')
                if not relative.startswith('control/'):access_control.require_private_asset_auth(self)
            content_type = 'application/wasm' if target.suffix.lower() == '.wasm' else mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if content_type.startswith(('text/', 'application/javascript')):
                content_type += '; charset=utf-8'
            self.send_bytes(200, target.read_bytes(), content_type)
        except (APIError, DeviceError, planning.PlanningError, schedule_reference.ReferenceError, operations.OperationError, production.ProductionError, file_exchange.ExchangeError, calibration.CalibrationError, access_control.AccessError, badge_media.BadgeMediaError, factory_instances.InstanceError, project_sources.ProjectSourcesError, intelligence.IntelligenceError) as exc:
            self.error_response(exc)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_message('ERROR %s', str(exc))
            self.json_response({'error': '本机服务处理失败，请查看启动终端日志'}, 500)
