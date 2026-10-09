"""Durable project dispatch over the existing single live badge connection.

Queues live on the factory server. A device receives only its current task;
receipt, media receipt and production completion remain separate facts.
"""
import copy
import hashlib
import json
import threading

import access_control
import badge_media
import fulfillment
from device_bridge import DELIVERY_KIND, DeviceError
from kanpace.core.errors import APIError
from kanpace.core.validation import now, uid


TERMINAL = ('completed', 'cancelled')

def dependencies(task):
    return list(dict.fromkeys(task.get('dependencies', []) + task.get('schedule_dependencies', [])))



class ProjectDispatchCoordinator:
    def __init__(self, store, bridge, *, background=True):
        self.store, self.bridge = store, bridge
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        if background:
            self.worker = threading.Thread(target=self._run, name='project-dispatch', daemon=True)
            self.worker.start()

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=4)

    def devices(self, con):
        # Never acquire the transport lock while a caller holds SQLite's writer
        # lock: the serial receipt handler takes those locks in the other order.
        live = dict(self.bridge._state)
        connected = live.get('state') == 'ready' and bool(live.get('device_id'))
        known = {row['device_id'] for row in self.store.all(con, 'device_bindings') if row.get('device_id')}
        known.update(row['device_id'] for row in self.store.all(con, DELIVERY_KIND) if row.get('device_id'))
        known.update(getattr(self.bridge, '_secrets', {}).keys())
        if connected:
            known.add(live['device_id'])
        bindings = {row['device_id']: row for row in self.store.all(con, 'device_bindings')
                    if row.get('device_id') and not row.get('archived')}
        return [{'id': identifier, 'device_id': identifier, 'name': identifier,
                 'connected': connected and identifier == live['device_id'],
                 'status': 'connected' if connected and identifier == live['device_id'] else 'offline',
                 'image_slots': live.get('image_slots', 2) if connected and identifier == live['device_id'] else None,
                 'image_support': bool(live.get('image_support')) if connected and identifier == live['device_id'] else None,
                 'transport': live.get('transport') if connected and identifier == live['device_id'] else None,
                 'bound_person_id': bindings.get(identifier, {}).get('person_id')}
                for identifier in sorted(known)]

    def bind(self, con, data):
        person_id = self.store.daily_workflow.identifier(data.get('person_id'), '人员编号')
        device_id = self.store.daily_workflow.identifier(data.get('device_id'), '胸牌编号')
        person = self.store.get(con, 'people', person_id)
        if person.get('demo'):
            raise APIError(409, '请使用真实人员档案绑定胸牌')
        if person.get('employment_status', 'active') != 'active':
            raise APIError(409, '离职人员不能绑定胸牌，请选择在职人员')
        if device_id not in {row['id'] for row in self.devices(con)}:
            raise APIError(409, '胸牌尚未完成连接注册，请先连接实际设备')
        expected = data.get('expected_version')
        if type(expected) is not int or expected < 0:
            raise APIError(400, '请提供人员胸牌绑定版本')
        bindings = [row for row in self.store.all(con, 'device_bindings') if not row.get('archived')]
        existing = next((row for row in bindings if row['person_id'] == person_id), None)
        if any(row['device_id'] == device_id and row['person_id'] != person_id for row in bindings):
            raise APIError(409, '此胸牌已经绑定其他人员，一人一牌不能重复绑定')
        if existing and existing['device_id'] == device_id and expected in (existing['version'], existing['version'] - 1):
            return {'binding': existing, 'duplicate': True}
        if expected != (existing['version'] if existing else 0):
            raise APIError(409, '人员胸牌绑定已更新，请刷新')
        if existing and any(job['status'] not in TERMINAL and any(row['person_id'] == person_id for row in job['workers'])
                            for job in self.store.all(con, 'project_dispatches')):
            raise APIError(409, '人员还有项目派工队列，请先处理后更换胸牌')
        binding = dict(existing or {'id': uid('binding'), 'created_at': now()}, person_id=person_id, person_name=person.get('name', ''),
                       device_id=device_id, version=expected + 1, updated_at=now())
        self.store.put(con, 'device_bindings', binding)
        self.store.event(con, None, 'person_badge_bound', '人员与胸牌绑定', person_id=person_id, device_id=device_id)
        return {'binding': binding, 'duplicate': False}

    def preview(self, con, project_id, day=None):
        project = self.store.get(con, 'projects', project_id)
        publication_blockers = []
        if (fulfillment.is_closed(project) or project.get('archived') or project.get('status') != 'released'
                or project.get('released_revision') != project.get('revision') or project.get('demo')):
            publication_blockers.append('请先复核并发布真实项目的当前工程版本；旧队列可先停止后续派发')
        day = self.store.daily_workflow.day(day) if day is not None else None
        dated = {row['id'] for row in self.store.daily_workflow.dated_tasks(con, day, project_id=project_id)} if day else None
        tasks = [task for task in self.store.active_tasks(con, project_id)
                 if task.get('revision') == project['revision'] and task.get('status') in ('ready', 'blocked', 'in_progress')
                 and (dated is None or task['id'] in dated)]
        plans = {row['task_id']: row for row in self.store.all(con, 'plans', project_id)
                 if row.get('status') == 'scheduled' and row.get('task_revision') == project['revision']}
        tasks.sort(key=lambda task: (-task.get('priority', 0), task.get('schedule_position', 1000000),
            plans.get(task['id'], {}).get('start_at') or plans.get(task['id'], {}).get('start_date') or '9999', task.get('created_at', ''), task['id']))
        # Preserve the chosen order wherever it does not contradict an in-project
        # predecessor. Cross-person dependencies are also checked before sending.
        ordered, remaining = [], list(tasks)
        while remaining:
            pending = {task['id'] for task in remaining}
            ready = next((task for task in remaining if not pending.intersection(dependencies(task))), None)
            if ready is None:
                raise APIError(409, '项目工序前置关系循环，无法建立派工队列')
            ordered.append(ready)
            remaining.remove(ready)
        people = {row['id']: row for row in self.store.all(con, 'people')}
        bindings = {row['person_id']: row for row in self.store.all(con, 'device_bindings') if not row.get('archived')}
        devices = self.devices(con)
        by_device = {row['id']: row for row in devices}
        groups, blockers, warnings = {}, publication_blockers, []
        for task in ordered:
            person_id = task.get('assignee')
            if not person_id or person_id not in people:
                blockers.append('任务尚未分配人员：' + task['title'])
                continue
            if people[person_id].get('employment_status', 'active') != 'active':
                blockers.append('任务负责人已离职，请重新分派：' + task['title'])
                continue
            binding = bindings.get(person_id)
            device = by_device.get(binding['device_id'], {}) if binding else {}
            group = groups.setdefault(person_id, {'person_id': person_id, 'person_name': people[person_id].get('name', ''),
                'binding': binding, 'device_id': binding['device_id'] if binding else None,
                'connected': bool(device.get('connected')), 'tasks': [], 'blockers': []})
            catalog = badge_media.catalog(self.store, con, project_id, task['id'])
            media = badge_media.automatic_selection(catalog, device.get('image_slots') or 6)
            group['tasks'].append({'id': task['id'], 'title': task['title'], 'status': task['status'], 'revision': task['revision'],
                'planned_date': plans.get(task['id'], {}).get('start_date'), 'media': media})
        for group in groups.values():
            group['task_count'] = len(group['tasks'])
            if not group['binding']:
                group['blockers'].append('请先为此人员绑定一块已注册胸牌')
                blockers.append(group['person_name'] + '尚未绑定胸牌')
            elif not group['connected']:
                group['blockers'].append('胸牌未连接，队列将等待此设备连接')
        active = next((job for job in self.store.all(con, 'project_dispatches', project_id) if job['status'] not in TERMINAL), None)
        connected_count = sum(row['connected'] for row in devices)
        matched = sum(group['connected'] for group in groups.values())
        if len(groups) > connected_count:
            warnings.append(f'项目需要 {len(groups)} 块人员胸牌，当前实际连接 {connected_count} 块；离线人员队列会等待连接')
        warnings.append('当前服务同时管理 1 个实际连接；其他已注册胸牌保持离线状态')
        if not tasks:
            blockers.append('项目范围内没有可派工的未完成任务')
        return {'project': {key: project.get(key) for key in ('id', 'name', 'revision')}, 'scope': 'date' if day else 'project', 'date': day,
            'workers': list(groups.values()), 'devices': devices, 'blockers': list(dict.fromkeys(blockers)), 'warnings': warnings,
            'active_dispatch': {'id': active['id'], 'status': active['status'], 'version': active['version']} if active else None,
            'summary': {'worker_count': len(groups), 'task_count': len(tasks), 'required_badges': len(groups),
                'connected_count': connected_count, 'matched_connected_count': matched,
                'unbound_count': sum(not group['binding'] for group in groups.values()), 'missing_connection_count': len(groups) - matched}}

    def create(self, con, project_id, data):
        request_id = self.store.daily_workflow.identifier(data.get('request_id'), '派工请求编号')
        payload = {'project_id': project_id, 'revision': data.get('expected_revision'), 'date': data.get('date')}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        for job in self.store.all(con, 'project_dispatches'):
            if job['request_id'] == request_id:
                if job['payload_hash'] != digest:
                    raise APIError(409, '同一派工请求编号内容不同，请重新核对')
                return {'dispatch': self.public(job), 'duplicate': True}
        preview = self.preview(con, project_id, data.get('date'))
        if type(data.get('expected_revision')) is not int or data['expected_revision'] != preview['project']['revision']:
            raise APIError(409, '工程版本已变化，请刷新项目派工预览')
        if preview['blockers']:
            raise APIError(409, '项目派工条件尚未满足', {'blockers': preview['blockers']})
        if preview['active_dispatch']:
            raise APIError(409, '此项目已有派工队列，请查看原队列', preview['active_dispatch'])
        workers = []
        for group in preview['workers']:
            workers.append({'person_id': group['person_id'], 'person_name': group['person_name'], 'device_id': group['device_id'],
                'binding_version': group['binding']['version'], 'status': 'queued',
                'entries': [{'task_id': task['id'], 'title': task['title'], 'revision': task['revision'], 'status': 'queued',
                             'delivery_id': None, 'transfer_id': None, 'attempt': 0, 'error': None, 'warnings': task['media']['warnings']}
                            for task in group['tasks']]})
        job = {'id': uid('dispatch'), 'project_id': project_id, 'revision': preview['project']['revision'],
            'request_id': request_id, 'payload_hash': digest, 'date': preview['date'], 'scope': preview['scope'],
            'status': 'queued', 'workers': workers, 'created_at': now(), 'updated_at': now(), 'version': 1,
            'requested_by': copy.deepcopy(access_control.get_actor() or {}), 'warnings': preview['warnings']}
        self.store.put(con, 'project_dispatches', job)
        self.store.event(con, project_id, 'project_dispatch_created', '建立项目人员派工队列', dispatch_id=job['id'], worker_count=len(workers))
        return {'dispatch': self.public(job), 'duplicate': False}

    @staticmethod
    def public(job):
        return {key: copy.deepcopy(value) for key, value in job.items() if key not in ('requested_by', 'payload_hash')}

    def get(self, con, identifier):
        return {'dispatch': self.public(self.store.get(con, 'project_dispatches', identifier))}

    def cancel(self, con, identifier, data):
        job = self.store.get(con, 'project_dispatches', identifier)
        if job['status'] in TERMINAL:
            return {'dispatch': self.public(job), 'duplicate': True}
        if type(data.get('expected_version')) is not int or data['expected_version'] != job['version']:
            raise APIError(409, '派工队列已更新，请刷新后停止')
        job.update(status='cancelled', version=job['version'] + 1, updated_at=now(), cancelled_at=now())
        self.store.put(con, 'project_dispatches', job)
        self.store.event(con, job['project_id'], 'project_dispatch_cancelled', '停止项目后续派发，已下发任务保持不变', dispatch_id=identifier)
        return {'dispatch': self.public(job), 'duplicate': False}

    def retry(self, con, identifier):
        job = self.store.get(con, 'project_dispatches', identifier)
        if job['status'] in TERMINAL:
            raise APIError(409, '派工队列已结束，不能重试')
        changed = False
        for worker in job['workers']:
            for entry in worker['entries']:
                if entry['status'] == 'failed':
                    changed = True
                    entry.update(status='queued', error=None, delivery_id=None, transfer_id=None, attempt=entry.get('attempt', 0) + 1)
        if changed:
            job.update(status='queued', version=job['version'] + 1, updated_at=now(), requested_by=copy.deepcopy(access_control.get_actor() or {}))
            self.store.put(con, 'project_dispatches', job)
        return {'dispatch': self.public(job), 'duplicate': not changed}

    def _run(self):
        while not self.stop_event.wait(1):
            try:
                self.tick()
            except Exception:
                # Unknown/transient faults must not overwrite the saved queue or
                # acknowledge a send. The next cycle re-reads durable facts.
                continue

    def _authorized(self, con, job):
        actor = job.get('requested_by') or {}
        enabled = any(row.get('enabled') for row in self.store.all(con, 'access_config'))
        if not enabled:
            return True
        user = next((row for row in self.store.all(con, 'access_users') if row['id'] == actor.get('id') and row.get('active')), None)
        return bool(user and ('*' in access_control.ROLES[user['role']]['permissions'] or 'device' in access_control.ROLES[user['role']]['permissions']))

    @staticmethod
    def _rank(task, plans):
        plan = plans.get(task['id'], {})
        return (-task.get('priority', 0), task.get('schedule_position', 1000000),
                plan.get('start_at') or plan.get('start_date') or '9999', task.get('created_at', ''), task['id'])

    def tick(self):
        with self.lock:
            with self.store.read_transaction() as con:
                jobs = [job for job in self.store.all(con, 'project_dispatches') if job['status'] not in TERMINAL]
                tasks = {task['id']: task for task in self.store.all(con, 'tasks')}
                plans = {row['task_id']: row for row in self.store.all(con, 'plans') if row.get('status') == 'scheduled'}
                projects = {project['id']: project for project in self.store.all(con, 'projects')}
                # One chosen candidate per person across every project. Active
                # execution wins; otherwise current schedule order wins. A live
                # device task is still checked before any physical replacement.
                candidates = {}
                for job in jobs:
                    project = projects.get(job['project_id'], {})
                    if (project.get('revision') != job['revision'] or project.get('released_revision') != job['revision']
                            or project.get('status') != 'released' or fulfillment.is_closed(project) or not self._authorized(con, job)):
                        continue
                    for worker in job['workers']:
                        for entry in worker['entries']:
                            task = tasks.get(entry['task_id'])
                            if (not task or task.get('assignee') != worker['person_id'] or task.get('revision') != job['revision']
                                    or entry['status'] in ('completed', 'failed') or task['status'] not in ('ready', 'in_progress')):
                                continue
                            ready = all(dep in tasks and tasks[dep]['status'] == 'done'
                                and not self.store.daily_workflow.label_summary(con, tasks[dep])['pending'] for dep in dependencies(task))
                            if not ready or (task['status'] == 'ready' and self.store.start_blockers(con, task)):
                                continue
                            rank = (0 if task['status'] == 'in_progress' else 1, self._rank(task, plans))
                            existing = candidates.get(worker['person_id'])
                            if not existing or rank < existing[0]:
                                candidates[worker['person_id']] = (rank, entry['task_id'])
            for job in jobs:
                before = copy.deepcopy(job)
                for worker in job['workers']:
                    # Keep visible queued rows in the latest table order; never
                    # change production status or operation dependencies here.
                    worker['entries'].sort(key=lambda entry: self._rank(tasks.get(entry['task_id'], {'id': entry['task_id']}), plans))
                    preferred = candidates.get(worker['person_id'], (None, None))[1]
                    try:
                        self._advance(job, worker, preferred)
                    except (APIError, DeviceError) as error:
                        worker['status'] = 'failed'
                        pending = next((entry for entry in worker['entries'] if entry['status'] != 'completed'), None)
                        if pending:
                            pending.update(status='failed', error=str(error))
                statuses = [worker['status'] for worker in job['workers']]
                job['status'] = 'completed' if all(status == 'completed' for status in statuses) else 'partial_failure' if ('failed' in statuses or any(entry['status'] == 'failed' for worker in job['workers'] for entry in worker['entries'])) else 'active'
                if before != job:
                    job.update(updated_at=now(), version=job['version'] + 1)
                    with self.store.write_transaction() as con:
                        latest = self.store.get(con, 'project_dispatches', job['id'])
                        if latest['version'] == before['version']:
                            self.store.put(con, 'project_dispatches', job)

    def _advance(self, job, worker, preferred):
        with self.store.read_transaction() as con:
            project = self.store.get(con, 'projects', job['project_id'])
            entries = worker['entries']
            tasks = {entry['task_id']: self.store.get(con, 'tasks', entry['task_id']) for entry in entries}
            for entry in entries:
                task = tasks[entry['task_id']]
                if task['status'] == 'done' and self.store.daily_workflow.label_summary(con, task)['pending'] == 0:
                    entry.update(status='completed', error=None)
            remaining = [entry for entry in entries if entry['status'] != 'completed']
            if not remaining:
                worker['status'] = 'completed'
                return
            entry = next((item for item in remaining if item['task_id'] == preferred), remaining[0])
            task = tasks[entry['task_id']]
            person = next((row for row in self.store.all(con, 'people') if row['id'] == worker['person_id']), None)
            if not self._authorized(con, job):
                entry.update(status='failed', error='原派工账号权限已变更，请由有权限人员重新确认')
            elif not person or person.get('employment_status', 'active') != 'active':
                entry.update(status='failed', error='人员已离职，请重新分派任务并核对胸牌')
            elif (fulfillment.is_closed(project) or project.get('archived') or task.get('archived')
                    or project.get('revision') != job['revision'] or project.get('released_revision') != job['revision']
                    or task.get('revision') != job['revision'] or task.get('assignee') != worker['person_id']):
                entry.update(status='failed', error='项目、负责人或工程版本已变化，请重新核对派工')
            binding = next((row for row in self.store.all(con, 'device_bindings')
                            if row['person_id'] == worker['person_id'] and not row.get('archived')), None)
            if not binding or binding['device_id'] != worker['device_id'] or binding['version'] != worker['binding_version']:
                entry.update(status='failed', error='人员胸牌绑定已变化，请重新核对')
            if entry['status'] == 'failed':
                worker['status'] = 'failed'
                return
            if task['status'] == 'done':
                entry.update(status='awaiting_labels', error=None)
                worker['status'] = entry['status']
                return
            live = self.bridge.snapshot()['device']
            if live.get('state') != 'ready' or live.get('device_id') != worker['device_id']:
                entry.update(status='waiting_device', error=None)
                worker['status'] = entry['status']
                return
            if live.get('transport') != 'usb':
                entry.update(status='failed', error='当前项目图文派工需要 USB 图片传输；此连接尚不支持无线图片回执')
                worker['status'] = 'failed'
                return
            if not entry.get('delivery_id'):
                recovered = next((row for row in reversed(self.store.all(con, DELIVERY_KIND, job['project_id']))
                    if row.get('dispatch_id') == job['id'] and row.get('dispatch_attempt', 0) == entry.get('attempt', 0)
                    and row['task_id'] == task['id'] and row['device_id'] == worker['device_id']), None)
                if recovered:
                    entry['delivery_id'] = recovered['id']
            if entry.get('delivery_id'):
                delivery = self.store.get(con, DELIVERY_KIND, entry['delivery_id'])
                if delivery['status'] in ('failed', 'timeout', 'rejected'):
                    entry.update(status='failed', error=delivery.get('error') or '胸牌未确认任务接收')
                elif delivery['status'] != 'received':
                    entry.update(status='awaiting_receipt', error=None)
                if delivery['status'] != 'received':
                    worker['status'] = entry['status']
                    return
            if preferred and preferred != task['id']:
                if not entry.get('delivery_id'):
                    entry.update(status='queued', error=None)
                worker['status'] = entry['status']
                return
            blockers = self.store.start_blockers(con, task)
            # Explicit pause/switch has already validated the newly active target.
            if task['status'] == 'blocked':
                blockers.append('当前任务已暂停，请先处理异常或在 Web 确认切换')
            for dependency_id in dependencies(task):
                dependency = self.store.get(con, 'tasks', dependency_id)
                if dependency['status'] == 'done' and self.store.daily_workflow.label_summary(con, dependency)['pending']:
                    blockers.append('前置工序尚未确认对应工件标签')
            if blockers and not entry.get('delivery_id'):
                entry.update(status='waiting_predecessors', error='；'.join(dict.fromkeys(blockers)))
                worker['status'] = entry['status']
                return
        # No database transaction is held while waiting for the real USB peer.
        try:
            if self.bridge.images.busy() or self.bridge._pending:
                entry.update(status='waiting_connection', error=None)
                worker['status'] = entry['status']
                return
            generation = getattr(self.bridge, '_send_generation', 0)
            current_reply = self.bridge._usb_rpc('get_task', timeout=2, expected_device_id=worker['device_id'], reply_type='status')
            current = current_reply.get('task') or {}
            with self.bridge._lock:
                if self.bridge.images.busy() or self.bridge._pending or generation != getattr(self.bridge, '_send_generation', 0):
                    entry.update(status='waiting_connection', error=None)
                    worker['status'] = entry['status']
                    return
                if current.get('id') and current['id'] != task['id']:
                    with self.store.read_transaction() as con:
                        previous = self.store.get(con, 'tasks', current['id'])
                        switched_here = previous.get('status') == 'blocked' and previous.get('interrupted_by_task_id') == task['id']
                        ready_reordered = (live.get('safe_ready_replacement') is True and previous.get('status') == 'ready' and current.get('status') == 'ready'
                            and current_reply.get('execution_pending') == 0)
                        if not switched_here and not ready_reordered and (previous.get('status') != 'done' or self.store.daily_workflow.label_summary(con, previous)['pending']):
                            entry.update(status='waiting_current_task', error='胸牌上还有未完成或未确认标签的任务，未覆盖原任务')
                            worker['status'] = entry['status']
                            return
                if current_reply.get('execution_pending', 0):
                    entry.update(status='waiting_connection', error='胸牌还有报工等待确认，未覆盖任务')
                    worker['status'] = entry['status']
                    return
                if entry.get('delivery_id') and current.get('id') == task['id'] and current.get('revision') == task['revision']:
                    self._media_progress(entry, job, worker, live)
                    worker['status'] = entry['status']
                    return
                if task['status'] == 'blocked':
                    entry.update(status='waiting_predecessors', error='原任务仍暂停，请先确认恢复后再下发')
                    worker['status'] = entry['status']
                    return
                if entry.get('delivery_id'):
                    # Returning to a previously received task needs a new real
                    # receipt; old ACKs never prove what is currently on screen.
                    entry.update(delivery_id=None, transfer_id=None, attempt=entry.get('attempt', 0) + 1)
                delivered = self.bridge.send_task(task['id'], dispatch_context={'dispatch_id': job['id'],
                    'attempt': entry.get('attempt', 0), 'expected_execution_version': task.get('execution_version', 0),
                    'expected_assignee': worker['person_id'], 'expected_revision': job['revision'], 'device_id': worker['device_id']})
            entry.update(status='awaiting_receipt', delivery_id=delivered['delivery']['id'], error=None)
        except (DeviceError, APIError) as error:
            entry.update(status='failed', error=str(error))
        worker['status'] = entry['status']

    def _media_progress(self, entry, job, worker, live):
        if not live.get('image_support'):
            entry.update(status='failed', error='任务已收件，但胸牌固件不支持图片；请升级后重试图文派工')
            return
        transfer = self.bridge.images.snapshot().get('transfer')
        if not transfer or transfer.get('delivery_id') != entry['delivery_id']:
            if self.bridge.images.busy():
                entry.update(status='images_pending', error=None)
                return
            try:
                transfer = self.bridge.images.start({'project_id': job['project_id'], 'task_id': entry['task_id'],
                    'mode': 'task', 'delivery_id': entry['delivery_id']}, job.get('requested_by'), automatic=True)['transfer']
            except DeviceError as error:
                entry.update(status='failed', error=str(error))
                return
        entry['transfer_id'] = transfer['id']
        entry['warnings'] = list(dict.fromkeys(entry.get('warnings', []) + transfer.get('warnings', [])))
        entry['image_count'] = transfer.get('completed_images', 0)
        entry['media_status'] = transfer['status']
        if transfer['status'] == 'error':
            entry.update(status='failed', error='任务已收件，图片未送达：' + (transfer.get('error') or '图片传输失败'))
        elif transfer['status'] == 'empty':
            entry.update(status='active', error=None, warnings=list(dict.fromkeys(entry['warnings'] + ['未找到可发送的已关联图片，请补充工程资料'])))
        elif transfer['status'] == 'received':
            entry.update(status='active', error=None)
        else:
            entry.update(status='images_pending', error=None)
