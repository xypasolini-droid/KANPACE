#!/usr/bin/env python3
"""Install or check the five isolated KANPACE engines without opening a Store."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('engineering', 'optimization', 'agent')
ENGINE_NAMES = {
    'engineering': {'paddleocr': 'PaddleOCR', 'occt': 'Open CASCADE / cadquery-ocp'},
    'optimization': {'ortools': 'Google OR-Tools CP-SAT',
                     'packingsolver': 'PackingSolver rectangle-guillotine'},
    'agent': {'langgraph': 'LangGraph'},
}


def selected_groups(only):
    return GROUPS if only == 'all' else (only,)


def resolve_python(value=None, engineering=False):
    """Turn 3.11/3.12 into an executable usable by all three installers."""
    if value:
        requested = 'python' + value if value in ('3.11', '3.12') else value
        executable = shutil.which(requested)
        if not executable and Path(requested).expanduser().is_file():
            executable = str(Path(requested).expanduser().absolute())
    else:
        executable = shutil.which('python3.12') or (None if engineering else shutil.which('python3.11')) or sys.executable
    if not executable:
        raise ValueError('未找到 Python，请安装 Python 3.11 / 3.12，或向 --python 提供解释器完整路径。')
    probe = subprocess.run([executable, '-c',
                            'import json,sys; print(json.dumps(list(sys.version_info[:2])))'],
                           check=True, capture_output=True, text=True, timeout=10)
    version = json.loads(probe.stdout)
    if version not in ([3, 11], [3, 12]):
        raise ValueError('五项引擎安装入口要求 Python 3.11 或 3.12；当前为 ' + '.'.join(map(str, version)))
    if engineering and version != [3, 12]:
        raise ValueError('本次工程引擎依赖锁需要 Python 3.12；请使用 --python 3.12 或对应解释器完整路径。')
    return executable


def installer_command(group, executable):
    if group == 'engineering':
        return [executable, str(ROOT / 'tools/setup_engineering.py'), '--python', executable]
    if group == 'optimization':
        return [executable, str(ROOT / 'setup_optimization.py'), '--python', executable]
    # This installer has no --python option: its launching interpreter creates venv.
    if group == 'agent':
        return [executable, str(ROOT / 'tools/setup_agent.py')]
    raise ValueError('Unknown installer group: ' + group)


def probe_group(group):
    """Use installed workers and synthetic input only; never import app or Store."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if group == 'engineering':
        from engineering_engines import EngineeringJobs
        with tempfile.TemporaryDirectory(prefix='kanpace-engine-check-') as directory:
            status = EngineeringJobs(directory).status()
        versions = status.get('versions', {})
        return {
            'paddleocr': {'name': ENGINE_NAMES[group]['paddleocr'],
                          'available': bool(status.get('ocr', {}).get('ready')),
                          'version': versions.get('paddleocr'),
                          'models_ready': bool(status.get('ocr', {}).get('models_ready')),
                          'probe': 'installed imports and local model files'},
            'occt': {'name': ENGINE_NAMES[group]['occt'],
                     'available': bool(status.get('cad', {}).get('ready')),
                     'version': versions.get('cadquery-ocp'),
                     'probe': 'installed native import'},
        }
    if group == 'optimization':
        import optimization_engines
        status = optimization_engines.status()
        packing = dict(status['packingsolver'])
        if packing.get('available'):
            # File presence is not sufficient: load and solve with the actual CLI.
            try:
                result = optimization_engines.packing_preview({
                    'dimensions_confirmed': True, 'material': 'synthetic-health-check',
                    'thickness_mm': 18, 'grain': 'none', 'kerf_mm': 3, 'trim_mm': 5,
                    'stock': {'width_mm': 400, 'height_mm': 300, 'quantity': 1},
                    'items': [{'id': 'probe', 'width_mm': 100, 'height_mm': 100,
                               'quantity': 1, 'allow_rotate': False}],
                    'time_limit_seconds': 1,
                })
                packing['available'] = bool(result['validation']['valid'])
                packing['probe_status'] = result['engine']['status']
                packing['checked_pieces'] = result['validation']['checked_pieces']
            except Exception as error:
                packing.update(available=False, reason=str(error))
        return {'ortools': status['ortools'], 'packingsolver': packing}
    if group == 'agent':
        import langgraph_agent
        return {'langgraph': langgraph_agent.status()}
    raise ValueError('Unknown probe group: ' + group)


def check(groups):
    engines = {}
    for group in groups:
        print('Checking ' + group + ' installed engines...', file=sys.stderr, flush=True)
        try:
            result = probe_group(group)
        except Exception as error:
            result = {key: {'name': name, 'available': False, 'reason': str(error)}
                      for key, name in ENGINE_NAMES[group].items()}
        for key, value in result.items():
            engines[key] = dict(value, group=group)
    available = bool(engines) and all(item.get('available') is True for item in engines.values())
    print(json.dumps({'schema': 1, 'operation': 'check', 'groups': list(groups),
                      'all_available': available, 'engines': engines},
                     ensure_ascii=False, indent=2))
    return 0 if available else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Only probe installed engines; no installation or business database access')
    parser.add_argument('--only', choices=(*GROUPS, 'all'), default='all')
    parser.add_argument('--python', help='Python 3.12 for engineering/all, Python 3.11/3.12 for other groups (installation only)')
    args = parser.parse_args(argv)
    groups = selected_groups(args.only)
    if args.check:
        return check(groups)
    try:
        executable = resolve_python(args.python, engineering='engineering' in groups)
        for group in groups:
            command = installer_command(group, executable)
            print('Installing ' + group + ': ' + shlex.join(command), flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Installation failed: ' + str(error), file=sys.stderr)
        return 1
    print('Installation commands completed. Checking the selected engines...', flush=True)
    return check(groups)


if __name__ == '__main__':
    raise SystemExit(main())
