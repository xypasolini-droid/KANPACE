#!/usr/bin/env python3
"""Build a private, isolated Web demo from user-provided historical orders.

The source manifest is private and supplied at run time. Nothing is written to
the mounted order folders or to KANPACE's ordinary ``data`` directory. A demo
identity is published only after every project and source has been checked.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from kanpace.application.store import Store
from kanpace.core.validation import now
import order_packet
import project_overview
import schedule_reference


IDENTITY = 'kanpace.historical.standalone-demo'
MARKER = '.kanpace-historical-demo.json'
NOTE = '真实历史资料，仅供本机演示；未获客户/技术员确认，不可派工或加工。'


def say(message):
    print(message, flush=True)


def bytes_for(case, entry):
    relative = Path(entry['path'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('来源相对路径无效')
    root = Path(case['root']).resolve(strict=True)
    source = root / relative
    if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
        raise ValueError('来源文件不存在或不在订单目录内：' + entry['path'])
    raw = source.read_bytes()
    if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('来源文件与清单哈希不符：' + entry['path'])
    return raw


def import_document(store, case, project_id, entry, *, purpose='drawing', related_id=None):
    raw = bytes_for(case, entry)
    request = {'project_id': project_id, 'filename': Path(entry['path']).name,
               'relative_path': entry['path'], 'purpose': purpose,
               'content_base64': base64.b64encode(raw).decode('ascii')}
    if related_id:
        request['related_document_id'] = related_id
    with store.write_transaction() as con:
        result = store.import_file(con, request)
        doc = result['document']
        if purpose == 'render':
            # The render import route stores its image but omits the source path.
            doc['relative_path'] = entry['path']
            doc['source_paths'] = list(dict.fromkeys(doc.get('source_paths', []) + [entry['path']]))
            store.put(con, 'documents', doc)
        doc_id = doc['id']
    say(f"  {purpose}: {entry['path']} ({len(raw)//1024} KiB)")
    return doc_id


def companion_id(pdf, assemblies):
    stem = Path(pdf['path']).stem.casefold()
    for assembly_path, doc_id in assemblies.items():
        native = Path(assembly_path)
        if stem in {part.casefold() for part in native.parts[:-1]} or stem == native.stem.casefold():
            return doc_id
    return None


def build_case(store, case):
    name = case['project_display_name']
    with store.write_transaction() as con:
        project = store.new_project(con, {'name': name, 'client': case['client_display_name'],
                                          'factory_type': 'cabinet'})
        project.update(demo_dataset=True, historical_order=True,
                       historical_order_no=case['order_number_from_folder'],
                       demo_note=NOTE, demo_source_kind='user_provided_historical_files')
        if case['slug'] == 'demo_jewelry':
            # The only fabricated schedule row is explicitly SIM-prefixed. It
            # does not become the original order number or a real factory date.
            project['external_order_no'] = 'SIM-DEMO-0001'
            project['demo_schedule_note'] = '仅与单独标记“模拟测试”的排程行关联，非该历史订单的真实排程。'
        store.put(con, 'projects', project)
        project_id = project['id']
    say(f"\n[{case['slug']}] {name} · {project_id}")

    master_id = import_document(store, case, project_id, case['master_order'])
    import_document(store, case, project_id, case['workshop_instruction'])
    effects = []
    for entry in case['effect_sources']:
        purpose = 'render' if Path(entry['path']).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') else 'drawing'
        effects.append((entry, import_document(store, case, project_id, entry, purpose=purpose)))
    import_document(store, case, project_id, case['construction']['dwg'])
    import_document(store, case, project_id, case['construction']['pdf'])
    assemblies = {}
    for entry in case['engineering']['native_assembly_examples']:
        assemblies[entry['path']] = import_document(store, case, project_id, entry)
    for entry in case['engineering']['packet_pdfs']:
        import_document(store, case, project_id, entry, related_id=companion_id(entry, assemblies))

    # The generic file parser may have inferred tentative parts from standalone
    # documents. Retain those records for audit, but only the matched order
    # packet should provide the visible cabinet-level work-scope drafts.
    with store.write_transaction() as con:
        preliminary = store.active_parts(con, project_id)
        for part in preliminary:
            part.update(archived=True, preliminary_import=True)
            store.put(con, 'parts', part)
        project = store.get(con, 'projects', project_id)
        packet = order_packet.save(store, con, project_id, {
            'master_document_id': master_id, 'sheet': case['master_order']['sheet'],
            'expected_revision': project['revision']})
        result_parts = packet['parts']
        if len(result_parts) != case['master_order']['item_count']:
            raise ValueError(f"{name} 构件数不符：{len(result_parts)} != {case['master_order']['item_count']}")
        project = store.get(con, 'projects', project_id)
        project['demo_source_count'] = case['selected_source_count']
        project['demo_preliminary_parts_archived'] = len(preliminary)
        store.put(con, 'projects', project)
    say(f"  拆解草稿：{len(packet['parts'])} 项构件，{len(packet['tasks'])} 道工种任务；无审批或派工")

    with store.write_transaction() as con:
        if effects and Path(effects[0][0]['path']).suffix.lower() == '.pdf':
            entry, doc_id = effects[0]
            doc = store.get(con, 'documents', doc_id)
            page = entry['featured_page']
            project_overview.save(store, con, project_id, {
                'expected_version': 0, 'document_id': doc_id,
                'document_sha256': doc['sha256'], 'pages': [page],
                'cover_id': f'overview_{doc_id}_{page}'})
        elif effects:
            project_overview.save(store, con, project_id, {
                'expected_version': 0, 'cover_id': effects[0][1]})
    return project_id, {'parts': len(packet['parts']), 'tasks': len(packet['tasks']),
                        'documents': case['selected_source_count']}


def build(root, manifest, schedule_files):
    store = Store(root, seed=False, empty=True)
    project_ids, counts = {}, {}
    for case in manifest['cases']:
        identifier, stats = build_case(store, case)
        project_ids[case['slug']] = identifier
        counts[case['slug']] = stats
    schedule_ids = {}
    for label, path in schedule_files.items():
        raw = path.read_bytes()
        with store.write_transaction() as con:
            result = schedule_reference.import_reference(store, con, {
                'filename': path.name, 'content_base64': base64.b64encode(raw).decode('ascii')})
            schedule_ids[label] = result['source']['id']
        say(f"排程参考：{label} · {result['row_count']} 行")
    with store.read_transaction() as con:
        synthetic = schedule_reference.get_references(store, con, schedule_ids['simulated'])['working']
        if 'demo_jewelry' in project_ids:
            matched = [row for row in synthetic['orders'] if row.get('project_id') == project_ids['demo_jewelry']]
            if len(matched) != 1:
                raise ValueError('模拟排程没有唯一关联演示项目')
        for slug, expected in counts.items():
            pid = project_ids[slug]
            parts = store.active_parts(con, pid)
            tasks = store.active_tasks(con, pid)
            if len(parts) != expected['parts'] or len(tasks) != expected['tasks']:
                raise ValueError('构件或任务在保存后发生变化：' + slug)
            if any(t.get('status') != 'draft' for t in tasks) or any(p.get('approved') for p in parts):
                raise ValueError('历史演示不可伪造已审核或已发布状态：' + slug)
    marker = {'kind': IDENTITY, 'version': 1, 'instance_id': str(uuid.uuid4()),
              'created_at': now(), 'project_ids': project_ids, 'case_counts': counts,
              'schedule_sources': schedule_ids, 'note': NOTE,
              'simulated_schedule_note': 'SIM 排程是虚构测试行，不代表历史订单实际日期。'}
    with store.write_transaction() as con:
        con.execute('INSERT INTO config(key,value) VALUES (?,?)',
                    ('historical_demo', json.dumps(marker, ensure_ascii=False)))
        store.event(con, None, 'historical_demo_initialized', NOTE, project_ids=project_ids)
    with store.connect() as con:
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    target = root / MARKER
    target.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    target.chmod(0o600)
    return marker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--schedule-real', type=Path, required=True)
    parser.add_argument('--schedule-simulated', type=Path, required=True)
    parser.add_argument('--only', help='Select any slug from the private source manifest')
    args = parser.parse_args(argv)
    os.umask(0o077)
    requested = args.data_dir.expanduser()
    if requested.is_symlink():
        parser.error('演示目录不能是符号链接')
    target = requested.resolve()
    if target == (APP / 'data').resolve() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        parser.error('演示只允许写入新的专用空目录，不得使用正式 data')
    manifest_path = args.manifest.expanduser().resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('publishable') is not False or manifest.get('classification') != 'private-local-source-manifest':
        parser.error('必须使用明确标记为私有、不可发布的历史资料清单')
    if args.only:
        manifest['cases'] = [case for case in manifest['cases'] if case['slug'] == args.only]
    if not manifest['cases']:
        parser.error('没有选择任何历史订单')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + target.name + '.build-', dir=target.parent))
    staging.chmod(0o700)
    try:
        marker = build(staging, manifest, {'real': args.schedule_real.resolve(strict=True),
                                            'simulated': args.schedule_simulated.resolve(strict=True)})
        if target.exists():
            target.rmdir()
        staging.rename(target)
        say('完成：' + str(target))
        say(json.dumps({'project_ids': marker['project_ids'], 'case_counts': marker['case_counts']}, ensure_ascii=False))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
