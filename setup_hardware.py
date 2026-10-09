#!/usr/bin/env python3
"""Install the optional USB driver library into a project-local virtual environment."""
from pathlib import Path
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent

def main():
    if sys.version_info < (3, 10):
        print('需要 Python 3.10 或以上。')
        return 1
    target = BASE / '.venv'
    print('正在准备本地 USB 环境；只需首次安装，业务数据保持不变。')
    venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(BASE / 'requirements-hardware.txt')], check=True)
    print('USB 依赖安装完成。请先停止服务，再用“启动KANPACE”打开工作台。Mac 可双击“停止KANPACE.command”。')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
