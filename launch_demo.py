#!/usr/bin/env python3
"""Start the separately packaged synthetic demo; never reuse a production server.

Only Python's standard library is required. The normal launch.py and its
launchd registration are intentionally not involved. Keep this terminal open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent

# Applied only to the independent demo's HTTP responses. Production static
# files keep their original defaults, including exclusion of demo records.
DEMO_SCRIPTS = {
    '/operations.js': [('operationsShowDemo=false', 'operationsShowDemo=true')],
    '/planning.js': [('planningShowDemo=false', 'planningShowDemo=true')],
    '/schedule-reference.js': [("referenceMode='departments'", "referenceMode='execution'")],
    '/operations-scheduling.js': [("include_demo:'0'", "include_demo:'1'")],
    '/factory-home.js': [
        ("include_demo:'0'", "include_demo:'1'"),
        ('&& !row.project.demo', '&& true'),
        ('const demos = summaries.filter(row => (!row.closed || row.deliveryPending) && row.project.demo);', 'const demos = [];'),
    ],
}


def validate_client_sources(static_dir):
    for name, replacements in DEMO_SCRIPTS.items():
        content = (static_dir / name.lstrip('/')).read_text(encoding='utf-8')
        for before, after in replacements:
            if before not in content:
                raise RuntimeError('演示界面版本不匹配，请使用完整演示包：' + name)


def directory_id(data_dir):
    return hashlib.sha256(str(data_dir.resolve()).encode('utf-8')).hexdigest()[:20]


def same_demo(port, identity):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/demo-info', timeout=.4) as response:
            value = json.load(response)
        return isinstance(value, dict) and value.get('mode') == 'standalone_demo' and value.get('directory_id') == identity
    except (OSError, ValueError):
        return False


def choose_port(first, identity):
    for port in range(first, min(first + 20, 65536)):
        if same_demo(port, identity):
            return port, True
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port, False
    raise RuntimeError('演示端口均被占用，请用 --port 指定其他端口。不会连接已有正式系统。')


def demo_handler():
    from kanpace.http.server import Handler
    from kanpace.core.errors import APIError

    class DemoHandler(Handler):
        def do_GET(self):
            if urlsplit(self.path).path == '/api/demo-info':
                try:
                    self.validate_host()
                    return self.json_response(self.server.demo_info)
                except APIError as error:
                    return self.error_response(error)
            return super().do_GET()

        def send_bytes(self, status, body, content_type='application/json; charset=utf-8', headers=None):
            path = urlsplit(self.path).path
            if status == 200 and path in DEMO_SCRIPTS:
                text = body.decode('utf-8')
                for before, after in DEMO_SCRIPTS[path]:
                    text = text.replace(before, after)
                body = text.encode('utf-8')
            if status == 200 and content_type.startswith('text/html'):
                text = body.decode('utf-8')
                # Reviewed legacy documentation links must stay on this demo.
                text = text.replace('http://127.0.0.1:8765/', '/')
                if '/demo/ui.js' not in text:
                    text = text.replace('</body>', '<script src="/demo/ui.js" defer></script></body>')
                body = text.encode('utf-8')
            return super().send_bytes(status, body, content_type, headers)

    return DemoHandler


def main():
    if sys.version_info < (3, 10):
        print('请先安装 Python 3.10 或更新版本，再双击启动。', file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description='KANPACE 独立演示：合成资料、本机运行')
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--data-dir', type=Path, default=BASE / 'data-demo')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('请选择 1024 至 65535 的本机端口')
    data_dir = args.data_dir.resolve()
    if data_dir == (BASE / 'data').resolve():
        parser.error('演示不得使用正式 data 目录')
    try:
        identity = directory_id(data_dir)
        port, running = choose_port(args.port, identity)
        url = f'http://127.0.0.1:{port}/demo/index.html'
        if running:
            print('这一份演示已经启动：' + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        validate_client_sources(BASE / 'static')
        from tools.demo_fixture import prepare_demo
        from kanpace.application.store import Store
        from kanpace.http.server import Server
        info = prepare_demo(data_dir)
        store = Store(data_dir, seed=False, empty=True)
        # Server-owned switch, set only after the fixture validates both demo
        # markers. The packaged read-only scope adapters honor this switch.
        store.standalone_demo = True
        server = Server(('127.0.0.1', port), store)
        server.RequestHandlerClass = demo_handler()
        server.demo_info = {**info, 'mode': 'standalone_demo', 'directory_id': identity}
        print('\nKANPACE 独立演示已启动：' + url, flush=True)
        print('工厂端：' + f'http://127.0.0.1:{port}/factory/index.html#page=projects', flush=True)
        print('配置中台：' + f'http://127.0.0.1:{port}/control/index.html', flush=True)
        print('请保留这个窗口。体验操作会保存，按 Ctrl+C 停止演示。\n', flush=True)
        if not args.no_browser:
            threading.Timer(.4, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\n演示已停止，体验记录已保留。')
        finally:
            server.server_close()
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print('演示未启动：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
