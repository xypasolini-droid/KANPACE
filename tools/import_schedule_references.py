#!/usr/bin/env python3
"""Import original XLS/XLSX files into independent reference snapshots only."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
import schedule_reference as reference


def business_digest(store):
    with store.connect() as con:
        records = [tuple(row) for row in con.execute('SELECT kind,id,project_id,data FROM entities WHERE kind != ? ORDER BY kind,id', (reference.KIND,))]
        configs = [tuple(row) for row in con.execute('SELECT key,value FROM config ORDER BY key')]
    return hashlib.sha256(json.dumps([records, configs], ensure_ascii=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--summary', type=Path, help='Optional JSON summary path (source values are not included).')
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error('source directory does not exist')
    files = sorted(p for p in args.directory.iterdir() if p.is_file() and p.suffix.lower() in ('.xls', '.xlsx')
                   and not p.name.startswith(('.', '~$')))
    store = app.Store(args.data_dir, seed=False)
    before = business_digest(store)
    imported, errors = [], []
    for path in files:
        try:
            original = path.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            with store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                result = reference.import_reference(store, con, {'filename': path.name, 'content_base64': base64.b64encode(original).decode()})
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('source file changed during import')
            source = result['source']
            entry = {key: source[key] for key in ('id', 'filename', 'sha256', 'snapshot_date', 'date_trusted', 'default_sheet', 'row_count', 'group_count', 'sheet_count')}
            entry.update(duplicate=result['duplicate'], reparsed=result.get('reparsed', False))
            imported.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
        except Exception as exc:
            errors.append({'filename': path.name, 'error': str(exc)})
            print(json.dumps(errors[-1], ensure_ascii=False), file=sys.stderr, flush=True)
    with store.connect() as con:
        grid = reference.get_references(store, con)
    summary = {'files_found': len(files), 'imported': imported, 'errors': errors,
               'business_data_unchanged': business_digest(store) == before,
               'selected': grid['selected'], 'sources_registered': len(grid['sources']),
               'stats': [{k: s[k] for k in ('node_id', 'n', 'p25', 'p50', 'p75', 'n_same_day', 'historical_fallback_count', 'anomaly_count', 'revision_groups_merged')} for s in grid['stats']]}
    if args.summary:
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'imported'}, ensure_ascii=False, indent=2))
    return 1 if errors or not summary['business_data_unchanged'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
