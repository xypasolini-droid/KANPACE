#!/usr/bin/env python3
"""Install optional image decoding into the same local environment as USB support."""
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
    print('正在准备本地效果图组件；只需首次安装。')
    venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(BASE / 'requirements-media.txt')], check=True)
    print('效果图组件安装完成。请先停止服务，再用“启动KANPACE”打开工作台。Mac 可双击“停止KANPACE.command”。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
