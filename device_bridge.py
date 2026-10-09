"""Optional USB NDJSON transport for KANPACE badges.

A single reader owns the port. Task delivery and actual worker execution are
separate protocols. Only the supplied transactional business handler may accept
an execution event; a delivery receipt never changes production task state.
"""
from __future__ import annotations

import fulfillment
from order_packet import VERSION as ORDER_PACKET_VERSION

import ipaddress
import json
import math
import re
import os
import secrets
import urllib.error
import urllib.request
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

PROTOCOL = 1
MAX_FRAME = 8192
DELIVERY_KIND = 'device_deliveries'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class DeviceError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


class DeviceBridge:
    def __init__(self, store, *, serial_factory=None, port_provider=None,
                 handshake_timeout=4.0, receipt_timeout=8.0, execution_handler=None):
        self.store = store
        self.handshake_timeout = handshake_timeout
        self.receipt_timeout = receipt_timeout
        self._factory = serial_factory
        self._port_provider = port_provider
        self._execution_handler = execution_handler
        self._lock = threading.RLock()
        self._control = threading.Lock()
        self._serial = None
        self._reader = None
        self._stop = None
        self._hello = threading.Event()
        self._hello_request = None
        self._pending = {}
        self._rpcs = {}
        self._expected_device_id = None
        self._wifi_session = None
        self._secrets_path = self.store.data_dir / 'device-secrets.json'
        self._secrets = self._read_secrets()
        saved = next(reversed(self._secrets.values()), {}) if self._secrets else {}
        self._wifi = dict(connected=False, configured=bool(saved), ssid=saved.get('ssid', ''),
                          ip=saved.get('host'), rssi=None, cached=True, observed_at=None, networks=[])
        self._state = dict(state='disconnected', connected=False, port=None, transport='usb', host=None,
                           baudrate=115200, device_id=None, chip=None, firmware=None,
                           protocol=None, last_seen=None, last_error=None,
                           dependency_available=False, execution_reporting=False, image_support=False, firmware_version=None,
                           image_slots=2, max_gallery_bytes=360000, safe_ready_replacement=False)
        from badge_image_transfer import BadgeImageTransfers
        self.images = BadgeImageTransfers(self)
        self._load_driver()
        # A process restart cannot preserve a live transport receipt expectation.
        with self.store.connect() as con:
            for delivery in self.store.all(con, DELIVERY_KIND):
                if delivery['status'] in ('queued', 'sent'):
                    delivery.update(status='failed', error='本地服务重启，未取得设备接收确认')
                    self.store.put(con, DELIVERY_KIND, delivery)

    def _load_driver(self):
        if self._factory is None:
            try:
                import serial
                from serial.tools import list_ports
                self._factory = serial.Serial
                self._port_provider = list_ports.comports
            except ImportError:
                return
        self._state['dependency_available'] = True

    def ports(self):
        self._load_driver()
        if not self._port_provider:
            return []
        result = []
        try:
            for port in self._port_provider():
                name = str(port.device)
                hwid = str(getattr(port, 'hwid', ''))
                vid = getattr(port, 'vid', None)
                # Deliberately exclude Bluetooth, debug ports and arbitrary paths.
                if vid is None and 'USB' not in hwid.upper() and not name.startswith(('/dev/cu.usb', '/dev/ttyUSB', '/dev/ttyACM')):
                    continue
                if name.startswith('/dev/tty.usb'):
                    continue
                result.append(dict(port=name, description=str(getattr(port, 'description', 'USB 串口')),
                                   manufacturer=getattr(port, 'manufacturer', None), vid=vid,
                                   pid=getattr(port, 'pid', None), serial_number=getattr(port, 'serial_number', None)))
        except Exception:
            return []
        return sorted(result, key=lambda item: item['port'])

    def snapshot(self):
        ports = self.ports()
        with self._lock:
            self._expire_pending()
            return {'device': self._device_state(), 'ports': ports}

    def deliveries(self):
        with self.store.connect() as con:
            records = self.store.all(con, DELIVERY_KIND)
        return {'deliveries': list(reversed(records[-100:]))}

    def connect(self, port=None, baudrate=115200, transport='usb', host=None):
        if transport == 'wifi':
            return self.connect_wifi(host)
        if transport != 'usb':
            raise DeviceError(400, '连接方式必须为 usb 或 wifi')
        if not isinstance(port, str) or not port:
            raise DeviceError(400, '请选择 USB 串口')
        if isinstance(baudrate, bool) or baudrate != 115200:
            raise DeviceError(400, '工牌协议串口速率固定为 115200')
        self._load_driver()
        if not self._factory:
            raise DeviceError(503, '未安装 pyserial；请安装 requirements-hardware.txt 后重启服务', self.snapshot())
        if port not in {item['port'] for item in self.ports()}:
            raise DeviceError(400, '所选端口不在当前 USB 串口列表中，请刷新设备列表')
        with self._control:
            self._disconnect()
            with self._lock:
                self._expected_device_id = None
                self._state.update(state='connecting', connected=False, port=port, transport='usb', host=None,
                                   baudrate=baudrate, device_id=None, chip=None, firmware=None,
                                   protocol=None, last_seen=None, last_error=None)
                self._hello.clear()
                # No command may reach an unknown firmware: legacy SparkLink
                # interprets individual JSON characters as interaction actions.
                self._hello_request = None
                try:
                    # Opening with inactive modem controls avoids an intentional
                    # reset sequence. Some USB drivers may still reset on open.
                    serial_port = self._factory(port=None, baudrate=baudrate, timeout=.15, write_timeout=1)
                    serial_port.dtr = False
                    serial_port.rts = False
                    serial_port.port = port
                    serial_port.open()
                    self._serial = serial_port
                    self._stop = threading.Event()
                    self._reader = threading.Thread(target=self._read_loop,
                        args=(serial_port, self._stop), name='cabinet-badge-reader', daemon=True)
                    self._reader.start()
                except Exception as exc:
                    self._state.update(state='error', last_error='无法打开 USB 串口：' + str(exc))
                    self._close_port()
                    raise DeviceError(409, self._state['last_error'], self.snapshot())
            # One bounded window covers passive discovery and the subsequent
            # challenge. Only the announced exact firmware is eligible for writes.
            deadline = time.monotonic() + self.handshake_timeout
            last_hello_at = 0.0
            while time.monotonic() < deadline and not self._hello.wait(min(.05, max(.001, deadline-time.monotonic()))):
                with self._lock:
                    if self._state['state'] != 'connecting':
                        break
                    if not self._expected_device_id:
                        continue  # Passive listening: zero serial writes.
                    if self._hello_request is None:
                        self._hello_request = 'hello_' + uuid4().hex
                    if time.monotonic() - last_hello_at < .7:
                        continue
                    try:
                        self._write({'type': 'hello', 'protocol': PROTOCOL, 'request_id': self._hello_request})
                        last_hello_at = time.monotonic()
                    except Exception:
                        break
            with self._lock:
                if self._state['state'] != 'ready':
                    detail = self._state['last_error'] or (
                        '已识别KANPACE固件公告，但没有收到匹配的握手回复；请检查板卡连接'
                        if self._expected_device_id else
                        '未发现兼容的KANPACE固件公告，未向串口发送任何命令；请先升级工牌固件')
                    self._state.update(state='incompatible', connected=False, last_error=detail)
                    self._close_port()
                    raise DeviceError(409, detail, self.snapshot())
            return self.snapshot()

    def _close_port(self):
        if self._stop:
            self._stop.set()
        port, self._serial = self._serial, None
        if port:
            try:
                port.close()
            except Exception:
                pass

    def _disconnect(self):
        with self._lock:
            reader = self._reader
            self._close_port()
            for identifier in list(self._pending):
                self._finish(identifier, 'failed', '串口已断开，未取得设备接收确认')
            self._state.update(state='disconnected', connected=False, device_id=None,
                               chip=None, firmware=None, protocol=None, execution_reporting=False,
                               image_support=False, firmware_version=None)
            self._reader = None
            self._wifi_session = None
            self._wifi['cached'] = True
            for rpc in self._rpcs.values():
                rpc['event'].set()
        if reader and reader is not threading.current_thread():
            reader.join(timeout=.8)

    def disconnect(self):
        with self._control:
            self._disconnect()
        return self.snapshot()

    def _read_secrets(self):
        try:
            with self._secrets_path.open(encoding='utf-8') as stream:
                records = json.load(stream)
            if isinstance(records, dict):
                os.chmod(self._secrets_path, 0o600)
                return {key: value for key, value in records.items()
                        if isinstance(key, str) and isinstance(value, dict)
                        and isinstance(value.get('token'), str)}
        except (OSError, ValueError):
            pass
        return {}

    def _save_secrets(self):
        # The WiFi password is never stored on the computer. Only the random
        # device token and observed non-secret LAN address are kept locally.
        temporary = self._secrets_path.with_name('.device-secrets-' + uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(self._secrets, stream, ensure_ascii=False)
            os.replace(temporary, self._secrets_path)
            os.chmod(self._secrets_path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _device_error(frame):
        code = frame.get('error')
        if not isinstance(code, str) or not re.fullmatch(r'[a-z0-9_]{1,80}', code):
            return '工牌拒绝此请求，未确认接收'
        labels = {'storage_write_failed':'工牌存储写入失败，任务未被确认保存',
                  'invalid_task':'任务字段不符合工牌协议',
                  'delivery_conflict':'下发编号与工牌已保存内容冲突',
                  'task_mode_required':'请先将工牌切换到任务模式',
                  'wifi_storage_failed':'工牌未能保存无线配置',
                  'wifi_scan_failed':'工牌无线扫描失败，请稍后重试',
                  'wifi_scan_timeout':'工牌无线扫描超时，请重新扫描',
                  'invalid_wifi_config':'无线配置格式不符合工牌要求',
                  'image_storage_unavailable':'工牌图片存储尚未就绪，请重新连接',
                  'image_storage_full':'工牌图片空间不足',
                  'invalid_image_metadata':'图片信息无效，请重新选择图片',
                  'image_task_mismatch':'图片与工牌当前任务不匹配，请重新下发任务',
                  'image_context_conflict':'图片所属项目或版本不一致，请重新选择',
                  'image_id_conflict':'图片发送记录冲突，请重新发送',
                  'image_storage_write_failed':'工牌未能保存图片，请重新发送',
                  'image_transfer_missing':'图片传输已中断，请重新发送',
                  'invalid_image_chunk':'图片传输数据无效，请重新发送',
                  'invalid_image_base64':'图片传输数据损坏，请重新发送',
                  'image_offset_mismatch':'图片接收位置不一致，请重新发送',
                  'image_incomplete':'图片尚未接收完整，请重新发送',
                  'image_hash_mismatch':'图片校验失败，请重新发送',
                  'invalid_image_jpeg':'工牌无法解码此图片，请重新选择',
                  'image_catalog_write_failed':'工牌未能保存图册，请重新发送',
                  'image_context_unavailable':'工牌暂无此项目的图册，请先发送图片',
                  'image_kind_unavailable':'工牌尚未收到这类图片'}
        return labels.get(code, '工牌拒绝此请求') + '（' + code + '）'

    @staticmethod
    def _validate_task_payload(payload):
        task = payload['task']
        fields = {'id':128, 'project_id':128, 'project_name':512, 'title':512,
                  'trade':128, 'assignee':256, 'instructions':4096,
                  'acceptance':4096, 'status':64}
        required = {'id', 'project_id', 'project_name', 'title', 'trade'}
        for key, limit in fields.items():
            if key == 'instructions' and key not in task:
                continue  # Protocol-1 tasks saved before this field remain readable.
            value = task.get(key)
            if not isinstance(value, str) or (key in required and not value):
                raise DeviceError(400, '工牌任务字段无效：' + key)
            try:
                size = len(value.encode('utf-8'))
            except UnicodeEncodeError:
                raise DeviceError(400, '任务含无效 Unicode 字符：' + key) from None
            if size > limit:
                raise DeviceError(413, '工牌任务字段 ' + key + ' 超过 ' + str(limit) + ' 字节，请缩短后再发')
        if type(task.get('revision')) is not int or not 1 <= task['revision'] <= 2147483647:
            raise DeviceError(400, '工牌任务版本号无效')
        for key in ('quantity', 'hours'):
            value = task.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e9):
                raise DeviceError(400, '工牌任务数值字段无效：' + key)
        # Optional protocol-1 execution fields. A legacy task has unknown
        # progress; transport must not turn missing history into completed=0.
        recorded = task.get('progress_recorded', False)
        if not isinstance(recorded, bool):
            raise DeviceError(400, '工牌任务 progress_recorded 必须为布尔值')
        for key in ('completed_quantity', 'remaining_quantity'):
            value = task.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000_000):
                raise DeviceError(400, '工牌任务进度字段无效：' + key)
        if recorded:
            total, completed, remaining = (task.get(key) for key in ('quantity', 'completed_quantity', 'remaining_quantity'))
            if (type(total) not in (int, float) or not math.isfinite(total) or total != int(total)
                    or type(completed) is not int or type(remaining) is not int
                    or completed > total or completed + remaining != total):
                raise DeviceError(400, '工牌任务已做、剩余与总数量不一致')
        for key, maximum in (('priority', 3), ('execution_version', 2147483647)):
            value = task.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= maximum):
                raise DeviceError(400, '工牌任务执行字段无效：' + key)
        if task.get('pause_reason') not in (None, 'material', 'quality', 'equipment', 'urgent', 'other'):
            raise DeviceError(400, '工牌任务暂停原因无效')
        for key, limit in (('pause_note', 4096), ('handover_note', 8192),
                           ('paused_at', 64), ('resumed_at', 64), ('interrupted_by_task_id', 128)):
            value = task.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise DeviceError(400, '工牌任务执行字段无效：' + key)
                try:
                    length = len(value.encode('utf-8'))
                except UnicodeEncodeError:
                    raise DeviceError(400, '任务含无效 Unicode 字符：' + key) from None
                if length > limit:
                    raise DeviceError(413, '工牌任务字段 ' + key + ' 超过 ' + str(limit) + ' 字节，请缩短后再发')
        if not isinstance(task.get('source'), dict):
            raise DeviceError(400, '工牌任务来源必须为对象')
        def validate_tree(value, depth=0):
            if depth > 12:
                raise DeviceError(400, '任务来源嵌套层级超过工牌限制')
            if isinstance(value, str):
                if '\0' in value:
                    raise DeviceError(400, '任务不能包含 NUL 控制字符')
                try:
                    value.encode('utf-8')
                except UnicodeEncodeError:
                    raise DeviceError(400, '任务含无效 Unicode 字符') from None
            elif isinstance(value, (dict, list)):
                if len(value) > 256:
                    raise DeviceError(400, '任务来源字段数超过工牌限制')
                if isinstance(value, dict):
                    for key, child in value.items():
                        validate_tree(key, depth+1)
                        validate_tree(child, depth+1)
                else:
                    for child in value:
                        validate_tree(child, depth+1)
        validate_tree(payload)

    def _device_state(self):
        return dict(self._state, wifi=dict(self._wifi))

    def _expire_pending(self):
        for identifier, pending in list(self._pending.items()):
            if time.monotonic() >= pending['deadline']:
                self._finish(identifier, 'timeout', '任务已发出，但超时未收到设备接收确认；请检查工牌后再重发')

    @staticmethod
    def _private_host(host):
        if not isinstance(host, str):
            return False
        try:
            address = ipaddress.ip_address(host)
            return isinstance(address, ipaddress.IPv4Address) and any(address in network for network in (
                ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'), ipaddress.ip_network('192.168.0.0/16')))
        except ValueError:
            return False

    def _http_frame(self, message):
        session = self._wifi_session
        if not session:
            raise DeviceError(409, 'WiFi 工牌未连接')
        action = {'hello':'hello', 'task':'task', 'wifi_status':'wifi_status'}.get(message.get('type'))
        if not action:
            raise DeviceError(400, '不支持通过 WiFi 执行此设备操作')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        body = json.dumps(message, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(body) > MAX_FRAME:
            raise DeviceError(413, '任务载荷超过工牌 8192 字节容量')
        request = urllib.request.Request('http://' + session['host'] + '/cabinet/' + action,
            data=body, headers={'Content-Type':'application/json', 'Authorization':'Bearer ' + session['token']}, method='POST')
        # Avoid environment proxies and cross-host redirects carrying credentials.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=3) as response:
                if response.status != 200:
                    raise DeviceError(409, '工牌 WiFi 接口返回非成功状态')
                raw = response.read(MAX_FRAME + 1)
            if len(raw) > MAX_FRAME:
                raise DeviceError(409, '工牌返回的 WiFi 数据超过协议长度')
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                raise ValueError('invalid response')
            return frame
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            exc.close()
            raise DeviceError(409, '工牌 WiFi 认证失败或接口不可用（HTTP ' + str(status_code) + '）') from None
        except (OSError, ValueError, urllib.error.URLError):
            raise DeviceError(409, '无法取得工牌 WiFi 回复；请确认电脑与工牌在同一局域网、IP 地址正确且供电正常') from None

    def _wifi_failure(self, message):
        self._state.update(state='error', connected=False, last_error=message)
        self._wifi.update(connected=False, cached=True)
        self._wifi_session = None

    def connect_wifi(self, host):
        if not self._private_host(host):
            raise DeviceError(400, 'WiFi 地址必须为局域网 IPv4 地址，不接受网址或公网地址')
        matching = [(identifier, record) for identifier, record in self._secrets.items() if record.get('host') == host]
        if len(matching) != 1:
            raise DeviceError(409, '请先用 USB 配置此工牌的 WiFi，并刷新无线状态取得已验证的 IP 地址')
        identifier, record = matching[0]
        with self._control:
            self._disconnect()
            with self._lock:
                self._expected_device_id = identifier
                self._hello_request = 'hello_' + uuid4().hex
                self._hello.clear()
                self._wifi_session = dict(host=host, device_id=identifier, token=record['token'])
                self._state.update(state='connecting', connected=False, transport='wifi', port=None, host=host,
                                   device_id=None, chip=None, firmware=None, protocol=None, last_error=None)
                try:
                    frame = self._http_frame(dict(type='hello', protocol=PROTOCOL, request_id=self._hello_request))
                    self._handle(frame)
                    if self._state['state'] != 'ready':
                        raise DeviceError(409, 'WiFi 回复未通过工牌身份和协议验证')
                    self._wifi.update(ip=host, connected=True, cached=False, observed_at=stamp())
                except DeviceError as exc:
                    self._wifi_failure(exc.message)
                    raise DeviceError(exc.status, exc.message, self.snapshot()) from None
            return self.snapshot()

    def _usb_rpc(self, frame_type, fields=None, timeout=4, expected_device_id=None, reply_type=None):
        with self._lock:
            if self._state['state'] != 'ready' or self._state['transport'] != 'usb' or not self._serial:
                raise DeviceError(409, '此操作需先通过 USB 连接兼容的KANPACE工牌')
            if expected_device_id and self._state['device_id'] != expected_device_id:
                raise DeviceError(409, 'USB 工牌已切换，请重新确认设备后操作')
            request_id = 'rpc_' + uuid4().hex
            rpc = dict(type=frame_type, reply_type=reply_type or frame_type,
                       device_id=self._state['device_id'], event=threading.Event(), reply=None)
            self._rpcs[request_id] = rpc
            try:
                self._write(dict(type=frame_type, protocol=PROTOCOL, request_id=request_id, **(fields or {})))
            except Exception:
                self._rpcs.pop(request_id, None)
                raise DeviceError(409, 'USB 请求未发出，请检查连接') from None
        rpc['event'].wait(timeout)
        with self._lock:
            self._rpcs.pop(request_id, None)
            if not rpc['reply']:
                raise DeviceError(504, '未收到工牌回复，请检查 USB 连接后重试')
            if rpc['reply'].get('type') == 'error':
                message = self._device_error(rpc['reply'])
                self._state['last_error'] = message
                raise DeviceError(409, message)
            self._state['last_error'] = None
            return rpc['reply']

    def wifi_scan(self):
        frame = self._usb_rpc('wifi_scan')
        networks = frame.get('networks', [])
        if not isinstance(networks, list):
            networks = []
        clean = []
        for network in networks[:50]:
            if not isinstance(network, dict) or not isinstance(network.get('ssid'), str):
                continue
            clean.append(dict(ssid=network['ssid'][:32], rssi=network.get('rssi') if type(network.get('rssi')) is int else None,
                              secure=bool(network.get('secure'))))
        with self._lock:
            self._wifi.update(networks=clean, scan_pending=frame.get('scan_pending') is True)
            return {'wifi':dict(self._wifi), 'device':self._device_state()}

    def wifi_config(self, ssid, password):
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32:
            raise DeviceError(400, 'WiFi 名称须为 1–32 字节')
        if not isinstance(password, str) or len(password.encode('utf-8')) > 63 or (password and len(password.encode('utf-8')) < 8):
            raise DeviceError(400, 'WiFi 密码须为空（开放网络）或 8–63 字节')
        with self._lock:
            if self._state['state'] != 'ready' or self._state['transport'] != 'usb':
                raise DeviceError(409, '请先通过 USB 连接兼容的KANPACE工牌，再写入 WiFi 配置')
            identifier = self._state['device_id']
            record = self._secrets.get(identifier, {})
            record = dict(token=record.get('token') or secrets.token_hex(32), ssid=ssid, host=None)
            self._secrets[identifier] = record
            self._save_secrets()
            token = record['token']
        # Credentials go only over the user-selected, handshaken USB connection.
        frame = self._usb_rpc('wifi_config', {'ssid':ssid, 'password':password, 'token':token}, expected_device_id=identifier)
        if frame.get('configured') is not True:
            raise DeviceError(409, '工牌没有确认保存 WiFi 配置；请检查网络名称和密码格式')
        with self._lock:
            self._wifi.update(configured=True, connected=False, ssid=ssid, ip=None, rssi=None,
                              cached=True, observed_at=None)
            return {'wifi':dict(self._wifi), 'device':self._device_state()}

    def wifi_status(self):
        with self._lock:
            state = self._state['state']
            transport = self._state['transport']
            identifier = self._state['device_id']
        if state != 'ready':
            with self._lock:
                self._wifi['cached'] = True
                return {'wifi':dict(self._wifi), 'device':self._device_state()}
        if transport == 'usb':
            frame = self._usb_rpc('wifi_status', expected_device_id=identifier)
        else:
            with self._lock:
                request_id = 'wifi_' + uuid4().hex
                try:
                    frame = self._http_frame(dict(type='wifi_status', protocol=PROTOCOL, request_id=request_id))
                    if (frame.get('request_id') != request_id or frame.get('device_id') != identifier
                        or frame.get('type') != 'wifi_status' or type(frame.get('protocol')) is not int or frame.get('protocol') != PROTOCOL):
                        raise DeviceError(409, 'WiFi 状态回复未通过设备身份验证')
                except DeviceError as exc:
                    self._wifi_failure(exc.message)
                    raise DeviceError(exc.status, exc.message, self.snapshot()) from None
        with self._lock:
            host = frame.get('ip') if self._private_host(frame.get('ip')) else None
            self._wifi.update(connected=frame.get('connected') is True, configured=frame.get('configured') is True,
                ssid=frame.get('ssid', '')[:32] if isinstance(frame.get('ssid'), str) else '',
                ip=host, rssi=frame.get('rssi') if type(frame.get('rssi')) is int else None,
                device_id=identifier, cached=False, observed_at=stamp())
            self._state['last_seen'] = stamp()
            if self._wifi['connected'] and host and identifier in self._secrets:
                self._secrets[identifier].update(host=host, ssid=self._wifi['ssid'])
                self._save_secrets()
            return {'wifi':dict(self._wifi), 'device':self._device_state()}

    def _write(self, message):
        raw = json.dumps(message, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
        if len(raw) > MAX_FRAME:
            raise DeviceError(413, '任务载荷超过工牌 8192 字节容量，请缩短验收说明或来源信息')
        if not self._serial:
            raise DeviceError(409, '设备未连接')
        written = self._serial.write(raw)
        if written != len(raw):
            raise OSError('串口未写完完整任务帧')

    def _task_payload(self, con, task):
        """Full versioned display snapshot, shared by delivery and business ACK."""
        project = self.store.get(con, 'projects', task['project_id'])
        people = {p['id']: p['name'] for p in self.store.all(con, 'people')}
        payload = {key: task.get(key) for key in ('id', 'project_id', 'revision', 'title', 'trade', 'quantity', 'hours', 'instructions', 'acceptance', 'source', 'status')}
        payload['source'] = payload['source'] or {}
        # Older order packets copied the whole cabinet material note to every
        # trade. Never relay that note as a trade-specific badge instruction.
        payload['instructions'] = '' if self._legacy_packet_task(task) else (payload['instructions'] or '')
        payload['acceptance'] = payload['acceptance'] or ''
        payload['assignee'] = people.get(task.get('assignee'), '')
        payload['project_name'] = project['name']
        payload['requires_web_inspection'] = bool(task.get('inspection_required')) or task.get('trade') == '质检' or (task.get('part_id') is None and task.get('process') == 'electrical')
        payload['daily'] = self.store.daily_workflow.badge_context(con, task)
        payload['execution_allowed'] = (not fulfillment.is_closed(project) and not project.get('archived')
            and not task.get('archived') and project.get('status') == 'released'
            and task.get('revision') == project.get('released_revision') == project.get('revision')
            and task.get('status') in ('ready', 'in_progress', 'blocked'))
        for key in ('priority', 'pause_reason', 'pause_note', 'handover_note',
                    'paused_at', 'resumed_at', 'interrupted_by_task_id', 'execution_version'):
            payload[key] = task.get(key)
        payload['progress_recorded'] = task.get('progress_recorded', False)
        for key in ('completed_quantity', 'remaining_quantity'):
            value = task.get(key) if payload['progress_recorded'] else None
            if type(value) is float and math.isfinite(value) and value.is_integer():
                value = int(value)
            payload[key] = value
        return payload

    @staticmethod
    def _legacy_packet_task(task):
        return bool(task.get('packet_generated')) and task.get('rule_id') != ORDER_PACKET_VERSION

    def send_task(self, identifier, test_mode=False, *, dispatch_context=None):
        if not isinstance(test_mode, bool):
            raise DeviceError(400, 'test_mode 必须为布尔值')
        with self._lock:
            if self.images.busy():
                raise DeviceError(409, '工牌正在接收图片，请等待完成后再下发任务')
            if self._pending:
                raise DeviceError(409, '胸牌正在确认上一项任务，请等待真实回执')
            # Production guards apply even for test mode. No mutation is allowed
            # to turn an obsolete instruction into a sendable work order.
            with self.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                task = self.store.get(con, 'tasks', identifier)
                project = self.store.get(con, 'projects', task['project_id'])
                if dispatch_context and self.store.get(con, 'project_dispatches', dispatch_context['dispatch_id'])['status'] in ('cancelled', 'completed'):
                    raise DeviceError(409, '项目派工队列已停止，未继续下发任务')
                if dispatch_context and (task.get('assignee') != dispatch_context.get('expected_assignee')
                        or task.get('revision') != dispatch_context.get('expected_revision')
                        or task.get('execution_version') != dispatch_context.get('expected_execution_version')
                        or self._state.get('device_id') != dispatch_context.get('device_id')):
                    raise DeviceError(409, '项目派工人员、工程版本或胸牌连接已变化')
                if fulfillment.is_closed(project):
                    raise DeviceError(409, '项目已完成或发货，不能下发任务到工牌')
                if task.get('archived') or project.get('archived') or task.get('status') in ('done', 'invalidated'):
                    raise DeviceError(409, '已完成、失效或归档的任务不能下发到工牌')
                if task.get('status') not in ('ready', 'blocked', 'in_progress'):
                    raise DeviceError(409, '任务尚未发布，不能下发到工牌')
                if self._legacy_packet_task(task):
                    raise DeviceError(409, '旧版拆单任务含整柜材料说明，请重新拆单复核后派工')
                if project.get('status') != 'released' or task.get('revision') != project.get('revision') or task.get('revision') != project.get('released_revision'):
                    raise DeviceError(409, '必须先复核并发布当前工程版本，再下发任务到工牌')
                if self._state['state'] != 'ready' or not (self._serial or self._wifi_session):
                    raise DeviceError(409, '请先连接并完成KANPACE工牌协议握手')
                payload_task = self._task_payload(con, task)
                identifier = 'delivery_' + uuid4().hex
                request_id = 'req_' + uuid4().hex
                test_mode = test_mode or bool(project.get('demo'))
                payload = dict(type='task', protocol=PROTOCOL, delivery_id=identifier,
                               request_id=request_id, test_mode=test_mode, task=payload_task)
                self._validate_task_payload(payload)
                raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                if len(raw) + 1 > MAX_FRAME:
                    raise DeviceError(413, '任务载荷超过工牌 8192 字节容量，请缩短验收说明或来源信息')
                delivery = dict(id=identifier, request_id=request_id, task_id=task['id'],
                    project_id=project['id'], project_name=project['name'], task_title=task['title'],
                    trade=task['trade'], revision=task['revision'], device_id=self._state['device_id'],
                    assignee_id=task.get('assignee'), execution_version=task.get('execution_version', 0),
                    port=self._state['port'], transport=self._state['transport'], host=self._state['host'], test_mode=test_mode, status='queued', created_at=stamp(),
                    sent_at=None, received_at=None, error=None, payload=payload)
                if dispatch_context:
                    delivery['dispatch_id'] = dispatch_context['dispatch_id']
                    delivery['dispatch_attempt'] = dispatch_context.get('attempt', 0)
                self.store.put(con, DELIVERY_KIND, delivery)
            self._send_generation = getattr(self, '_send_generation', 0) + 1
            try:
                reply = None
                if self._state['transport'] == 'wifi':
                    reply = self._http_frame(payload)
                else:
                    self._write(payload)
                delivery.update(status='sent', sent_at=stamp())
                with self.store.connect() as con:
                    self.store.put(con, DELIVERY_KIND, delivery)
                    self.store.event(con, project['id'], 'device_task_sent',
                        ('测试任务' if test_mode else '任务') + '已通过' + ('WiFi' if self._state['transport'] == 'wifi' else 'USB串口') + '发出，等待设备确认：' + task['title'],
                        delivery_id=identifier, task_id=task['id'], revision=task['revision'], test_mode=test_mode)
                self._pending[identifier] = dict(deadline=time.monotonic()+self.receipt_timeout, delivery=delivery)
                if reply is not None:
                    self._handle(reply)
                    with self.store.connect() as con:
                        delivery = self.store.get(con, DELIVERY_KIND, identifier)
            except Exception as exc:
                delivery.update(status='failed', error='设备通信失败，未取得接收确认：' + str(exc))
                with self.store.connect() as con:
                    self.store.put(con, DELIVERY_KIND, delivery)
                self._state['last_error'] = delivery['error']
                if self._state['transport'] == 'wifi':
                    self._wifi_failure(delivery['error'])
                else:
                    self._state.update(state='error', connected=False)
                    self._close_port()
                raise DeviceError(409, delivery['error'], {'delivery': delivery})
            return {'delivery': dict(delivery), 'device': self._device_state()}

    def _finish(self, identifier, status, error=None):
        pending = self._pending.pop(identifier, None)
        if not pending:
            return
        delivery = dict(pending['delivery'])
        delivery.update(status=status, error=error)
        if status == 'received':
            delivery['received_at'] = stamp()
        with self.store.connect() as con:
            self.store.put(con, DELIVERY_KIND, delivery)
            if status == 'received':
                self.store.event(con, delivery['project_id'], 'device_task_received',
                    '工牌已确认接收' + ('测试' if delivery['test_mode'] else '') + '任务：' + delivery['task_title'],
                    delivery_id=identifier, task_id=delivery['task_id'], device_id=delivery['device_id'],
                    revision=delivery['revision'], test_mode=delivery['test_mode'])
        if status == 'received' and self._state.get('image_support') and self._state['transport'] == 'usb':
            try:
                self.images.start({'project_id': delivery['project_id'], 'task_id': delivery['task_id'],
                                   'mode': 'task', 'delivery_id': delivery['id']}, automatic=True)
            except DeviceError:
                pass  # Task receipt stays valid; the image panel allows an explicit retry.

    def _handle(self, frame):
        if not isinstance(frame, dict) or type(frame.get('protocol')) is not int or frame.get('protocol') != PROTOCOL:
            return
        with self._lock:
            if frame.get('type') == 'execution_event':
                self._handle_execution(frame)
                return
            request_id = frame.get('request_id')
            if isinstance(request_id, str) and request_id in self._rpcs:
                rpc = self._rpcs[request_id]
                if frame.get('type') in (rpc.get('reply_type', rpc['type']), 'error') and frame.get('device_id') == rpc['device_id']:
                    rpc['reply'] = frame
                    rpc['event'].set()
                    self._state['last_seen'] = stamp()
                return
            if frame.get('type') == 'hello' and self._state['state'] == 'connecting':
                if (frame.get('chip') != 'ESP32-C3'
                    or not isinstance(frame.get('device_id'), str) or not frame['device_id']
                    or len(frame['device_id']) > 128 or frame.get('firmware') != 'cabinet-badge-1'
                    or (self._expected_device_id and frame['device_id'] != self._expected_device_id)):
                    return
                if (self._state['transport'] == 'usb' and self._hello_request is None
                    and 'request_id' not in frame):
                    # An unsolicited announcement identifies a compatible
                    # protocol without sending potentially active legacy input.
                    self._expected_device_id = frame['device_id']
                    return
                if self._hello_request is None or frame.get('request_id') != self._hello_request:
                    return
                self._state.update(state='ready', connected=True, device_id=frame['device_id'],
                                   chip=frame['chip'], firmware=frame['firmware'], protocol=PROTOCOL,
                                   execution_reporting=frame.get('execution_reporting') is True,
                                   image_support=frame.get('image_support') is True,
                                   safe_ready_replacement=frame.get('safe_ready_replacement') is True,
                                   firmware_version=frame.get('firmware_version'),
                                   image_slots=frame.get('max_images_per_task', frame.get('image_slots', 2))
                                       if type(frame.get('max_images_per_task', frame.get('image_slots', 2))) is int and 1 <= frame.get('max_images_per_task', frame.get('image_slots', 2)) <= 6 else 2,
                                   max_gallery_bytes=frame.get('max_gallery_bytes', 360000)
                                       if type(frame.get('max_gallery_bytes', 360000)) is int and 20000 <= frame.get('max_gallery_bytes', 360000) <= 660000 else 360000,
                                   last_seen=stamp(), last_error=None)
                self._hello.set()
            elif frame.get('type') == 'error' and self._state['state'] == 'ready':
                pending = self._pending.get(frame.get('delivery_id'))
                if pending:
                    delivery = pending['delivery']
                    if frame.get('request_id') == delivery['request_id'] and frame.get('device_id') == delivery['device_id']:
                        message = self._device_error(frame)
                        self._state['last_error'] = message
                        self._finish(delivery['id'], 'failed', message)
            elif frame.get('type') == 'ack' and self._state['state'] == 'ready':
                pending = self._pending.get(frame.get('delivery_id'))
                if not pending:
                    return
                delivery = pending['delivery']
                if (frame.get('received') is not True or type(frame.get('revision')) is not int
                    or any(frame.get(key) != delivery[key] for key in ('request_id', 'task_id', 'revision', 'device_id'))
                    or frame.get('device_id') != self._state['device_id']):
                    self._state['last_error'] = '忽略未匹配当前设备、任务及版本的回执'
                    return
                self._state.update(last_seen=stamp(), last_error=None)
                self._finish(delivery['id'], 'received')

    @staticmethod
    def validate_execution_frame(frame):
        """Reject ambiguous numeric versions and malformed frames before business IO."""
        for key in ('event_id', 'device_id', 'task_id', 'delivery_id'):
            value = frame.get(key)
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
                raise DeviceError(400, '工牌报工标识格式错误')
        for key in ('revision', 'execution_version'):
            value = frame.get(key)
            if type(value) is not int or not (1 if key == 'revision' else 0) <= value <= 2147483647:
                raise DeviceError(400, '工牌报工版本格式错误')
        action = frame.get('action')
        if action not in ('start', 'pause', 'resume', 'finish', 'label_confirm'):
            raise DeviceError(400, '工牌报工动作无效')
        if action == 'label_confirm' and (not isinstance(frame.get('label_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', frame['label_id'])):
            raise DeviceError(400, '请确认与本件相符的标签编号')
        if action == 'pause' and frame.get('reason') not in ('material', 'equipment', 'quality', 'urgent', 'other'):
            raise DeviceError(400, '请选择有效暂停原因')
        for key in ('note', 'handover_note'):
            if key in frame and (not isinstance(frame[key], str) or len(frame[key]) > 2000):
                raise DeviceError(400, '工牌报工说明过长或格式错误')
        if 'completed_quantity' in frame:
            if type(frame['completed_quantity']) is not int or not 0 <= frame['completed_quantity'] <= 1000000000:
                raise DeviceError(400, '工牌报工数量必须为非负整数')
        if action == 'finish' and 'completed_quantity' not in frame:
            raise DeviceError(400, '完工必须确认数量')

    def _handle_execution(self, frame):
        # A port announcement is insufficient. Only this challenged USB session
        # can submit; LAN execution has not been implemented or validated yet.
        if (self._state['state'] != 'ready' or self._state['transport'] != 'usb'
                or not self._serial or frame.get('device_id') != self._state['device_id']):
            return
        # Never acknowledge an unaddressable event (the device must retain it).
        if any(not isinstance(frame.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', frame[key])
               for key in ('event_id', 'task_id')):
            return
        reply = dict(type='execution_ack', protocol=PROTOCOL, device_id=self._state['device_id'],
                     event_id=frame['event_id'], task_id=frame['task_id'], accepted=False,
                     retryable=False)
        try:
            self.validate_execution_frame(frame)
        except DeviceError as exc:
            result = dict(accepted=False, code='invalid_event', message=exc.message)
        else:
            try:
                if self._execution_handler is None:
                    result = dict(accepted=False, retryable=True, code='execution_unavailable', message='服务尚未启用工牌报工')
                else:
                    result = self._execution_handler(dict(frame))
                    if not isinstance(result, dict) or type(result.get('accepted')) is not bool:
                        raise ValueError('invalid business handler response')
            except Exception:
                # The transaction may have committed before transport failure.
                # Retrying the SAME event id is the only safe recovery.
                result = dict(accepted=False, retryable=True, code='service_retry', message='服务暂不可用，报工已保留')
        for key in ('accepted', 'retryable', 'duplicate', 'code', 'message'):
            if key in result:
                reply[key] = result[key]
        if isinstance(reply.get('message'), str):
            reply['message'] = reply['message'][:500]
        returned_task = result.get('task')
        snapshot_task = returned_task
        if isinstance(returned_task, dict) and returned_task.get('id') == frame['task_id']:
            try:
                with self.store.connect() as con:
                    task = self.store.get(con, 'tasks', frame['task_id'])
                    snapshot_task = task
                    wire_task = self._task_payload(con, task)
                try:
                    self._validate_task_payload({'task': wire_task})
                    reply['task'] = wire_task
                except DeviceError:
                    reply['task'] = self._execution_refresh_payload(task)
            except Exception:
                pass  # Event result remains valid; do not invent a task snapshot.
        raw = json.dumps(reply, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(raw) + 1 > MAX_FRAME:
            if isinstance(returned_task, dict):
                reply['task'] = self._execution_refresh_payload(snapshot_task)
            else:
                reply.pop('task', None)
        if reply.get('task', {}).get('refresh_required') and reply['accepted']:
            reply['message'] = '报工已确认，请重新下发任务'
        self._write(reply)
        self._state['last_seen'] = stamp()
        self._state['last_execution'] = {key: reply.get(key) for key in
                                       ('event_id', 'task_id', 'accepted', 'retryable', 'code', 'message', 'duplicate')}

    @staticmethod
    def _execution_refresh_payload(task):
        """Confirm durable facts even if a concurrent edit exceeds display size.

        The terminal explicitly requires a new full delivery and cannot execute
        abbreviated instructions. No original instruction is silently truncated.
        """
        fields = ('id', 'project_id', 'revision', 'quantity', 'status', 'execution_version',
                  'completed_quantity', 'remaining_quantity', 'progress_recorded', 'priority', 'pause_reason')
        payload = {key: task.get(key) for key in fields}
        if not payload.get('progress_recorded'):
            payload['completed_quantity'] = payload['remaining_quantity'] = None
        payload.update(project_name='待重新下发', title='任务内容已更新', trade='工位', assignee='',
                       instructions='', acceptance='', source={}, hours=None, execution_allowed=False, refresh_required=True,
                       pause_note='', handover_note='')
        return payload

    def _read_loop(self, serial_port, stop):
        buffer = bytearray()
        dropping = False
        try:
            while not stop.is_set():
                chunk = serial_port.read(512)
                if stop.is_set():
                    return
                for byte in chunk:
                    if byte == 10:
                        if not dropping and buffer:
                            try:
                                self._handle(json.loads(buffer.decode('utf-8')))
                            except (UnicodeDecodeError, ValueError, TypeError):
                                pass  # Boot text and unrelated serial lines are not receipts.
                        buffer.clear()
                        dropping = False
                    elif not dropping:
                        buffer.append(byte)
                        if len(buffer) >= MAX_FRAME:
                            buffer.clear()
                            dropping = True
                with self._lock:
                    if stop.is_set():
                        return
                    self._expire_pending()
        except Exception as exc:
            if stop.is_set():
                return
            with self._lock:
                self._state.update(state='error', connected=False, last_error='USB 连接中断：' + str(exc))
                for identifier in list(self._pending):
                    self._finish(identifier, 'failed', self._state['last_error'])
                self._close_port()
                self._hello.set()
