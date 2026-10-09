#!/usr/bin/env python3
"""Install KANPACE's private engineering environment and official public models.

This is the only engineering command that needs Internet access. It never reads
customer files and never starts a web service or changes production records.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'PP-OCRv5_mobile_det': '0d63e78e2b680928f6b1747d76a08db6e645efb7',
    'PP-OCRv5_mobile_rec': '682f20538d8c086cb2128e5cfac775e6c4904e85',
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def download_models():
    # Anonymous HTTPS only: never read a saved Hugging Face token or login.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').is_file() else None)
    directory = ROOT / 'models/engineering'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 1, 'models': [], 'customer_data_used': False}
    for name in MODELS:
        repo = 'PaddlePaddle/' + name
        with urllib.request.urlopen('https://huggingface.co/api/models/' + repo + '/revision/' + MODELS[name] + '?blobs=true',
                                    context=context, timeout=60) as response:
            info = json.load(response)
        if info['sha'] != MODELS[name]:
            raise RuntimeError('Unexpected public model revision: ' + repo)
        license_name = (info.get('cardData') or {}).get('license')
        if license_name != 'apache-2.0':
            raise RuntimeError('模型许可与审核记录不符：' + repo + ': ' + str(license_name))
        target = directory / name
        target.mkdir(exist_ok=True)
        print('Downloading official public model', repo, info['sha'], flush=True)
        wanted = [entry for entry in info['siblings'] if entry['rfilename'].startswith('inference.')
                  or entry['rfilename'] == 'README.md' or entry['rfilename'].startswith('LICENSE')]
        def download(entry):
            filename = entry['rfilename']
            if '/' in filename or '\\' in filename:
                raise RuntimeError('Unexpected nested model asset')
            expected = (entry.get('lfs') or {}).get('sha256')
            destination = target / filename
            if expected and destination.is_file() and digest(destination) == expected:
                return
            url = 'https://huggingface.co/' + repo + '/resolve/' + info['sha'] + '/' + filename
            temporary = destination.with_name(destination.name + '.part')
            with urllib.request.urlopen(url, context=context, timeout=120) as response, temporary.open('wb') as out:
                shutil.copyfileobj(response, out, 1024 * 1024)
            if expected and digest(temporary) != expected:
                temporary.unlink()
                raise RuntimeError('Official model checksum mismatch: ' + filename)
            temporary.replace(destination)
            print('Verified download:', name, filename, flush=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(download, wanted))
        files = {str(p.relative_to(target)): digest(p) for p in target.iterdir() if p.is_file()}
        if not {'inference.json', 'inference.pdiparams', 'inference.yml'} <= set(files):
            raise RuntimeError('模型文件不完整：' + repo)
        manifest['models'].append({'name': name, 'repo': repo, 'revision': info['sha'],
                                   'license': license_name, 'files_sha256': files,
                                   'source_url': 'https://huggingface.co/' + repo})
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Public model downloads complete. Subsequent document jobs are offline.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', help='Installed Python 3.12 interpreter for the isolated environment')
    parser.add_argument('--models-only', action='store_true')
    parser.add_argument('--models-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--skip-models', action='store_true')
    args = parser.parse_args()
    if args.models_worker:
        download_models()
        return
    runtime = ROOT / '.venv-engineering/bin/python'
    uv = shutil.which('uv')
    if not args.models_only:
        if not uv:
            raise SystemExit('Install uv first, or manually create .venv-engineering and install requirements-engineering.txt')
        if not runtime.exists():
            python = args.python or shutil.which('python3.12')
            if not python and sys.version_info[:2] == (3, 12):
                python = sys.executable
            if not python:
                raise SystemExit('本次工程依赖锁要求 Python 3.12，请用 --python 提供已安装解释器的完整路径')
            version = subprocess.run([python, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'],
                                     check=True, capture_output=True, text=True, timeout=10).stdout.strip()
            if version != '3.12':
                raise SystemExit('工程依赖锁在 Python 3.12 验证；当前解释器为 ' + version + '，请改用 Python 3.12')
            subprocess.run([uv, 'venv', '--python', python, str(runtime.parent.parent)], check=True)
        version = subprocess.run([str(runtime), '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'],
                                 check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if version != '3.12':
            raise SystemExit('现有 .venv-engineering 为 Python ' + version + '；请另备份并用 Python 3.12 创建专属环境')
        lock = ROOT / 'requirements-engineering.lock.txt'
        requirements = lock if lock.exists() else ROOT / 'requirements-engineering.txt'
        install_env = os.environ.copy()
        install_env.setdefault('UV_HTTP_TIMEOUT', '600')
        install_env.setdefault('UV_CONCURRENT_DOWNLOADS', '2')
        subprocess.run([uv, 'pip', 'install', '--python', str(runtime), '-r', str(requirements)], check=True, env=install_env)
    if not args.skip_models:
        subprocess.run([str(runtime), str(Path(__file__).resolve()), '--models-worker'], check=True)


if __name__ == '__main__':
    main()
