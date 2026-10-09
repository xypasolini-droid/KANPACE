#!/usr/bin/env python3
"""Rebuild reviewed project render previews without changing production data.

Requires Python 3.10+, Pillow, and Poppler's pdftoppm for PDF sources.
The adjacent selection JSON is an explicit, visually reviewed allowlist.
Sources are read only. Changed sources fail closed instead of reusing a page
selection against an unreviewed revision. Only each project's `renders` changes.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

ASSET_URL = '/api/drawing-media/assets/'
APP = Path(__file__).resolve().parents[1]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Source is outside the selected order directory: {relative}')
    return path


def store_image(raw: bytes, key: str, assets: Path) -> dict:
    with Image.open(io.BytesIO(raw)) as original:
        image = ImageOps.exif_transpose(original).convert('RGBA')
        rgb = Image.new('RGB', image.size, 'white')
        rgb.paste(image, mask=image.getchannel('A'))
        rgb.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
        width, height = rgb.size
        for suffix, size, quality in [('', None, 93), ('-thumb', (720, 560), 88)]:
            target = assets / f'{key}{suffix}.webp'
            if not target.exists():
                preview = rgb.copy()
                if size:
                    preview.thumbnail(size, Image.Resampling.LANCZOS)
                with tempfile.NamedTemporaryFile(dir=assets, suffix='.webp', delete=False) as tmp:
                    preview.save(tmp, 'WEBP', quality=quality, method=5)
                    temporary = Path(tmp.name)
                temporary.replace(target)
    return {'id': key, 'url': ASSET_URL + key + '.webp',
            'thumb_url': ASSET_URL + key + '-thumb.webp', 'width': width, 'height': height}


def build_render(item: dict, root: Path, assets: Path, pdftoppm: str | None) -> dict:
    path = source_path(root, item['source_relative'])
    raw = path.read_bytes()
    actual = sha256(raw)
    if actual != item['source_sha256']:
        raise ValueError(f'Source changed and needs visual review: {item["source_relative"]}')
    key = sha256((json.dumps({k: item.get(k) for k in ('source_sha256', 'page', 'zip_member')},
                            sort_keys=True) + ':project-render:3200:v1').encode())
    full = assets / f'{key}.webp'
    thumb = assets / f'{key}-thumb.webp'
    if full.exists() and thumb.exists():
        with Image.open(full) as im:
            image = {'id': key, 'url': ASSET_URL + full.name, 'thumb_url': ASSET_URL + thumb.name,
                     'width': im.width, 'height': im.height}
    else:
        if item.get('page'):
            if not pdftoppm:
                raise RuntimeError('Install Poppler (pdftoppm) to render PDF pages.')
            with tempfile.TemporaryDirectory(prefix='cabinet-project-render-') as tmp:
                prefix = Path(tmp) / 'page'
                subprocess.run([pdftoppm, '-f', str(item['page']), '-l', str(item['page']),
                                '-singlefile', '-scale-to', '3200', '-png', str(path), str(prefix)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
                image = store_image(prefix.with_suffix('.png').read_bytes(), key, assets)
        elif item.get('zip_member'):
            with zipfile.ZipFile(io.BytesIO(raw)) as workbook:
                member = item['zip_member']
                if not member.startswith('xl/media/') or '..' in Path(member).parts:
                    raise ValueError('Only reviewed embedded workbook media are supported.')
                picture = workbook.read(member)
            if sha256(picture) != item['image_sha256']:
                raise ValueError(f'Workbook image changed: {path.name} {member}')
            image = store_image(picture, key, assets)
        else:
            image = store_image(raw, key, assets)
    return {**image, **{k: item[k] for k in ('title', 'kind', 'scope', 'source_sha256',
            'source_category', 'page', 'sheet', 'cell', 'reference_note', 'reference_status') if k in item},
            'source_file': path.name}


def content_fingerprint(manifest: dict) -> str:
    clone = json.loads(json.dumps(manifest))
    for project in clone['projects'].values():
        project.pop('renders', None)
    return sha256(json.dumps(clone, sort_keys=True, ensure_ascii=False).encode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=APP / 'data')
    parser.add_argument('--selection', type=Path, default=Path(__file__).with_name('project-render-selection.json'))
    parser.add_argument('--report', type=Path, default=APP / 'docs/verification/project-render-assets.json')
    args = parser.parse_args()
    root = args.source_dir.resolve(strict=True)
    selection = json.loads(args.selection.read_text(encoding='utf-8'))
    cache = args.data_dir / 'drawing-previews'
    manifest_path = cache / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    fingerprint = content_fingerprint(manifest)
    assets = cache / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    pdftoppm = shutil.which('pdftoppm')
    built, reports = {}, []
    for project_id, project in manifest['projects'].items():
        spec = selection['orders'].get(project.get('order_key'))
        if spec is None:
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            renders = list(pool.map(lambda row: build_render(row, root, assets, pdftoppm), spec['selected']))
        built[project_id] = renders
        reports.append({'project_id': project_id, 'order_key': project['order_key'],
                        'name': spec['name'], 'render_count': len(renders),
                        'scope_counts': dict(Counter(r['scope'] for r in renders)),
                        'source_categories': dict(Counter(r['source_category'] for r in renders)),
                        'notes': spec.get('notes', []), 'excluded': spec.get('excluded', []),
                        'renders': renders})
        print(spec['name'], len(renders), flush=True)
    # Check for other edits before writing the manifest, and preserve all other fields.
    current = json.loads(manifest_path.read_text(encoding='utf-8'))
    if content_fingerprint(current) != fingerprint:
        raise RuntimeError('The drawing manifest changed while rendering. Rerun to preserve current data.')
    for project_id, renders in built.items():
        current['projects'][project_id]['renders'] = renders
    assert content_fingerprint(current) == fingerprint
    temporary = manifest_path.with_suffix('.renders.tmp')
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(manifest_path)
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'source_directory': str(root),
              'selection_version': selection['version'], 'visually_reviewed': True,
              'original_manifest_fields_preserved': True, 'original_sources_read_only': True,
              'summary': {'projects': len(reports), 'projects_with_renders': sum(bool(r['render_count']) for r in reports),
                          'projects_without_renders': sum(not r['render_count'] for r in reports),
                          'renders': sum(r['render_count'] for r in reports)},
              'review_notes': selection.get('review_notes', []), 'projects': reports}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
