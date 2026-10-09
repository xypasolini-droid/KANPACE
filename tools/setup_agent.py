"""Install the isolated LangGraph environment: python3 tools/setup_agent.py."""
from pathlib import Path
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 10):
    raise SystemExit('LangGraph runtime requires Python 3.10 or later.')
folder = ROOT / '.venv-agent'
if folder.is_symlink():
    raise SystemExit('Refusing a linked environment directory.')
if not folder.exists():
    venv.EnvBuilder(with_pip=True).create(folder)
python = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-agent.lock.txt')], check=True)
subprocess.run([str(python), str(ROOT / 'tools/archive_agent_runtime.py')], check=True)
print('LangGraph installed. Business data and device firmware were not changed.')
