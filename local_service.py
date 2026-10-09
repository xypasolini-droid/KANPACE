#!/usr/bin/env python3
"""Run the Mac local Web server under the current login session's launchd.

The plist lives inside app data, not Library/LaunchAgents: no login item or
system-wide service is installed. Closing a terminal or agent turn does not
stop the server. Explicit bootout stops it without KeepAlive restarting it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'


def ready(url=URL):
    try:
        with urllib.request.urlopen(url + '/api/health', timeout=0.5) as response:
            data = json.load(response)
            return isinstance(data, dict) and data.get('ok') is True and data.get('mode') == 'local_single_workstation'
    except (OSError, ValueError):
        return False


def wait_until_ready(timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        if ready():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def label(base=BASE):
    identity = hashlib.sha256(str(Path(base).resolve()).encode()).hexdigest()[:12]
    return 'com.xiongyi.cabinet-flow.' + identity


def target(base=BASE):
    return f'gui/{os.getuid()}/{label(base)}'


def definition(base=BASE):
    base = Path(base).resolve()
    python = base / '.venv/bin/python'
    if not python.is_file():
        python = Path(sys.executable).resolve()
    logs = base / 'data/logs'
    return {
        'Label': label(base),
        'ProgramArguments': [str(python), '-u', str(base / 'app.py'),
                             '--port', '8765', '--data-dir', str(base / 'data')],
        'WorkingDirectory': str(base),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 5,
        'StandardOutPath': str(logs / 'server.log'),
        'StandardErrorPath': str(logs / 'server-error.log'),
    }


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, timeout=15)


def ensure_started(base=BASE):
    if sys.platform != 'darwin':
        raise RuntimeError('此后台启动方式仅用于 macOS。')
    base = Path(base).resolve()
    job = target(base)
    existing = launchctl('print', job)
    if existing.returncode == 0:
        # Without -k, kickstart does not interrupt an already running process.
        started = launchctl('kickstart', job)
        if started.returncode:
            # launchd can finish a preceding bootout between print and kickstart.
            # In that case recreate the job; preserve other errors verbatim.
            if 'Could not find service' not in started.stderr:
                raise RuntimeError('本地服务未能启动：' + started.stderr.strip())
        else:
            return job
    service_dir = base / 'data/service'
    service_dir.mkdir(parents=True, exist_ok=True)
    (base / 'data/logs').mkdir(parents=True, exist_ok=True)
    path = service_dir / (label(base) + '.plist')
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=service_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(plistlib.dumps(definition(base)))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    started = launchctl('bootstrap', f'gui/{os.getuid()}', str(path))
    if started.returncode:
        # Concurrent double-clicks may have loaded the same job already.
        if launchctl('print', job).returncode:
            raise RuntimeError('无法启动本地服务：' + started.stderr.strip())
    return job


def stop(base=BASE):
    if sys.platform != 'darwin':
        raise RuntimeError('此停止方式仅用于 macOS。')
    job = target(base)
    if launchctl('print', job).returncode:
        return False
    result = launchctl('bootout', job)
    if result.returncode:
        raise RuntimeError('本地服务未能停止：' + result.stderr.strip())
    return True


def main():
    parser = argparse.ArgumentParser(description='KANPACE macOS 本地服务')
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    try:
        if sys.platform != 'darwin':
            raise RuntimeError('此后台服务管理方式仅用于 macOS。')
        if args.action == 'start':
            ensure_started()
            if not wait_until_ready():
                raise RuntimeError('后台服务已加载，但 Web 暂未就绪。请查看 data/logs/server-error.log。')
            print('KANPACE本地服务已启动：' + URL)
        elif args.action == 'stop':
            print('KANPACE本地服务已停止，数据已保留。' if stop() else 'KANPACE本地服务未运行。')
        else:
            result = launchctl('print', target())
            if result.returncode:
                print('KANPACE本地服务未运行。')
                return 1
            if not ready():
                print('后台服务已加载，但 Web 暂未就绪。请查看 data/logs/server-error.log。')
                return 1
            print('KANPACE本地服务正在运行：' + URL)
            return 0
        return 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
