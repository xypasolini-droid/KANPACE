"""Capture installed runtime versions and included license texts, without secrets."""
from importlib import metadata
from pathlib import Path
import hashlib
import json
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/open-source/licenses/langgraph-runtime'
OUT.mkdir(parents=True, exist_ok=True)
rows = []
for dist in sorted(metadata.distributions(), key=lambda value: value.metadata['Name'].lower()):
    name = dist.metadata['Name']
    files = []
    for file in dist.files or []:
        if not re.search(r'(?:^|/)(?:LICEN[CS]E|NOTICE|COPYING)(?:[._-]|$)', str(file), re.I):
            continue
        source = Path(dist.locate_file(file))
        if not source.is_file():
            continue
        data = source.read_bytes()
        target = re.sub(r'[^a-zA-Z0-9_.-]+', '_', name + '__' + str(file))
        (OUT / target).write_bytes(data)
        files.append({'file': target, 'sha256': hashlib.sha256(data).hexdigest()})
    rows.append({'name': name, 'version': dist.version,
                 'license_expression': dist.metadata.get('License-Expression'),
                 'license_metadata': dist.metadata.get('License'), 'license_files': files})
(OUT / 'manifest.json').write_text(json.dumps({'python': platform.python_version(), 'platform': platform.platform(),
    'packages': rows, 'note': 'Installed distribution license evidence; model weights are not installed by this runtime.'},
    ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'packages': len(rows), 'license_files': sum(len(row['license_files']) for row in rows), 'manifest': str(OUT / 'manifest.json')}))
