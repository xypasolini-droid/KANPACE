#!/usr/bin/env python3
"""Archive installed dependency license texts and public model provenance."""
import hashlib
import io
from importlib import metadata
import json
from pathlib import Path
import shutil
import ssl
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'licenses/engineering'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = dist.metadata['Name'], dist.version
        target = OUT / (name + '-' + version)
        files = []
        for entry in dist.files or []:
            if not any(word in Path(str(entry)).name.lower() for word in ('license', 'licence', 'copying', 'notice')):
                continue
            original = dist.locate_file(entry)
            if not original.is_file() or original.stat().st_size > 5_000_000:
                continue
            target.mkdir(exist_ok=True)
            filename = str(entry).replace('/', '__').replace('\\', '__')
            shutil.copyfile(original, target / filename)
            files.append(str((target / filename).relative_to(OUT)))
        inventory.append({'name': name, 'version': version,
                          'license_expression': dist.metadata.get('License-Expression'),
                          'license_metadata': dist.metadata.get('License'),
                          'classifiers': dist.metadata.get_all('Classifier') or [],
                          'project_urls': dist.metadata.get_all('Project-URL') or [],
                          'archived_files': files})
    # OCCT is embedded by the wheel and must remain separately documented.
    upstream = {
        'OCCT-7.8.1-LGPL-2.1.txt': 'https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_8_1/LICENSE_LGPL_21.txt',
        'OCCT-7.8.1-exception.txt': 'https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_8_1/OCCT_LGPL_EXCEPTION.txt',
        'FreeImage-3.18.0-FIPL.txt': 'https://freeimage.sourceforge.io/freeimage-license.txt',
        'LibRaw-0.21.3-COPYRIGHT.txt': 'https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/COPYRIGHT',
        'LibRaw-0.21.3-LGPL.txt': 'https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/LICENSE.LGPL',
        'LibRaw-0.21.3-CDDL.txt': 'https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/LICENSE.CDDL',
    }
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').is_file() else None)
    sources = []
    for filename, url in upstream.items():
        with urllib.request.urlopen(url, context=context, timeout=60) as response:
            data = response.read()
        (OUT / filename).write_bytes(data)
        sources.append({'file': filename, 'url': url, 'sha256': hashlib.sha256(data).hexdigest()})
    # BCE's exact wheel omits its license text; the matching official sdist
    # retains Baidu's Apache-2.0 copyright header. Never infer from Paddle's license.
    bce = next((entry for entry in inventory if entry['name'].lower() == 'bce-python-sdk'), None)
    if bce and not bce['archived_files']:
        url = 'https://pypi.org/pypi/bce-python-sdk/' + bce['version'] + '/json'
        with urllib.request.urlopen(url, context=context, timeout=60) as response:
            release = json.load(response)
        source = next(entry for entry in release['urls'] if entry['packagetype'] == 'sdist')
        with urllib.request.urlopen(source['url'], context=context, timeout=60) as response:
            payload = response.read(10_000_001)
        if len(payload) > 10_000_000 or hashlib.sha256(payload).hexdigest() != source['digests']['sha256']:
            raise RuntimeError('BCE source archive digest mismatch')
        target = OUT / ('bce-python-sdk-' + bce['version'])
        target.mkdir(exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith('/baidubce/__init__.py'))
            header = archive.extractfile(member).read()
        if b'Licensed under the Apache License, Version 2.0' not in header:
            raise RuntimeError('BCE source license changed')
        (target / 'upstream-package-copyright.py.txt').write_bytes(header)
        (target / 'source-provenance.json').write_text(json.dumps(source, indent=2) + '\n')
        apache_url = 'https://www.apache.org/licenses/LICENSE-2.0.txt'
        with urllib.request.urlopen(apache_url, context=context, timeout=60) as response:
            apache = response.read()
        (target / 'APACHE-2.0.txt').write_bytes(apache)
        bce['archived_files'] = [str(p.relative_to(OUT)) for p in target.iterdir() if p.is_file()]
        sources.append({'file': str((target / 'APACHE-2.0.txt').relative_to(OUT)),
                        'url': apache_url, 'sha256': hashlib.sha256(apache).hexdigest(),
                        'copyright_evidence_sdist': source['url'], 'sdist_sha256': source['digests']['sha256']})
    native = ROOT / '.venv-engineering/lib'
    embedded = [{'file': str(p.relative_to(ROOT / '.venv-engineering')), 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                 'license_scope': 'embedded native dependency; wrapper license is not sufficient'}
                for p in native.glob('python*/site-packages/OCP/.dylibs/*.dylib')]
    (OUT / 'embedded-ocp-native-libraries.json').write_text(json.dumps(embedded, indent=2) + '\n')
    wheel_origins = ROOT / '.engineering-wheelhouse'
    for origin in wheel_origins.glob('*.origin.json'):
        shutil.copyfile(origin, OUT / origin.name)
    models = ROOT / 'models/engineering'
    if (models / 'manifest.json').exists():
        shutil.copyfile(models / 'manifest.json', OUT / 'model-manifest.json')
        for entry in json.loads((models / 'manifest.json').read_text())['models']:
            shutil.copyfile(models / entry['name'] / 'README.md', OUT / (entry['name'] + '-MODEL-CARD.md'))
    (OUT / 'installed-dependencies.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'upstream-license-sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    print('Archived dependency packages:', len(inventory))
    print('Packages without bundled license texts:', ', '.join(d['name'] for d in inventory if not d['archived_files']))


if __name__ == '__main__':
    main()
