#!/usr/bin/env python3
"""Start the local server and open its browser. No dependencies or cloud calls."""
from pathlib import Path
import subprocess
import sys
import time
import webbrowser
import local_service

BASE = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'

def ready():
    return local_service.ready(URL)

def main():
    if sys.version_info < (3, 10):
        print('请安装 Python 3.10 或更新版本后启动。')
        return 1
    if ready():
        webbrowser.open(URL)
        print('KANPACE已经运行，已打开工作台：' + URL)
        return 0
    if sys.platform == 'darwin':
        try:
            local_service.ensure_started()
            for _ in range(100):
                if ready():
                    webbrowser.open(URL)
                    print('工作台已打开，服务在后台运行。可以关闭本窗口。')
                    print('如需停止，请双击“停止KANPACE.command”；数据会保留。')
                    return 0
                time.sleep(0.1)
            print('服务暂未就绪，请查看 data/logs/server-error.log。')
            return 1
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print('启动失败：' + str(exc))
            return 1
    hardware_python = BASE / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    python = str(hardware_python) if hardware_python.exists() else sys.executable
    child = subprocess.Popen([python, str(BASE / 'app.py')], cwd=BASE)
    try:
        for _ in range(80):
            if child.poll() is not None:
                print('本地服务未能启动，请查看上方错误；8765 端口可能已被占用。')
                return 1
            if ready():
                webbrowser.open(URL)
                print('工作台已打开。请保留此窗口；关闭服务可按 Ctrl+C。')
                return child.wait()
            time.sleep(0.1)
        print('服务启动超时，请检查终端日志。')
        return 1
    except KeyboardInterrupt:
        print('\n正在关闭KANPACE；已保存的数据保留在 data 文件夹。')
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()

if __name__ == '__main__':
    raise SystemExit(main())
