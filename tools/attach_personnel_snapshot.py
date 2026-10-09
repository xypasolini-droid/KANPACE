#!/usr/bin/env python3
"""Attach a source-only personnel workbook to a verified private demo.

This command never writes to the operational people table. It preserves the
workbook as a dated source snapshot for review before any staff import.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import file_exchange
import launch_historical_demo as demo


def inspect_workbook(path):
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != '.xlsx':
        raise ValueError('请选择普通 XLSX 人员名册文件')
    raw = path.read_bytes()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('人员名册文件为空或过大')
    parsed = file_exchange.inspect_content(path.name, raw, auto_people=True)
    mapping = file_exchange.people_mapping(parsed['headers'])
    if not {'name', 'workshop', 'role'} <= set(mapping):
        raise ValueError('人员名册必须包含姓名、车间、岗位三列')
    return raw, len(parsed['rows'])


def attach(data_dir, workbook):
    root, _ = demo.validate_demo_dir(data_dir)
    source_path = Path(workbook).expanduser()
    raw, count = inspect_workbook(source_path)
    if count < 1:
        raise ValueError('人员名册没有可保存的记录')
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / 'sources'
    if folder.is_symlink():
        raise ValueError('演示资料目录不能是符号链接')
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    source = folder / demo.PERSONNEL_SOURCE
    meta_path = folder / demo.PERSONNEL_META
    metadata = {'schema_version': 1, 'status': 'pending_confirmation',
                'count': count, 'sha256': digest, 'bytes': len(raw),
                'original_filename': source_path.name}
    if source.exists() or meta_path.exists():
        existing = demo.personnel_snapshot(root)
        if existing and existing[0] == metadata:
            return metadata
        raise ValueError('演示目录已有不同的人员快照；请人工核对，不自动覆盖')
    # Both files are written privately in the verified demo directory. The
    # public endpoint refuses a partial pair, and neither file is in static/.
    fd, temporary = tempfile.mkstemp(prefix='.personnel-', suffix='.xlsx', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, source)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    fd, temporary = tempfile.mkstemp(prefix='.personnel-', suffix='.json', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, meta_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    demo.personnel_snapshot(root)
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--workbook', type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = attach(args.data_dir, args.workbook)
    except (demo.HistoricalDemoError, OSError, ValueError) as exc:
        parser.exit(1, '人员快照未附加：' + str(exc) + '\n')
    print('已保存人员名册快照：' + str(result['count']) + ' 条待核对；未加入派工人员。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
