import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_source_delivery', ROOT / 'tools/build_source_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class SourceDeliveryTests(unittest.TestCase):
    def test_software_allowlist_covers_current_web_and_rejects_runtime_data(self):
        for name in ('workers/docling_service.py', 'config/recognition-services.example.json',
                     'config/docling-worker.example.json', 'requirements-web.in',
                     'docs/upgrade/runtime-locks/agent.txt',
                     'docs/upgrade/runtime-licenses/agent/package_LICENSE',
                     'docs/design/20261004-Web订单工作流-设计与状态.md',
                     'docs/product/KANPACE-历次需求与功能总账-20261004.md',
                     'tests/test_recognition_xlsx.py', 'tests/test_recognition_pdfium_frames.py'):
            self.assertTrue(delivery.allowed(Path(name)), name)
        for name in ('outputs/order/report.json', 'work/uploads/order.pdf', 'data/orders.json',
                     'config/recognition-services.json', 'tools/project-render-selection.json',
                     'static/studies/taiwan-jewelry/study.json',
                     'static/studies/taiwan-jewelry/source-inventory.json',
                     'static/studies/taiwan-jewelry/sources/order.pdf',
                     'static/studies/taiwan-jewelry/images/order.png',
                     'tests/accidental.sqlite3-wal', 'static/.env.local',
                     'firmware/goldenmorning-display/src/main.cpp',
                     'tests/test_badge_images_firmware.py'):
            self.assertFalse(delivery.allowed(Path(name)), name)
        self.assertTrue(delivery.allowed(Path('firmware/goldenmorning-display/src/main.cpp'),
                                         'software-and-historical-firmware'))

    def test_new_product_and_engineering_docs_are_allowlisted(self):
        for name in (
            'docs/product/KANPACE-软件端与硬件端流程图.md',
            'docs/product/KANPACE-产品说明-精简版.md',
            'docs/engineering/真实自动拆图算法.md',
            'docs/engineering/队友出图流程接入说明.md',
        ):
            self.assertTrue(delivery.allowed(Path(name)), name)
        self.assertFalse(delivery.allowed(Path('docs/engineering/customer-export.pdf')))

    def test_staging_scrubs_document_links_and_json_provenance(self):
        with TemporaryDirectory() as temporary:
            stage = Path(temporary)
            def put(name, content):
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
            home_path = '/' + 'Users/tester/private/source.pdf'
            volume_path = '/' + 'Volumes/Factory/private/source.pdf'
            put('DELIVERY.md', '# Release\n')
            put('README.md', '# Current Web\npython3 app.py --port 8788\n')
            put('static/brand/provenance.json', json.dumps({'manual': home_path, 'assets': []}))
            put('static/studies/taiwan-jewelry/index.html', '<title>台湾珠宝柜 · 图纸分工样例</title>')
            put('firmware/goldenmorning-display/dist/manifest.json', json.dumps({'version': 'test'}))
            put('licenses/optimization/sources.json', json.dumps({'source_dir': home_path, 'repository': 'https://example.com/repo'}))
            put('docs/example.md', f'[现场材料]({home_path})\n{{"source_path": "{volume_path}", "page": 2}}\n')
            put('docs/upgrade/provenance.md', f'`{home_path}`\n[Old chat](codex://threads/test-id)\n')
            put('docs/upgrade/runtime-locks/pip.json', json.dumps({'nested': [{'path': home_path}], 'license': 'MIT'}))

            changes = delivery.stage_templates(stage)
            self.assertTrue(any(row['path'] == 'docs/example.md' for row in changes))
            self.assertTrue(any(row['path'] == 'licenses/optimization/sources.json' for row in changes))
            self.assertIn('原机资料另存', (stage / 'docs/example.md').read_text())
            self.assertIn('<由所属工厂填写原文件>', (stage / 'docs/example.md').read_text())
            self.assertEqual(json.loads((stage / 'licenses/optimization/sources.json').read_text())['source_dir'], '原机路径已移除')
            self.assertIn('Current Web', (stage / 'README.md').read_text())
            self.assertNotIn('codex://', (stage / 'docs/upgrade/provenance.md').read_text())
            self.assertEqual(json.loads((stage / 'docs/upgrade/runtime-locks/pip.json').read_text())['license'], 'MIT')
            self.assertEqual(json.loads((stage / 'static/studies/taiwan-jewelry/source-inventory.json').read_text())['sources'], [])
            self.assertEqual(delivery.assert_portable_stage(stage), [])

    def test_archive_verification_checks_all_members_and_hashes(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            stage = folder / 'stage'
            stage.mkdir()
            source = stage / 'app.py'
            source.write_text('print("synthetic")\n')
            manifest = {'files': [{'path': 'app.py', 'bytes': source.stat().st_size,
                                    'sha256': delivery.sha(source)}]}
            (stage / 'RELEASE-MANIFEST.json').write_text(json.dumps(manifest))
            (stage / 'SHA256SUMS.txt').write_text(''.join(delivery.sha(p) + '  ' + p.name + '\n'
                                                      for p in sorted(stage.iterdir())))
            archive = folder / 'release.zip'
            def archive_stage(extra=False, mutated=False):
                with zipfile.ZipFile(archive, 'w') as bundle:
                    for path in sorted(stage.iterdir()):
                        data = b'changed' if mutated and path.name == 'app.py' else path.read_bytes()
                        bundle.writestr('KANPACE/' + path.name, data)
                    if extra:
                        bundle.writestr('KANPACE/private-order.json', '{}')
            archive_stage()
            self.assertEqual(delivery.verify_archive(archive, stage)['zip_member_sha256'], 'passed')
            archive_stage(extra=True)
            with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                delivery.verify_archive(archive, stage)
            archive_stage(mutated=True)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                delivery.verify_archive(archive, stage)

    def test_inventory_prunes_private_runtime_and_snapshot_detects_changes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app.py').write_text('pass\n')
            (root / 'work').mkdir()
            (root / 'work/private.json').write_text('{}')
            (root / 'outputs').mkdir()
            (root / 'outputs/private.json').write_text('{}')
            (root / 'linked.py').symlink_to(root / 'work/private.json')
            with patch.object(delivery, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'linked source file'):
                    list(delivery.inventory())
                (root / 'linked.py').unlink()
                self.assertEqual([rel.as_posix() for _, rel in delivery.inventory()], ['app.py'])
                records = [{'path': 'app.py', 'source_sha256': delivery.sha(root / 'app.py')}]
                delivery.assert_source_snapshot(records)
                (root / 'app.py').write_text('changed\n')
                with self.assertRaisesRegex(ValueError, 'Source changed'):
                    delivery.assert_source_snapshot(records)

    def test_unreviewed_host_path_fails_closed_without_printing_path(self):
        with TemporaryDirectory() as temporary:
            stage = Path(temporary)
            path = stage / 'docs/example.md'
            path.parent.mkdir(parents=True)
            path.write_text('private=' + '/' + 'Volumes/Factory/secret-order.pdf')
            with self.assertRaisesRegex(ValueError, 'docs/example.md') as raised:
                delivery.assert_portable_stage(stage)
            self.assertNotIn('secret-order', str(raised.exception))
            path.write_text('attachment=' + '/' + 'private/var' + '/folders/session/screenshot.png')
            with self.assertRaises(ValueError):
                delivery.assert_portable_stage(stage)

    def test_embedded_build_path_exception_is_digest_pinned(self):
        with TemporaryDirectory() as temporary:
            stage = Path(temporary)
            path = stage / 'vendor/build.wasm'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'fixture/' + b'Users/tester/build')
            approved = {'vendor/build.wasm': delivery.sha(path)}
            self.assertEqual(delivery.assert_portable_stage(stage, approved), ['vendor/build.wasm'])
            path.write_bytes(path.read_bytes() + b'-changed')
            with self.assertRaises(ValueError):
                delivery.assert_portable_stage(stage, approved)


if __name__ == '__main__':
    unittest.main()
