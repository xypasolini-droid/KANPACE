"""The historical demo never opens unmarked data or reaches a real badge."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kanpace.application.store import Store
from device_bridge import DeviceError
import launch_historical_demo as demo
from tools import attach_personnel_snapshot as snapshot_tool


def personnel_workbook():
    """Synthetic OOXML fixture; no customer or staff data enters tests."""
    out = io.BytesIO()
    namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def row(number, values):
        cells = ''.join(f'<c r="{col}{number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                        for col, value in zip('ABC', values))
        return f'<row r="{number}">{cells}</row>'
    rows = row(1, ['姓名', '车间', '岗位'])
    rows += row(2, ['演示甲', '木作车间', '木工'])
    rows += row(3, ['演示乙', '玻璃车间', '玻璃加工'])
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="人员" sheetId="1" r:id="r1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{namespace}"><sheetData>{rows}</sheetData></worksheet>')
    return out.getvalue()


class HistoricalDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'historical'
        self.store = Store(self.root, seed=False, empty=True)
        with self.store.write_transaction() as con:
            project = self.store.new_project(con, {'name': '历史订单隔离演示'})
        self.project_id = project['id']
        self.marker = {
            'kind': demo.IDENTITY,
            'version': demo.VERSION,
            'instance_id': str(uuid.uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'project_ids': {'sample': project['id']},
            'note': demo.NOTICE,
        }
        self.write_marker()

    def tearDown(self):
        self.temp.cleanup()

    def write_marker(self):
        payload = json.dumps(self.marker, ensure_ascii=False)
        (self.root / demo.MARKER_NAME).write_text(payload, encoding='utf-8')
        with closing(sqlite3.connect(self.store.db_path)) as con:
            with con:
                con.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)', (demo.CONFIG_KEY, payload))

    def test_identity_must_be_marked_and_match_the_database(self):
        root, marker = demo.validate_demo_dir(self.root)
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(marker, self.marker)
        with closing(sqlite3.connect(self.store.db_path)) as con:
            with con:
                con.execute('UPDATE config SET value=? WHERE key=?', ('{}', demo.CONFIG_KEY))
        with self.assertRaises(demo.HistoricalDemoError):
            demo.validate_demo_dir(self.root)

    def test_rejects_unmarked_nonempty_directory_symlinks_and_factory_identity(self):
        marker_file = self.root / demo.MARKER_NAME
        marker_file.unlink()
        with self.assertRaises(demo.HistoricalDemoError):
            demo.validate_demo_dir(self.root)
        self.write_marker()
        alias = Path(self.temp.name) / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(demo.HistoricalDemoError):
            demo.validate_demo_dir(alias)
        with closing(sqlite3.connect(self.store.db_path)) as con:
            with con:
                con.execute("INSERT INTO config(key,value) VALUES('factory_instance','{}')")
        with self.assertRaises(demo.HistoricalDemoError):
            demo.validate_demo_dir(self.root)

    def test_missing_or_foreign_project_ids_are_rejected(self):
        self.marker['project_ids'] = {'other': 'prj_does_not_exist'}
        self.write_marker()
        with self.assertRaises(demo.HistoricalDemoError):
            demo.validate_demo_dir(self.root)

    def test_hardware_mutations_blocked_and_demo_banner_injected(self):
        server = demo.historical_server(('127.0.0.1', 0), self.store)
        server.demo_info = {**self.marker, 'mode': 'historical_demo',
                            'directory_id': demo.directory_id(self.root), 'hardware_enabled': False}
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        host = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(host + '/api/demo-info', timeout=3) as response:
                info = json.load(response)
            self.assertEqual(info['mode'], 'historical_demo')
            self.assertFalse(info['hardware_enabled'])
            with urllib.request.urlopen(host + '/factory/index.html', timeout=3) as response:
                html = response.read().decode('utf-8')
            self.assertIn('/historical-demo/ui.js', html)
            with urllib.request.urlopen(host + '/historical-demo/ui.js', timeout=3) as response:
                self.assertIn('实体胸牌已禁用', response.read().decode('utf-8'))
            with urllib.request.urlopen(host + '/control/index.html', timeout=3) as response:
                self.assertIn('/historical-demo/ui.js', response.read().decode('utf-8'))
            self.assertIsNone(server.project_dispatch.worker)
            self.assertIsNone(server.device_bridge._port_provider)
            server.device_bridge._port_provider = lambda: self.fail('演示不应扫描 USB 串口')
            with urllib.request.urlopen(host + '/api/device', timeout=3) as response:
                device = json.load(response)
            self.assertEqual(device['ports'], [])
            self.assertFalse(device['device']['dependency_available'])
            with self.assertRaises(DeviceError):
                server.device_bridge.connect()
            paths = ['/api/device/connect', '/api/device/images', '/api/device-bindings',
                     '/api/tasks/task_1/send-device', f'/api/projects/{self.project_id}/dispatch',
                     '/api/project-dispatches/job_1/retry',
                     '/api/factory-instances/provision',
                     '/api/control/factories/local/config/plans']
            for path in paths:
                with self.subTest(path=path):
                    request = urllib.request.Request(host + path, data=b'{}', method='POST',
                                                     headers={'Content-Type': 'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(raised.exception.code, 403)
                    raised.exception.close()
            for method in ('PUT', 'PATCH', 'DELETE'):
                for path in ('/api/device/connect', '/api/factory-instances/provision'):
                    with self.subTest(method=method, path=path):
                        request = urllib.request.Request(host + path, data=b'{}', method=method,
                                                         headers={'Content-Type': 'application/json'})
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                        self.assertEqual(raised.exception.code, 403)
                        raised.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_controller_route_match_is_scoped(self):
        self.assertTrue(demo.controller_mutation_route('/api/factory-instances/provision'))
        self.assertTrue(demo.controller_mutation_route('/api/control/factories/local/config/plans'))
        self.assertTrue(demo.controller_mutation_route('/api/control%2Ffactories/local/config'))
        self.assertFalse(demo.controller_mutation_route('/api/industry-templates'))
        self.assertFalse(demo.controller_mutation_route('/api/projects'))

    def test_personnel_snapshot_is_source_only_and_download_is_local(self):
        workbook = Path(self.temp.name) / 'test-roster.xlsx'
        original = personnel_workbook()
        workbook.write_bytes(original)
        with self.store.read_transaction() as con:
            before = len(self.store.all(con, 'people'))
        meta = snapshot_tool.attach(self.root, workbook)
        self.assertEqual(meta['count'], 2)
        self.assertEqual(meta['status'], 'pending_confirmation')
        self.assertEqual(meta['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(snapshot_tool.attach(self.root, workbook), meta)
        self.assertEqual((self.root / 'sources' / demo.PERSONNEL_SOURCE).read_bytes(), original)
        self.assertEqual((self.root / 'sources' / demo.PERSONNEL_SOURCE).stat().st_mode & 0o777, 0o600)
        with self.store.read_transaction() as con:
            self.assertEqual(len(self.store.all(con, 'people')), before)

        server = demo.historical_server(('127.0.0.1', 0), self.store)
        server.demo_root = self.root
        server.demo_info = {**self.marker, 'mode': 'historical_demo',
                            'personnel_snapshot': demo.personnel_snapshot_public(self.root)}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(host + '/api/demo-info') as response:
                info = json.load(response)
            self.assertEqual(info['personnel_snapshot']['count'], 2)
            self.assertNotIn('演示甲', json.dumps(info, ensure_ascii=False))
            with urllib.request.urlopen(host + demo.PERSONNEL_DOWNLOAD) as response:
                self.assertEqual(response.read(), original)
                self.assertIn('attachment', response.headers['Content-Disposition'])
            request = urllib.request.Request(host + demo.PERSONNEL_DOWNLOAD,
                                             headers={'Sec-Fetch-Site': 'cross-site'})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request)
            self.assertEqual(rejected.exception.code, 403)
            rejected.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_personnel_snapshot_rejects_corrupt_or_mismatched_source(self):
        workbook = Path(self.temp.name) / 'test-roster.xlsx'
        workbook.write_bytes(personnel_workbook())
        snapshot_tool.attach(self.root, workbook)
        second = Path(self.temp.name) / 'other-roster.xlsx'
        second.write_bytes(personnel_workbook() + b'changed')
        with self.assertRaises(ValueError):
            snapshot_tool.attach(self.root, second)
        source = self.root / 'sources' / demo.PERSONNEL_SOURCE
        source.write_bytes(b'corrupt')
        with self.assertRaises(demo.HistoricalDemoError):
            demo.personnel_snapshot(self.root)


if __name__ == '__main__':
    unittest.main()
