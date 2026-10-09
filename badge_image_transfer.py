"""Bounded, acknowledged USB image transfers; never create production tasks."""
from __future__ import annotations

import base64
import copy
import hashlib
import threading
from uuid import uuid4

import badge_media
import fulfillment
from device_bridge import DeviceError, stamp

KIND = 'device_image_transfers'
CHUNK_BYTES = 4096


class BadgeImageTransfers:
    def __init__(self, bridge):
        self.bridge = bridge
        self.store = bridge.store
        self.lock = threading.RLock()
        self.current = None
        with self.store.connect() as con:
            rows = self.store.all(con, KIND)
            for row in rows:
                if row.get('status') in ('preparing', 'sending'):
                    row.update(status='error', error='本地服务重启，请重新发送图片', finished_at=stamp())
                    self.store.put(con, KIND, row)
            if rows:
                self.current = rows[-1]

    def snapshot(self):
        with self.lock:
            return {'transfer': copy.deepcopy(self.current)}

    def busy(self):
        with self.lock:
            return bool(self.current and self.current['status'] in ('preparing', 'sending'))

    def _update(self, job, *, persist=False, **fields):
        with self.lock:
            job.update(fields)
            saved = copy.deepcopy(job)
        if persist:
            with self.store.connect() as con:
                self.store.put(con, KIND, saved)

    def start(self, data, actor=None, *, automatic=False):
        project_id, task_id = data.get('project_id'), data.get('task_id') or None
        mode, selected = data.get('mode', 'preview'), data.get('asset_ids')
        if not isinstance(project_id, str) or mode not in ('preview', 'task'):
            raise DeviceError(400, '请选择项目和有效的图片发送方式')
        if task_id is not None and not isinstance(task_id, str):
            raise DeviceError(400, '任务标识无效')
        if mode == 'task' and not task_id:
            raise DeviceError(400, '任务图片必须关联当前任务')
        if not automatic and (not isinstance(selected, list) or not 1 <= len(selected) <= 6
                or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected)):
            raise DeviceError(400, '请选择不重复的项目图片，最多 6 张')
        bridge = self.bridge
        with bridge._lock:
            if (bridge._state['state'] != 'ready' or bridge._state['transport'] != 'usb'
                    or not bridge._serial):
                raise DeviceError(409, '请先通过 USB 连接工牌，再发送图片')
            if not bridge._state.get('image_support'):
                raise DeviceError(409, '当前工牌固件不支持看图，请升级到 1.5.0 或更新版本')
            slots = bridge._state.get('image_slots', 2)
            if not automatic and len(selected) > slots:
                raise DeviceError(409, f'当前胸牌最多保存 {slots} 张图片，请升级图库固件或减少选择')
            if self.busy() or bridge._pending:
                raise DeviceError(409, '工牌正在接收内容，请等待当前传输完成')
            with self.store.connect() as con:
                project = self.store.get(con, 'projects', project_id)
                if task_id:
                    task = self.store.get(con, 'tasks', task_id)
                    if task['project_id'] != project_id:
                        raise DeviceError(409, '任务与所选图片项目不一致')
                    if mode == 'task':
                        self._task_guard(project, task)
            context_id = f'{mode}:{task_id if mode == "task" else project_id}:r{project["revision"]}'
            job = dict(id='images_' + uuid4().hex[:20], project_id=project_id, project_name=project['name'],
                       revision=project['revision'], task_id=task_id, mode=mode, context_id=context_id,
                       device_id=bridge._state['device_id'], status='preparing', progress=0,
                       completed_images=0, total_images=len(selected or []), error=None, images=[],
                       created_at=stamp(), requested_by=copy.deepcopy(actor), image_slots=slots,
                       max_gallery_bytes=bridge._state.get('max_gallery_bytes', 360000), warnings=[],
                       delivery_id=data.get('delivery_id'))
            self.current = job
            self._update(job, persist=True)
            connection = bridge._serial
            worker = threading.Thread(target=self._run, args=(job, selected, connection, automatic),
                                      name='badge-image-transfer', daemon=True)
            worker.start()
            return self.snapshot()

    @staticmethod
    def _task_guard(project, task):
        if (fulfillment.is_closed(project) or project.get('archived') or task.get('archived')
                or task.get('status') not in ('ready', 'blocked', 'in_progress')
                or project.get('status') != 'released'
                or task.get('revision') != project.get('revision')
                or project.get('released_revision') != project.get('revision')):
            raise DeviceError(409, '当前任务版本不可下发，请复核项目状态')

    def _guard(self, job, connection):
        with self.bridge._lock:
            if (self.bridge._serial is not connection or self.bridge._state['state'] != 'ready'
                    or self.bridge._state['device_id'] != job['device_id']):
                raise DeviceError(409, 'USB 连接已变化，请重新发送图片')
        with self.store.connect() as con:
            project = self.store.get(con, 'projects', job['project_id'])
            if project['revision'] != job['revision']:
                raise DeviceError(409, '工程版本已变化，请重新选择图片')
            if job['mode'] == 'task':
                self._task_guard(project, self.store.get(con, 'tasks', job['task_id']))

    def _rpc(self, action, payload, job, connection):
        for attempt in range(3):
            self._guard(job, connection)
            try:
                reply = self.bridge._usb_rpc('image_' + action, payload, timeout=8,
                    expected_device_id=job['device_id'], reply_type='image_ack')
            except DeviceError as exc:
                if exc.status == 504 and attempt < 2:
                    continue
                raise
            if reply.get('action') != action or (payload.get('image_id') and reply.get('image_id') != payload['image_id']):
                raise DeviceError(409, '图片回执与本次发送不匹配')
            return reply

    def _run(self, job, selected, connection, automatic):
        try:
            with self.store.connect() as con:
                catalog = badge_media.catalog(self.store, con, job['project_id'], job['task_id'])
                if automatic:
                    selection = badge_media.automatic_selection(catalog, job['image_slots'])
                    selected = selection['asset_ids']
                    self._update(job, persist=True, warnings=selection['warnings'], available_images=selection['available_count'], omitted_images=selection['omitted_count'])
                    if not selected:
                        self._update(job, persist=True, status='empty', error=None, finished_at=stamp())
                        return
                package = badge_media.prepare(self.store, con, job['project_id'], selected, job['task_id'],
                                             max_images=job['image_slots'], max_gallery_bytes=job['max_gallery_bytes'])
            if package['revision'] != job['revision']:
                raise DeviceError(409, '工程版本已变化，请重新发送图片')
            self._guard(job, connection)
            if job['mode'] == 'task':
                current = self.bridge._usb_rpc('get_task', expected_device_id=job['device_id'], reply_type='status')
                task = current.get('task') or {}
                if (task.get('id') != job['task_id'] or task.get('project_id') != job['project_id']
                        or task.get('revision') != job['revision']):
                    raise DeviceError(409, '工牌当前任务已变化，请先重新下发任务')
            images = package['images']
            self._update(job, persist=True, status='sending', total_images=len(images),
                         images=[{k: v for k, v in item.items() if k != 'bytes'} for item in images])
            total_bytes = sum(len(item['bytes']) for item in images)
            sent = 0
            receipts = []
            for index, item in enumerate(images):
                raw = item['bytes']
                if len(raw) > 180000 or hashlib.sha256(raw).hexdigest() != item['sha256']:
                    raise DeviceError(422, '图片编码校验失败')
                image_id = job['id'] + '-' + str(index)
                begin = dict(image_id=image_id, context_id=job['context_id'], mode=job['mode'],
                             project_id=job['project_id'], project_name=job['project_name'],
                             task_id=job['task_id'] or '', revision=job['revision'], kind=item['kind'],
                             title=item['title'][:100], bytes=len(raw), sha256=item['sha256'],
                             width=item['width'], height=item['height'])
                if job['image_slots'] > 2:
                    begin['gallery_slot'] = index
                self._rpc('begin', begin, job, connection)
                for offset in range(0, len(raw), CHUNK_BYTES):
                    chunk = raw[offset:offset + CHUNK_BYTES]
                    reply = self._rpc('chunk', dict(image_id=image_id, offset=offset,
                        data=base64.b64encode(chunk).decode('ascii')), job, connection)
                    if type(reply.get('offset')) is not int or reply['offset'] != offset + len(chunk):
                        raise DeviceError(409, '工牌图片接收位置不一致，请重新发送')
                    self._update(job, progress=min(99, int((sent + offset + len(chunk)) / total_bytes * 100)))
                # Recheck source ownership/registration before exposing a new image.
                with self.store.connect() as con:
                    current_ids = {row['id'] for row in badge_media.catalog(self.store, con, job['project_id'], job['task_id'])['items']}
                if item['id'] not in current_ids:
                    raise DeviceError(409, '图片来源已更新，请重新选择')
                reply = self._rpc('commit', dict(image_id=image_id, show=index == len(images) - 1), job, connection)
                if (reply.get('sha256') != item['sha256'] or reply.get('bytes') != len(raw)
                        or reply.get('context_id') != job['context_id']):
                    raise DeviceError(409, '工牌未确认完整图片校验结果')
                sent += len(raw)
                receipts.append(dict(image_id=image_id, kind=item['kind'], sha256=item['sha256'], bytes=len(raw)))
                self._update(job, persist=True, completed_images=index + 1)
            self._guard(job, connection)
            self._update(job, persist=True, status='received', progress=100, receipts=receipts,
                         finished_at=stamp(), error=None)
            with self.store.connect() as con:
                event = self.store.event(con, job['project_id'], 'device_images_received',
                    '工牌已接收' + str(len(images)) + '张' + ('项目预览图片' if job['mode'] == 'preview' else '任务图片'),
                    transfer_id=job['id'], mode=job['mode'], task_id=job['task_id'], revision=job['revision'])
                actor = job.get('requested_by')
                if actor and actor.get('access_enabled'):
                    event.update(actor=actor['name'], actor_id=actor['id'], actor_role=actor['role'], actor_person_id=actor.get('person_id'))
                    self.store.put(con, 'events', event)
        except Exception as exc:
            self._update(job, persist=True, status='error', error=getattr(exc, 'message', str(exc))[:500], finished_at=stamp())
