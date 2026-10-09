#!/usr/bin/env python3
"""Initialize a portable, entirely synthetic KANPACE demonstration database.

Usage from the independent demo launcher::

    from tools.demo_fixture import prepare_demo
    info = prepare_demo(data_dir)
    store = Store(data_dir, seed=False, empty=True)

Only an empty, explicitly supplied directory can be initialized. Reopening a
recognized demo validates its two identity markers and makes no data changes.
The default production data directory is always rejected. The fixture imports
only the checked-in synthetic CSV and copies prebuilt synthetic PNG files;
runtime generation requires only Python's standard library and the application.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import sys
import tempfile
import uuid


APP = Path(__file__).resolve().parents[1]
ASSETS = APP / 'static' / 'demo-assets'
MARKER_NAME = '.kanpace-demo.json'
CONFIG_KEY = 'standalone_demo'
IDENTITY = 'kanpace.synthetic.standalone-demo'
VERSION = 1
DEMO_NOTE = ('合成演示：仅用于体验资料关联、审核、发布和报工流程；'
             '未进行真实尺寸、结构、材料或安全校核，不可据此加工。')


class DemoFixtureError(ValueError):
    """The requested directory cannot safely be used as this demo's storage."""


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _existing_demo(root):
    """Verify metadata read-only before any Store constructor can write."""
    marker = root / MARKER_NAME
    db = root / 'cabinet-flow.sqlite3'
    if marker.is_symlink() or db.is_symlink() or not marker.is_file() or not db.is_file():
        raise DemoFixtureError('该目录不是完整的独立演示库；请选择新的空目录。')
    try:
        identity = _json(marker)
        if (identity.get('kind') != IDENTITY or identity.get('version') != VERSION
                or not identity.get('instance_id')):
            raise ValueError('unrecognized marker')
        # URI read-only mode avoids creating or upgrading an unknown database.
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as con:
            row = con.execute('SELECT value FROM config WHERE key=?', (CONFIG_KEY,)).fetchone()
            production = con.execute("SELECT 1 FROM config WHERE key='factory_instance'").fetchone()
        saved = json.loads(row[0]) if row else None
        if saved != identity or production:
            raise ValueError('database identity does not match demo marker')
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error) as exc:
        raise DemoFixtureError('演示库身份校验失败；不会打开或覆盖现有数据。') from exc
    return {**identity, 'initialized': False, 'data_dir': str(root)}


def _image_entry(root, filename, *, kind, title, source_file, project_id):
    """Register checked-in PNGs using the real drawing_media asset contract."""
    source = ASSETS / filename
    raw = source.read_bytes()
    if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
        raise DemoFixtureError('合成演示图片无效：' + filename)
    width, height = struct.unpack('>II', raw[16:24])
    digest = hashlib.sha256(raw).hexdigest()
    target = root / 'drawing-previews' / 'assets' / (digest + '.png')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    url = '/api/drawing-media/assets/' + target.name
    return {'id': digest, 'url': url, 'thumb_url': url, 'width': width, 'height': height,
            'project_id': project_id, 'kind': kind, 'title': title,
            'scope': 'project', 'source_file': source_file, 'source_sha256': digest,
            'source_category': 'synthetic_demo', 'reference_status': 'synthetic_demo',
            'reference_note': DEMO_NOTE, 'demo': True}


def _media(root, project_id, parts, seed=False):
    prefix = 'showcase' if seed else 'sample'
    name = '璞玉' if seed else '澄光'
    render = _image_entry(root, prefix + '-render.png', kind='柜体效果图',
                         title=name + ' · 合成演示效果示意',
                         source_file=name + '-合成演示效果示意.png', project_id=project_id)
    drawing = _image_entry(root, prefix + '-drawing.png', kind='施工图',
                          title=name + ' · 合成演示施工示意',
                          source_file=name + '-合成演示施工示意.png', project_id=project_id)
    drawing['page'] = 1
    return {'project_id': project_id, 'demo': True, 'renders': [render], 'sources': [drawing],
            'parts': {part['id']: [dict(drawing, scope='project_reference',
                                      reference_note='整单合成示意，非该部件展开图。' + DEMO_NOTE)]
                      for part in parts}}


def _import_sample(store, con, name, due_date, *, reviewed):
    project = store.new_project(con, {'name': name, 'client': '合成演示 · 无真实客户',
                                     'due_date': due_date, 'quantity': 1}, demo=True)
    raw = (APP / 'samples' / 'showcase-bom.csv').read_bytes()
    imported = store.import_file(con, {
        'project_id': project['id'], 'filename': '合成演示-showcase-bom.csv',
        'content_base64': base64.b64encode(raw).decode('ascii'), 'purpose': 'drawing'})
    # Normal upload intentionally does not trust a user-supplied demo flag.
    # Here, fixture-owned imported records are explicitly labelled synthetic.
    doc = imported['document']
    doc.update(demo=True, synthetic_demo=True, provenance='samples/showcase-bom.csv',
               reference_note=DEMO_NOTE)
    store.put(con, 'documents', doc)
    for part in imported['parts']:
        part.update(demo=True, synthetic_demo=True, notes=DEMO_NOTE)
        part['source'] = {**part.get('source', {}), 'file': doc['filename'],
                          'reference': '内置合成 CSV 行 / ' + part['name'],
                          'revision': 'DEMO-A01'}
        store.put(con, 'parts', part)
        if reviewed:
            store.review_part(con, part['id'], {'approved': True, 'review_note': DEMO_NOTE})
    # Pending review still has complete fields, so users can inspect an actual
    # task proposal and see the unmodified release gate reject unreviewed parts.
    store.generate(con, project['id'])
    if reviewed:
        store.release(con, project['id'])
        store.auto_assign(con, project['id'])
    current = store.get(con, 'projects', project['id'])
    current.update(demo_scenario='ready' if reviewed else 'review', demo_note=DEMO_NOTE)
    store.put(con, 'projects', current)
    return current


def _build(root):
    # Import after all path/identity checks. These are the exact production
    # application services; this module does not modify their release rules.
    from kanpace.application.store import Store
    from kanpace.core.validation import now

    store = Store(root, seed=False)
    with store.write_transaction() as con:
        store.seed(con)
        showcase = store.all(con, 'projects')[0]
        showcase.update(name='璞玉 · 珠宝中岛柜（合成演示）', demo_scenario='showcase',
                        client='内置合成演示 · 无真实客户', demo_note=DEMO_NOTE,
                        due_date=(date.today() + timedelta(days=7)).isoformat())
        store.put(con, 'projects', showcase)
        for person in store.all(con, 'people'):
            person.update(name=person['name'] + '（演示）', demo=True)
            store.put(con, 'people', person)
        review = _import_sample(store, con, '澄光 · 待技术复核（合成演示）',
                                (date.today() + timedelta(days=12)).isoformat(), reviewed=False)
        ready = _import_sample(store, con, '澄光 · 可开工任务（合成演示）',
                               (date.today() + timedelta(days=9)).isoformat(), reviewed=True)
        showcase_tasks = store.active_tasks(con, showcase['id'])
        runnable = [task for task in showcase_tasks if task['status'] == 'ready'
                    and not store.start_blockers(con, task)]
        running = next((task for task in runnable if task['trade'] == '木工'), runnable[0])
        running = store.set_status(con, running['id'], {'status': 'in_progress',
                                                       'note': '合成演示：已开工，可练习进度、暂停和完工。'})
        candidates = [task for task in store.active_tasks(con, ready['id'])
                      if task['status'] == 'ready' and not store.start_blockers(con, task)]
        pause = next((task for task in candidates if task['trade'] == '玻璃'), candidates[-1])
        pause = store.pause_task(con, pause['id'], {
            'reason': 'equipment', 'note': '合成演示：玻璃加工设备等待例行点检。',
            'handover_note': '演示场景：设备点检完成后填写解除依据，再恢复任务。'})
        runnable_ready = [task for task in store.active_tasks(con, ready['id'])
                          if task['status'] == 'ready' and not store.start_blockers(con, task)]
        if not runnable_ready:
            raise DemoFixtureError('演示初始化未留下可实际开工的任务。')
        media = {'version': 1, 'synthetic_demo': True, 'reference_note': DEMO_NOTE, 'projects': {}}
        for project in (showcase, review, ready):
            media['projects'][project['id']] = _media(
                root, project['id'], store.active_parts(con, project['id']), seed=project is showcase)
        _dump(root / 'drawing-previews' / 'manifest.json', media)
        identity = {'kind': IDENTITY, 'version': VERSION, 'instance_id': str(uuid.uuid4()),
                    'created_at': now(), 'synthetic_demo': True, 'note': DEMO_NOTE,
                    'project_ids': {'showcase': showcase['id'], 'review': review['id'], 'ready': ready['id']},
                    'person_ids': {person['role']: person['id'] for person in store.all(con, 'people')},
                    'task_ids': {'in_progress': running['id'], 'paused': pause['id'],
                                 'ready': runnable_ready[0]['id']},
                    'scenarios': [
                        {'key': 'showcase', 'title': '图纸、效果与现场进度', 'project_id': showcase['id'],
                         'description': '查看四类工种的合成展柜、效果示意和施工示意；有已开工任务可报工。'},
                        {'key': 'review', 'title': '待复核到发布', 'project_id': review['id'],
                         'description': '8 项部件尚未审核；可在技术复核页逐项审核，再按原规则发布。'},
                        {'key': 'ready', 'title': '开工与解除暂停', 'project_id': ready['id'],
                         'description': '已发布并匹配人员；可开工任务及设备点检暂停任务均使用真实业务操作。'}]}
        con.execute('INSERT INTO config VALUES (?,?)', (CONFIG_KEY, json.dumps(identity, ensure_ascii=False)))
        store.event(con, None, 'standalone_demo_initialized', DEMO_NOTE, synthetic_demo=True,
                    project_ids=identity['project_ids'])
    # Close/checkpoint before atomically moving the self-contained database.
    with store.connect() as con:
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    _dump(root / MARKER_NAME, identity)
    return identity


def prepare_demo(data_dir):
    """Create once, or verify and preserve an existing independent demo.

    Returns serializable metadata with project_ids, person_ids, task_ids and an
    initialized boolean. Refuses any unmarked nonempty directory, any symlinked
    storage identity, or a database carrying a production factory marker.
    """
    requested = Path(data_dir).expanduser()
    if requested.is_symlink():
        raise DemoFixtureError('演示数据目录不能是符号链接。')
    root = requested.resolve()
    if root == (APP / 'data').resolve():
        raise DemoFixtureError('独立演示禁止使用正式 data 目录；请指定专用的空目录。')
    if root.exists():
        if not root.is_dir():
            raise DemoFixtureError('演示数据路径不是文件夹。')
        if (root / MARKER_NAME).exists() or (root / MARKER_NAME).is_symlink():
            return _existing_demo(root)
        if any(root.iterdir()):
            raise DemoFixtureError('该目录已有非演示内容；独立演示只初始化专用空目录。')
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + root.name + '.demo-build-', dir=root.parent))
    try:
        identity = _build(staging)
        # rmdir only succeeds if the caller-provided directory is still empty.
        if root.exists():
            root.rmdir()
        staging.rename(root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {**identity, 'initialized': True, 'data_dir': str(root)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    try:
        result = prepare_demo(args.data_dir)
    except (DemoFixtureError, OSError) as exc:
        parser.exit(2, '独立演示初始化失败：' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
