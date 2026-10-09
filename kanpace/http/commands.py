"""Command routes: authorize, own the transaction, invoke application services."""
from __future__ import annotations

from urllib.parse import unquote, urlsplit
import model_workspace
import planning
import schedule_reference
import operations
import production
import file_exchange
import scheduling
import calibration
import access_control
import agent_assistant
import factory_instances
import control_platform
import project_sources
import project_overview
import drawing_pipeline_review
import intelligence
import document_recognition
import optimization_engines
import badge_media
import order_packet
import project_document_flow
from device_bridge import DeviceError
from kanpace.core.errors import APIError
from kanpace.core.validation import now, uid


class CommandRoutes:
    def do_POST(self):
        try:
            data = self.validate_mutation()
            access_control.authorize(self, data=data)
            if access_control.handle(self, data):
                return
            path = urlsplit(self.path).path
            pieces = [unquote(x) for x in path.split('/') if x]
            store = self.server.store
            if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'recognition':
                with store.read_transaction() as con:
                    job = document_recognition.submit(store, con, pieces[2], data)
                return self.json_response({'job': job}, 202)
            if len(pieces) == 5 and pieces[:2] == ['api','projects'] and pieces[3:] == ['drawing-pipeline','import']:
                prepared = drawing_pipeline_review.prepare(data)
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    result, created = drawing_pipeline_review.save(store, con, pieces[2], data, prepared)
                return self.json_response(result, 201 if created else 200)
            if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'overview':
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    result = project_overview.save(store, con, pieces[2], data)
                return self.json_response(result)
            if len(pieces) in (6,7) and pieces[:3] == ['api','control','factories'] and pieces[4] == 'config':
                if len(pieces)==7 and pieces[5]!='plans':raise APIError(404,'配置操作不存在')
                return self.json_response(control_platform.mutate(store, pieces[3], pieces[5], data, pieces[6] if len(pieces)==7 else None))
            if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'sources':
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    result = project_sources.save_selection(store, con, pieces[2], data)
                # A successful response means the transaction has committed.
                return self.json_response(result)
            if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'document-confirmations':
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    result = project_document_flow.confirm(store, con, pieces[2], data)
                return self.json_response(result)
            if pieces == ['api','factory-instances','provision']:
                return self.json_response(factory_instances.provision(self.server,data),201)
            if pieces == ['api', 'agent', 'message']:
                # Business facts remain read-only; resumable workflow state is
                # saved separately in this factory's agent-workflows directory.
                with store.read_transaction() as con:
                    result = agent_assistant.respond(store, con, data)
                return self.json_response(result)
            if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'engineering':
                with store.connect() as con:
                    try:
                        job = intelligence.submit(store, con, pieces[2], data)
                    except intelligence.engineering_engines.EngineeringError as exc:
                        raise APIError(503 if exc.code in ('engine_not_installed','busy') else 400, str(exc), {'code':exc.code})
                return self.json_response({'job': job}, 202)
            if path == '/api/scheduling/preview' and data.get('engine') == 'ortools':
                with store.connect() as con:
                    con.execute('BEGIN')
                    prepared = optimization_engines.prepare_schedule(store, con, data)
                scenario = optimization_engines.solve_prepared(prepared)
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    result = optimization_engines.persist_schedule(store, con, scenario)
                return self.json_response(result)
            if len(pieces) == 4 and pieces[:2] == ['api','projects'] and pieces[3] == 'packing':
                with store.connect() as con:
                    project = store.get(con, 'projects', pieces[2])
                    store.require_project_open(project)
                    if type(data.get('expected_revision')) is not int or data['expected_revision'] != project['revision']:
                        raise APIError(409, '工程版本已变化，请刷新后核对下料尺寸')
                result = optimization_engines.packing_preview(data)
                with store.write_transaction() as con:
                    access_control.authorize(self, data=data)
                    latest = store.get(con, 'projects', project['id'])
                    store.require_project_open(latest)
                    if latest['revision'] != project['revision']:
                        raise APIError(409, '计算期间工程已变化，请核对尺寸后重算')
                    record = {'id':uid('packing'),'project_id':project['id'],'revision':project['revision'],
                              'created_at':now(),'config':data,'result':result}
                    store.put(con, 'packing_previews', record)
                return self.json_response({'preview':record}, 201)
            # Serial handshakes and writes must never hold the main SQLite
            # mutation transaction while awaiting transport events.
            if path == '/api/device/connect':
                return self.json_response(self.server.device_bridge.connect(data.get('port'), data.get('baudrate', 115200), data.get('transport', 'usb'), data.get('host')))
            if path == '/api/device/images':
                return self.json_response(self.server.device_bridge.images.start(data, access_control.get_actor()))
            if path == '/api/device/wifi-scan':
                return self.json_response(self.server.device_bridge.wifi_scan())
            if path == '/api/device/wifi-config':
                return self.json_response(self.server.device_bridge.wifi_config(data.get('ssid'), data.get('password', '')))
            if path == '/api/device/disconnect':
                return self.json_response(self.server.device_bridge.disconnect())
            if len(pieces) == 4 and pieces[:2] == ['api', 'tasks'] and pieces[3] == 'send-device':
                return self.json_response(self.server.device_bridge.send_task(pieces[2], data.get('test_mode', False)))
            if len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'fulfillment':
                with self.server.device_bridge._lock:
                    with store.write_transaction() as con:
                        access_control.authorize(self, data=data)
                        result = store.set_fulfillment(con, pieces[2], data)
                return self.json_response(result)
            with store.write_transaction() as con:
                # A second check under the writer lock keeps task ownership and
                # account changes consistent with the accepted mutation.
                access_control.authorize(self, data=data)
                if path == '/api/daily-workflow/labels/prepare':
                    result = store.daily_workflow.prepare_labels(con, data)
                elif path == '/api/device-bindings':
                    result = self.server.project_dispatch.bind(con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'dispatch':
                    result = self.server.project_dispatch.create(con, pieces[2], data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'project-dispatches'] and pieces[3] == 'retry':
                    result = self.server.project_dispatch.retry(con, pieces[2])
                elif len(pieces) == 4 and pieces[:2] == ['api', 'project-dispatches'] and pieces[3] == 'cancel':
                    result = self.server.project_dispatch.cancel(con, pieces[2], data)
                elif path in ('/api/material-planning/inventory', '/api/material-planning/purchases'):
                    import material_requirements
                    method = material_requirements.save_inventory if pieces[-1] == 'inventory' else material_requirements.save_purchase
                    result = method(store, con, data)
                elif path in ('/api/schedule-reference/working', '/api/schedule-reference/replace-preview', '/api/schedule-reference/replace', '/api/schedule-reference/apply'):
                    method = {'working': schedule_reference.save_working, 'replace-preview': schedule_reference.replacement_preview,
                        'replace': schedule_reference.replace_working, 'apply': schedule_reference.apply_working}[pieces[-1]]
                    result = method(store, con, data)
                elif path == '/api/planning/order':
                    result = planning.reorder(store, con, data)
                elif path == '/api/daily-workflow/locations':
                    result = store.daily_workflow.save_location(con, data)
                elif len(pieces) == 5 and pieces[:3] == ['api', 'daily-workflow', 'labels'] and pieces[4] == 'location':
                    result = store.daily_workflow.bind_location(con, pieces[3], data)
                elif len(pieces) == 5 and pieces[:3] == ['api', 'daily-workflow', 'labels'] and pieces[4] == 'confirm':
                    result = store.daily_workflow.confirm_label(con, pieces[3], data)
                elif path == '/api/daily-workflow/handovers/issue':
                    result = store.daily_workflow.issue(con, data)
                elif len(pieces) == 5 and pieces[:3] == ['api', 'daily-workflow', 'handovers'] and pieces[4] == 'return':
                    result = store.daily_workflow.return_badge(con, pieces[3], data)
                elif path == '/api/projects':
                    result = {'project': store.new_project(con, data)}
                elif path == '/api/exchange/preview':
                    result = file_exchange.prepare(store, con, data)
                elif path == '/api/calibration/estimate':
                    result = calibration.estimate(store, con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'exchange'] and pieces[3] == 'apply':
                    result = file_exchange.apply(store, con, pieces[2], data)
                elif path == '/api/scheduling/preview':
                    if data.get('engine') not in (None, 'heuristic'):
                        raise APIError(400, '请选择有效排程方式')
                    result = scheduling.preview(store, con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'scheduling'] and pieces[3] == 'apply':
                    result = scheduling.apply(store, con, pieces[2], data)
                elif len(pieces) in (3, 4) and pieces[:2] == ['api', 'operations'] and pieces[2] in ('factories', 'teams', 'workcenters', 'people', 'templates'):
                    method = {'factories': operations.save_factory, 'teams': operations.save_team, 'workcenters': operations.save_workcenter,
                              'people': operations.save_person, 'templates': operations.save_template}[pieces[2]]
                    result = method(store, con, data, pieces[3] if len(pieces) == 4 else None)
                elif len(pieces) == 5 and pieces[:3] == ['api', 'operations', 'templates'] and pieces[4] == 'publish':
                    result = operations.publish_template(store, con, pieces[3], data)
                elif len(pieces) in (4, 5) and pieces[:2] == ['api', 'projects'] and pieces[3] == 'workflow':
                    if len(pieces) == 4:
                        result = operations.save_workflow(store, con, pieces[2], data)
                    elif pieces[4] == 'review':
                        result = operations.review_workflow(store, con, pieces[2], data)
                    elif pieces[4] == 'preview':
                        result = operations.migration_preview(store, con, pieces[2], data)
                    elif pieces[4] == 'migrate':
                        result = operations.migrate_workflow(store, con, pieces[2], data)
                    else:
                        raise APIError(404, '流程操作不存在')
                elif len(pieces) == 3 and pieces[:2] == ['api', 'production']:
                    methods = {'materials': production.save_material, 'issues': production.save_issue, 'checks': production.save_checks,
                               'inspections': production.save_inspection, 'costs': production.save_cost,
                               'financials': production.save_financial, 'deliveries': production.save_delivery,
                               'changes': production.save_change, 'milestones': production.save_milestone}
                    if pieces[2] not in methods:
                        raise APIError(404, '生产操作不存在')
                    result = production.mutate(store, con, pieces[2], data, methods[pieces[2]])
                elif len(pieces) == 5 and pieces[:3] == ['api', 'production', 'reworks'] and pieces[4] == 'release':
                    result = production.release_rework(store, con, pieces[3], data)
                elif path == '/api/schedule-reference/import':
                    result = schedule_reference.import_reference(store, con, data)
                elif path == '/api/planning':
                    result = planning.save(store, con, data)
                elif path == '/api/planning/calendar':
                    result = planning.save_calendar(store, con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'planning'] and pieces[3] == 'cancel':
                    result = planning.cancel(store, con, pieces[2], data)
                elif path == '/api/order-drafts/import':
                    result = store.import_order_draft(con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'model-links':
                    try:
                        result = model_workspace.save_links(store, con, pieces[2], data)
                    except ValueError as exc:
                        raise APIError(400, str(exc))
                elif path == '/api/import':
                    result = store.import_file(con, data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'projects'] and pieces[3] == 'order-packet':
                    result = order_packet.save(store, con, pieces[2], data)
                elif path == '/api/parts':
                    result = {'part': intelligence.create_part(store, con, data) if 'engineering_evidence' in data else store.create_part(con, data)}
                elif path == '/api/people':
                    result = {'person': store.save_person(con, data)}
                elif len(pieces) == 3 and pieces[:2] == ['api', 'people']:
                    result = {'person': store.save_person(con, data, pieces[2])}
                elif path == '/api/settings':
                    result = {'settings': store.update_settings(con, data)}
                elif len(pieces) == 4 and pieces[:2] == ['api', 'parts'] and pieces[3] == 'review':
                    result = store.review_part(con, pieces[2], data)
                elif len(pieces) == 4 and pieces[:2] == ['api', 'projects']:
                    identifier, action = pieces[2:]
                    if action == 'generate':
                        result = store.generate(con, identifier)
                    elif action == 'release':
                        result = store.release(con, identifier)
                    elif action == 'auto-assign':
                        result = store.auto_assign(con, identifier)
                    elif action == 'costs':
                        result = {'project': store.update_project_costs(con, identifier, data)}
                    else:
                        raise APIError(404, '项目操作不存在')
                elif len(pieces) == 4 and pieces[:2] == ['api', 'tasks']:
                    identifier, action = pieces[2:]
                    if action == 'assign':
                        result = {'task': store.assign(con, identifier, data.get('person_id'), data)}
                    elif action == 'status':
                        result = {'task': store.set_status(con, identifier, data)}
                    elif action == 'progress':
                        result = {'task': store.report_progress(con, identifier, data)}
                    elif action == 'pause':
                        result = {'task': store.pause_task(con, identifier, data)}
                    elif action == 'resume':
                        result = {'task': store.resume_task(con, identifier, data)}
                    elif action == 'priority':
                        result = {'task': store.set_priority(con, identifier, data)}
                    elif action == 'switch':
                        result = store.switch_task(con, identifier, data)
                    else:
                        raise APIError(404, '任务操作不存在')
                elif len(pieces) == 4 and pieces[:2] == ['api', 'documents'] and pieces[3] == 'resolve':
                    result = {'document': store.resolve_document(con, pieces[2], data)}
                else:
                    raise APIError(404, '接口不存在')
            self.json_response(result)
        except (APIError, DeviceError, planning.PlanningError, schedule_reference.ReferenceError, operations.OperationError, production.ProductionError, file_exchange.ExchangeError, calibration.CalibrationError, access_control.AccessError, badge_media.BadgeMediaError, factory_instances.InstanceError, project_sources.ProjectSourcesError, intelligence.IntelligenceError) as exc:
            self.error_response(exc)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_message('ERROR %s', str(exc))
            self.json_response({'error': '操作未保存；本机服务处理失败，请查看启动终端日志'}, 500)
