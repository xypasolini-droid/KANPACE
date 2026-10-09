#!/usr/bin/env python3
"""Install/check CPU workers without opening manufacturing data or downloading models."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PINS = {'ortools': '9.15.6755', 'pypdfium2': '4.30.0', 'Pillow': '12.3.0',
        'langgraph': '1.2.11', 'langgraph-checkpoint-sqlite': '3.1.1'}
COMPONENTS = {'optimization': ('ortools', 'pypdfium2', 'Pillow'),
              'agent': ('langgraph', 'langgraph-checkpoint-sqlite')}


def executable(component):
    name = '.venv-optimization' if component == 'optimization' else '.venv-agent'
    return ROOT / name / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_input_pins():
    entries = [line.strip() for line in (ROOT / 'requirements-web.in').read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    expected = [f'{name}=={version}' for name, version in PINS.items()]
    if sorted(entries) != sorted(expected):
        raise RuntimeError('requirements-web.in differs from this verified installer baseline; review pins and probes together')


def run(command, **kwargs):
    result = subprocess.run([str(value) for value in command], text=True,
                            capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-6000:] or f'Exit {result.returncode}')
    return result


def inventory(component, archive=False):
    packages = []
    out = ROOT / 'docs/upgrade/runtime-licenses' / component
    if archive:
        out.mkdir(parents=True, exist_ok=True)
    for dist in sorted(importlib.metadata.distributions(), key=lambda value: value.metadata['Name'].lower()):
        files = []
        # REUSE/SPDX wheels may call license texts Apache-2.0.txt or BSD-3-Clause.txt;
        # PDFium additionally declares LicenseRef-PdfiumThirdParty.txt and dep5-wheel.
        declared = {Path(value).name for value in dist.metadata.get_all('License-File', [])}
        for item in dist.files or []:
            if (Path(item).name not in declared and
                    not re.search(r'(?:^|/)(?:LICEN[CS]E(?:Ref)?|NOTICE|COPYING|COPYRIGHT)(?:[._-]|$)', str(item), re.I)):
                continue
            source = Path(dist.locate_file(item))
            if not source.is_file():
                continue
            data = source.read_bytes()
            target = re.sub(r'[^a-zA-Z0-9_.-]+', '_', dist.metadata['Name'] + '__' + str(item))
            if archive:
                (out / target).write_bytes(data)
            files.append({'file': target, 'sha256': hashlib.sha256(data).hexdigest()})
        packages.append({'name': dist.metadata['Name'], 'version': dist.version,
                         'license_expression': dist.metadata.get('License-Expression'),
                         'license_metadata': dist.metadata.get('License'), 'license_files': files})
    result = {'python': platform.python_version(), 'platform': platform.platform(), 'packages': packages}
    if archive:
        (out / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def minimal_pdf():
    stream = b'BT /F1 12 Tf 20 80 Td (KANPACE runtime probe) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    pdf = b'%PDF-1.4\n'
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return pdf + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def optimization_probe():
    import pypdfium2 as pdfium
    from PIL import Image
    import optimization_engines
    jobs = [dict(id=key, duration=duration, release=0, due=480, windows=[[0, 480]],
                 resources=resources, dependencies=deps, wait_minutes=0)
            for key, duration, resources, deps in
            [('a', 90, ['person_a', 'machine'], []),
             ('b', 120, ['person_b', 'machine'], []),
             ('join', 45, ['person_a'], ['a', 'b'])]]
    jobs[0]['wait_minutes'] = 10
    payload = {'operation': 'schedule', 'jobs': jobs, 'horizon_minutes': 480, 'time_limit_seconds': 3}
    solved = json.loads(run([sys.executable, ROOT / 'optimization_worker.py'],
                            input=json.dumps(payload), timeout=180).stdout)
    certificate = optimization_engines.validate_schedule(payload, solved)
    if (solved.get('engine') != 'Google OR-Tools CP-SAT' or solved.get('version') != PINS['ortools']
            or solved.get('status') not in ('OPTIMAL', 'FEASIBLE')
            or len(solved.get('rows', [])) != 3 or not certificate['valid']):
        raise RuntimeError('Real CP-SAT schedule/certificate failed: ' + json.dumps(solved))
    doc = pdfium.PdfDocument(minimal_pdf())
    try:
        page = doc[0]
        textpage = page.get_textpage()
        try:
            text = textpage.get_text_range()
            box = textpage.get_charbox(0)
            if 'KANPACE runtime probe' not in text or len(box) != 4:
                raise RuntimeError('PDFium text/character position extraction failed')
            bitmap = page.render(scale=1)
            try:
                rendered = bitmap.to_pil()
                try:
                    if rendered.size != (200, 100):
                        raise RuntimeError('PDFium/Pillow page preview failed')
                finally:
                    rendered.close()
            finally:
                bitmap.close()
        finally:
            textpage.close()
            page.close()
    finally:
        doc.close()
    image = Image.new('RGB', (12, 8), (20, 40, 60))
    try:
        for kind in ('PNG', 'JPEG'):
            buffer = io.BytesIO()
            image.save(buffer, format=kind)
            buffer.seek(0)
            with Image.open(buffer) as reopened:
                reopened.load()
                if reopened.size != image.size:
                    raise RuntimeError('Pillow image encode/decode failed: ' + kind)
    finally:
        image.close()
    return {'cp_sat': {'status': solved['status'], 'tasks': len(solved['rows']),
                       'independent_validation': certificate, 'wall_time_seconds': solved.get('wall_time_seconds')},
            'pdfium': {'native_text': True, 'character_boxes': True, 'page_preview': True},
            'pillow': {'png_roundtrip': True, 'jpeg_roundtrip': True}, 'production_data_opened': False}


def agent_probe():
    import langgraph_agent
    import sqlite3
    os.environ['KANPACE_AGENT_LOCAL_MODEL_ENABLE'] = '0'
    facts = {'today': '2026-10-04', 'can_plan': True,
             'projects': [{'id': 'probe_project', 'name': 'Disposable probe', 'closed': False, 'due_date': '2026-10-01'}],
             'tasks': [{'id': 'probe_task', 'project_id': 'probe_project', 'title': 'Probe task',
                        'status': 'blocked', 'pause_label': 'Synthetic hold', 'dependencies': [],
                        'assignee': None, 'minutes_known': False}], 'materials': []}
    request = {'id': 'wf_' + 'a' * 32, 'binding': 'disposable-runtime-probe',
               'fingerprint': langgraph_agent.digest(facts), 'facts': facts}
    with tempfile.TemporaryDirectory(prefix='kanpace-runtime-check-') as directory:
        first = langgraph_agent.run(directory, request)
        if first.get('status') != 'review' or len(first.get('steps', [])) != 2:
            raise RuntimeError('LangGraph did not persist its review interrupt')
        second = langgraph_agent.run(directory, dict(request, resume=True, decision='compare', simulations=[]))
        if second.get('status') != 'proposed' or len(second.get('steps', [])) != 4:
            raise RuntimeError('New LangGraph process did not resume persisted review')
        checkpoint = Path(directory) / 'agent-workflows/checkpoints.sqlite'
        with sqlite3.connect(checkpoint) as con:
            count = con.execute('SELECT count(*) FROM checkpoints').fetchone()[0]
        third = langgraph_agent.run(directory, dict(request, resume=True, decision='compare', simulations=[]))
        with sqlite3.connect(checkpoint) as con:
            repeated = con.execute('SELECT count(*) FROM checkpoints').fetchone()[0]
        if second != third or count != repeated:
            raise RuntimeError('Repeated resume was not idempotent')
    return {'langgraph': {'first_status': first['status'], 'resumed_status': second['status'],
                         'nodes': [step['id'] for step in second['steps']],
                         'checkpoints': count, 'cross_process_resume': True, 'idempotent_resume': True},
            'production_data_opened': False, 'model_request_sent': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install pinned wheels from official PyPI, then check')
    parser.add_argument('--check', action='store_true', help='Check existing runtimes without installing')
    parser.add_argument('--python', default=sys.executable, help='Python 3.12 or 3.13 used to create isolated environments')
    parser.add_argument('--component', choices=['all', *COMPONENTS], default='all')
    parser.add_argument('--locked', action='store_true', help='Install the archived resolved component versions instead of re-resolving dependencies')
    parser.add_argument('--report', type=Path, default=ROOT / 'work/web-runtime-check.json')
    parser.add_argument('--probe', choices=list(COMPONENTS), help=argparse.SUPPRESS)
    parser.add_argument('--archive', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    check_input_pins()
    if args.probe:
        versions = {name: importlib.metadata.version(name) for name in COMPONENTS[args.probe]}
        if any(versions[name] != PINS[name] for name in versions):
            raise RuntimeError('Installed top-level versions differ from requirements-web.in')
        result = optimization_probe() if args.probe == 'optimization' else agent_probe()
        print(json.dumps({'available': True, 'versions': versions, 'checks': result,
                          'inventory': inventory(args.probe, args.archive)}, ensure_ascii=False))
        return 0
    if not (args.install or args.check):
        parser.error('Choose --install or --check')
    report = {'schema': 'kanpace-web-runtime-check-v1', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'source': 'https://pypi.org/simple', 'platform': platform.platform(), 'components': {},
              'production_data_opened': False, 'models_downloaded': False, 'packing_built': False}
    components = list(COMPONENTS) if args.component == 'all' else [args.component]
    for component in components:
        python = executable(component)
        try:
            if python.parent.parent.is_symlink():
                raise RuntimeError('Refusing a linked environment directory')
            if args.install:
                version = json.loads(run([args.python, '-c', 'import sys,json;print(json.dumps(list(sys.version_info[:2])))'], timeout=15).stdout)
                if tuple(version) not in ((3, 12), (3, 13)):
                    raise RuntimeError('Use Python 3.12 or 3.13 for this CPU baseline; versions other than those are unverified')
                if not python.is_file():
                    run([args.python, '-m', 'venv', python.parent.parent], timeout=120)
                out = ROOT / 'work/web-runtime-install'
                out.mkdir(parents=True, exist_ok=True)
                requirements = out / f'{component}.txt'
                requirements.write_text(''.join(f'{name}=={PINS[name]}\n' for name in COMPONENTS[component]))
                if args.locked:
                    requirements = ROOT / 'docs/upgrade/runtime-locks' / f'{component}.txt'
                    if not requirements.is_file():
                        raise RuntimeError(f'No resolved lock for {component}; install/verify baseline first')
                install_tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                pip_report = out / f'{component}-{install_tag}-pip.json'
                print(f'Installing {component} wheels from official PyPI...', flush=True)
                run([python, '-m', 'pip', '--isolated', 'install', '--index-url', 'https://pypi.org/simple',
                     '--only-binary=:all:', '--retries', '1', '--timeout', '30', '--report', pip_report,
                     '-r', requirements], timeout=600)
            if not python.is_file():
                raise RuntimeError(f'{python} does not exist; run --install with Python 3.12')
            run([python, '-m', 'pip', 'check'], timeout=30)
            command = [python, Path(__file__).resolve(), '--probe', component]
            if args.install:
                command.append('--archive')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
            result = json.loads(run(command, timeout=300, env=env).stdout)
            report['components'][component] = result
            if args.install:
                locked = ROOT / 'docs/upgrade/runtime-locks'
                locked.mkdir(parents=True, exist_ok=True)
                freeze = run([python, '-m', 'pip', 'freeze'], timeout=30).stdout
                (locked / f'{component}.txt').write_text(freeze)
                (locked / pip_report.name).write_text(pip_report.read_text())
            print(f'{component}: real CPU checks passed', flush=True)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            report['components'][component] = {'available': False, 'reason': str(error)}
            print(f'{component}: unavailable: {error}', file=sys.stderr, flush=True)
    report['available'] = all(row.get('available') is True for row in report['components'].values())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Report: {args.report}', flush=True)
    return 0 if report['available'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
