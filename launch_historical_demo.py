#!/usr/bin/env python3
"""Run a private, isolated KANPACE demo made from historical customer orders.

The import job creates the database and a matching identity marker first. This
launcher never imports source material, initializes an unmarked directory, or
opens the regular factory's data directory. Hardware transport and background
badge dispatch are disabled even when a caller bypasses the HTTP routes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
import re
import sqlite3
import sys
import threading
import urllib.request
import uuid
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


BASE = Path(__file__).resolve().parent
MARKER_NAME = '.kanpace-historical-demo.json'
CONFIG_KEY = 'historical_demo'
IDENTITY = 'kanpace.historical.standalone-demo'
VERSION = 1
NOTICE = '真实历史资料演示副本；客户与技术确认未补签，不可用作加工或实际派工。'
PERSONNEL_SOURCE = 'personnel-roster.xlsx'
PERSONNEL_META = 'personnel-snapshot.json'
PERSONNEL_DOWNLOAD = '/api/demo-sources/personnel-roster'


class HistoricalDemoError(ValueError):
    """The requested data directory is not a verified historical demo."""


def validate_demo_dir(data_dir):
    """Read both identity markers without modifying the candidate directory."""
    requested = Path(data_dir).expanduser()
    if requested.is_symlink():
        raise HistoricalDemoError('演示数据目录不能是符号链接。')
    root = requested.resolve()
    if (root == (BASE / 'data').resolve() or root.name == 'data'
            or not root.is_dir()):
        raise HistoricalDemoError('请选择已准备好的独立历史演示目录，不能使用正式 data。')
    marker_path, db_path = root / MARKER_NAME, root / 'cabinet-flow.sqlite3'
    if (marker_path.is_symlink() or db_path.is_symlink()
            or not marker_path.is_file() or not db_path.is_file()):
        raise HistoricalDemoError('缺少历史演示身份标记或数据库；不会打开现有业务资料。')
    if marker_path.stat().st_size > 64 * 1024:
        raise HistoricalDemoError('历史演示身份标记无效。')
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
        if (not isinstance(marker, dict) or marker.get('kind') != IDENTITY
                or type(marker.get('version')) is not int or marker['version'] != VERSION
                or not isinstance(marker.get('instance_id'), str)):
            raise ValueError('identity fields')
        uuid.UUID(marker['instance_id'])
        if not isinstance(marker.get('created_at'), str):
            raise ValueError('timestamp')
        datetime.fromisoformat(marker['created_at'].replace('Z', '+00:00'))
        project_ids = marker.get('project_ids')
        if not isinstance(project_ids, dict) or not project_ids or any(
                not isinstance(key, str) or not isinstance(value, str) or not value.startswith('prj_')
                for key, value in project_ids.items()):
            raise ValueError('project IDs')
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as con:
            row = con.execute('SELECT value FROM config WHERE key=?', (CONFIG_KEY,)).fetchone()
            production = con.execute("SELECT 1 FROM config WHERE key='factory_instance'").fetchone()
            projects = {value for (value,) in con.execute("SELECT id FROM entities WHERE kind='projects'")}
        saved = json.loads(row[0]) if row else None
        if production or saved != marker or not set(project_ids.values()) <= projects:
            raise ValueError('database identity')
    except (OSError, UnicodeError, ValueError, TypeError, sqlite3.Error) as exc:
        raise HistoricalDemoError('历史演示库身份校验失败；不会覆盖现有资料。') from exc
    return root, marker


def personnel_snapshot(root):
    """Return a verified private source snapshot without entering the people roster."""
    folder = Path(root) / 'sources'
    if not folder.exists():
        return None
    if folder.is_symlink() or not folder.is_dir():
        raise HistoricalDemoError('人员快照目录无效。')
    source, meta_path = folder / PERSONNEL_SOURCE, folder / PERSONNEL_META
    if not source.exists() and not meta_path.exists():
        return None
    if (source.is_symlink() or meta_path.is_symlink()
            or not source.is_file() or not meta_path.is_file()
            or meta_path.stat().st_size > 4096 or source.stat().st_size > 10 * 1024 * 1024):
        raise HistoricalDemoError('人员快照文件无效。')
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        raw = source.read_bytes()
        if (not isinstance(meta, dict) or meta.get('schema_version') != 1
                or meta.get('status') != 'pending_confirmation'
                or not isinstance(meta.get('count'), int) or meta['count'] < 1
                or not isinstance(meta.get('original_filename'), str)
                or not meta['original_filename'].lower().endswith('.xlsx')
                or Path(meta['original_filename']).name != meta['original_filename']
                or meta.get('bytes') != len(raw)
                or meta.get('sha256') != hashlib.sha256(raw).hexdigest()):
            raise ValueError('snapshot metadata')
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise HistoricalDemoError('人员快照完整性校验失败。') from exc
    return meta, raw


def personnel_snapshot_public(root):
    snapshot = personnel_snapshot(root)
    if snapshot is None:
        return None
    meta, _ = snapshot
    return {'count': meta['count'], 'status': 'pending_confirmation',
            'original_filename': meta['original_filename'],
            'download_url': PERSONNEL_DOWNLOAD,
            'note': '仅作历史人员名册快照；未加入派工人员。'}


def directory_id(root):
    return hashlib.sha256(str(root.resolve()).encode('utf-8')).hexdigest()[:20]


def same_demo(port, identity):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/demo-info', timeout=.5) as response:
            info = json.load(response)
        return info.get('mode') == 'historical_demo' and info.get('directory_id') == identity
    except (OSError, ValueError, TypeError):
        return False


def hardware_route(path):
    """Match all hardware mutations before parsing a request body or routing."""
    path = unquote(urlsplit(path).path)
    if path.startswith('/api/device') or path.startswith('/api/project-dispatches'):
        return True
    if re.fullmatch(r'/api/tasks/[^/]+/send-device', path):
        return True
    if re.fullmatch(r'/api/projects/[^/]+/dispatch', path):
        return True
    return False


def controller_mutation_route(path):
    """Keep the demo from provisioning instances or changing controller plans."""
    path = unquote(urlsplit(path).path)
    return path == '/api/control' or path.startswith('/api/control/') or \
        path == '/api/factory-instances' or path.startswith('/api/factory-instances/')


def historical_handler():
    from kanpace.http.server import Handler
    from kanpace.core.errors import APIError

    class HistoricalHandler(Handler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/demo-info':
                try:
                    self.validate_host()
                    return self.json_response(self.server.demo_info)
                except APIError as exc:
                    return self.error_response(exc)
            if path == PERSONNEL_DOWNLOAD:
                try:
                    self.validate_host()
                    if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
                        raise APIError(403, '请从本机演示页面下载资料')
                    snapshot = personnel_snapshot(self.server.demo_root)
                    if snapshot is None:
                        raise APIError(404, '没有人员名册快照')
                    return self.send_bytes(200, snapshot[1],
                                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                           {'Content-Disposition': 'attachment; filename="KANPACE-personnel-snapshot.xlsx"'})
                except HistoricalDemoError as exc:
                    return self.json_response({'error': str(exc)}, 409)
                except APIError as exc:
                    return self.error_response(exc)
            # This normally sends a USB RPC; the demo has no physical device.
            if urlsplit(self.path).path == '/api/device/image-status':
                return self.json_response({'error': '历史演示不连接实体胸牌'}, 403)
            return super().do_GET()

        def _mutate(self):
            if hardware_route(self.path):
                try:
                    self.validate_host()
                    return self.json_response({'error': '历史演示不连接或派发实体胸牌'}, 403)
                except APIError as exc:
                    return self.error_response(exc)
            if controller_mutation_route(self.path):
                try:
                    self.validate_host()
                    return self.json_response({'error': '历史演示不能开通工厂或修改配置中台'}, 403)
                except APIError as exc:
                    return self.error_response(exc)
            if self.command == 'POST':
                return super().do_POST()
            return self.json_response({'error': '此操作不支持'}, 405)

        def do_POST(self):
            return self._mutate()

        def do_PUT(self):
            return self._mutate()

        def do_PATCH(self):
            return self._mutate()

        def do_DELETE(self):
            return self._mutate()

        def send_bytes(self, status, body, content_type='application/json; charset=utf-8', headers=None):
            if status == 200 and content_type.startswith('text/html'):
                script = '<script src="/historical-demo/ui.js" defer></script>'
                html = body.decode('utf-8')
                if script not in html:
                    html = html.replace('</body>', script + '</body>') if '</body>' in html else html + script
                body = html.encode('utf-8')
            return super().send_bytes(status, body, content_type, headers)

    return HistoricalHandler


def historical_server(address, store):
    """Construct a KANPACE server without starting its badge dispatch worker."""
    from device_bridge import DeviceBridge, DeviceError
    from kanpace.application.project_dispatch import ProjectDispatchCoordinator
    from kanpace.http.server import Server

    class DisabledDeviceBridge(DeviceBridge):
        def _load_driver(self):
            # Do not initialize a serial driver or discover physical USB ports.
            return None

        def ports(self):
            return []

        def _disabled(self, *args, **kwargs):
            raise DeviceError(403, '历史演示不连接实体胸牌')

        connect = _disabled
        send_task = _disabled
        wifi_config = _disabled
        wifi_scan = _disabled
        _usb_rpc = _disabled
        _http_frame = _disabled
        _write = _disabled

    class HistoricalServer(Server):
        def __init__(self):
            self.store = store
            self.static_dir = (BASE / 'static').resolve()
            ThreadingHTTPServer.__init__(self, address, historical_handler())
            self.device_bridge = DisabledDeviceBridge(store, execution_handler=store.handle_device_execution)
            self.project_dispatch = ProjectDispatchCoordinator(store, self.device_bridge, background=False)

    return HistoricalServer()


def main(argv=None):
    parser = argparse.ArgumentParser(description='KANPACE 历史订单本机演示')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8777)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error('请使用 Python 3.10 或更新版本')
    if not 1024 <= args.port <= 65535:
        parser.error('端口须为 1024 至 65535')
    try:
        root, marker = validate_demo_dir(args.data_dir)
        identity = directory_id(root)
        url = f'http://127.0.0.1:{args.port}/factory/index.html#page=projects'
        if same_demo(args.port, identity):
            print('这份历史演示已经启动：' + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        from kanpace.application.store import Store
        store = Store(root, seed=False, empty=True)
        validate_demo_dir(root)
        server = historical_server(('127.0.0.1', args.port), store)
        server.demo_root = root
        server.demo_info = {**marker, 'mode': 'historical_demo', 'directory_id': identity,
                            'data_dir': str(root), 'hardware_enabled': False,
                            'personnel_snapshot': personnel_snapshot_public(root)}
        print('KANPACE 历史订单演示：http://127.0.0.1:' + str(args.port), flush=True)
        print('工厂端：' + url, flush=True)
        print('数据仅保存在：' + str(root), flush=True)
        print('实体胸牌连接及派工已禁用。按 Ctrl+C 停止。', flush=True)
        if not args.no_browser:
            threading.Timer(.4, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\n演示已停止，资料保留。')
        finally:
            server.server_close()
        return 0
    except (HistoricalDemoError, OSError, RuntimeError, ValueError) as exc:
        print('历史演示未启动：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
