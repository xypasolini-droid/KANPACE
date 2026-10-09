"""Local launchd contract tests; all service/browser/HTTP calls are mocked."""
import contextlib
import io
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_service as service
import launch


def result(code=0, stderr=''):
    return SimpleNamespace(returncode=code, stdout='', stderr=stderr)


class LocalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='KANPACE 测试 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / '中文 项目'
        self.base.mkdir()
        self.base = self.base.resolve()
        self.platform = patch.object(service.sys, 'platform', 'darwin')
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_definition_preserves_absolute_space_and_unicode_paths_and_venv(self):
        python = self.base / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        config = service.definition(self.base)
        self.assertEqual(config['ProgramArguments'], [str(python), '-u', str(self.base / 'app.py'), '--port', '8765', '--data-dir', str(self.base / 'data')])
        self.assertEqual(config['WorkingDirectory'], str(self.base))
        self.assertTrue(config['KeepAlive'])
        self.assertTrue(config['RunAtLoad'])
        self.assertEqual(config['ThrottleInterval'], 5)
        self.assertTrue(config['StandardErrorPath'].endswith('/data/logs/server-error.log'))
        self.assertIn('/opt/homebrew/bin', config['EnvironmentVariables']['PATH'])
        self.assertTrue(config['Label'].startswith('com.xiongyi.cabinet-flow.'))

    def test_fallback_interpreter_and_label_are_stable_per_resolved_directory(self):
        with patch.object(service.sys, 'executable', '/tmp/Python Runtime/python3'):
            self.assertEqual(service.definition(self.base)['ProgramArguments'][0], str(Path('/tmp/Python Runtime/python3').resolve()))
        alias = self.base / '..' / self.base.name
        self.assertEqual(service.label(self.base), service.label(alias))
        self.assertNotEqual(service.label(self.base), service.label(self.base / 'other'))

    def test_first_and_repeated_start_do_not_duplicate_bootstrap_or_kill_process(self):
        with patch.object(service, 'launchctl', side_effect=[result(1), result(), result(), result()]) as ctl:
            job = service.ensure_started(self.base)
            self.assertEqual(service.ensure_started(self.base), job)
        calls = [c.args for c in ctl.call_args_list]
        self.assertEqual([c[0] for c in calls], ['print', 'bootstrap', 'print', 'kickstart'])
        self.assertEqual(calls[-1], ('kickstart', job))
        self.assertNotIn('-k', calls[-1])
        path = Path(calls[1][2])
        self.assertEqual(path.parent, self.base / 'data/service')
        self.assertEqual(plistlib.loads(path.read_bytes()), service.definition(self.base))
        self.assertFalse(list(path.parent.glob('*.tmp')))
        self.assertTrue((self.base / 'data/logs').is_dir())
        self.assertNotIn('Library/LaunchAgents', str(path))

    def test_concurrent_starts_use_distinct_atomic_temporary_files(self):
        barrier = threading.Barrier(2)
        temporary_paths = []
        replace = Path.replace
        def synchronized_replace(path, destination):
            temporary_paths.append(path)
            barrier.wait(timeout=5)
            return replace(path, destination)
        with patch.object(service, 'launchctl', side_effect=lambda *args: result(1 if args[0] == 'print' else 0)), patch.object(Path, 'replace', synchronized_replace):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = list(pool.map(lambda _: service.ensure_started(self.base), range(2)))
        self.assertEqual(jobs[0], jobs[1])
        self.assertEqual(len(set(temporary_paths)), 2)
        path = self.base / 'data/service' / (service.label(self.base) + '.plist')
        self.assertEqual(plistlib.loads(path.read_bytes())['Label'], service.label(self.base))
        self.assertFalse(list(path.parent.glob('*.tmp')))

    def test_bootstrap_race_accepts_job_loaded_by_another_process(self):
        with patch.object(service, 'launchctl', side_effect=[result(1), result(5, 'already loaded'), result()]):
            self.assertEqual(service.ensure_started(self.base), service.target(self.base))

    def test_bootstrap_failure_is_reported(self):
        with patch.object(service, 'launchctl', side_effect=[result(1), result(5, 'bootstrap denied'), result(1)]):
            with self.assertRaisesRegex(RuntimeError, 'bootstrap denied'):
                service.ensure_started(self.base)

    def test_kickstart_failure_is_reported(self):
        with patch.object(service, 'launchctl', side_effect=[result(), result(5, 'kickstart denied')]):
            with self.assertRaisesRegex(RuntimeError, 'kickstart denied'):
                service.ensure_started(self.base)

    def test_bootout_finishing_between_print_and_kickstart_recreates_job(self):
        with patch.object(service, 'launchctl', side_effect=[result(), result(113, 'Could not find service "KANPACE"'), result()]) as ctl:
            self.assertEqual(service.ensure_started(self.base), service.target(self.base))
        self.assertEqual([call.args[0] for call in ctl.call_args_list], ['print', 'kickstart', 'bootstrap'])

    def test_stop_boots_out_job_without_touching_data(self):
        document = self.base / 'order.json'
        document.write_text('preserved')
        with patch.object(service, 'launchctl', side_effect=[result(), result()]) as ctl:
            self.assertTrue(service.stop(self.base))
        self.assertEqual(ctl.call_args_list[-1].args, ('bootout', service.target(self.base)))
        self.assertEqual(document.read_text(), 'preserved')

    def test_stop_absent_job_does_not_bootout(self):
        with patch.object(service, 'launchctl', return_value=result(1)) as ctl:
            self.assertFalse(service.stop(self.base))
        ctl.assert_called_once_with('print', service.target(self.base))

    def test_stop_failure_is_reported(self):
        with patch.object(service, 'launchctl', side_effect=[result(), result(5, 'bootout denied')]):
            with self.assertRaisesRegex(RuntimeError, 'bootout denied'):
                service.stop(self.base)

    def test_non_mac_management_rejected_before_subprocess(self):
        with patch.object(service.sys, 'platform', 'linux'), patch.object(service, 'launchctl') as ctl:
            for operation in [service.ensure_started, service.stop]:
                with self.assertRaisesRegex(RuntimeError, 'macOS'):
                    operation(self.base)
            with patch.object(sys, 'argv', ['local_service.py', 'status']), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(service.main(), 1)
            ctl.assert_not_called()

    def test_launchctl_uses_argument_array_and_bounded_timeout(self):
        with patch.object(service.subprocess, 'run', return_value=result()) as run:
            service.launchctl('bootstrap', 'gui/501', '/tmp/中文 space/app.plist')
        run.assert_called_once_with(['/bin/launchctl', 'bootstrap', 'gui/501', '/tmp/中文 space/app.plist'], capture_output=True, text=True, timeout=15)

    def test_health_accepts_only_expected_payload_without_real_network(self):
        payloads = [(b'{"ok":true,"mode":"local_single_workstation"}', True), (b'{"ok":true,"mode":"other"}', False), (b'[]', False), (b'<html>error</html>', False)]
        for payload, expected in payloads:
            with self.subTest(payload=payload), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as opener:
                self.assertEqual(service.ready(), expected)
                opener.assert_called_once_with('http://127.0.0.1:8765/api/health', timeout=0.5)
        with patch.object(service.urllib.request, 'urlopen', side_effect=OSError('refused')):
            self.assertFalse(service.ready())

    def test_start_cli_does_not_claim_running_before_health_ready(self):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['local_service.py', 'start']), patch.object(service, 'ensure_started'), patch.object(service, 'wait_until_ready', return_value=False), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.assertEqual(service.main(), 1)
        self.assertNotIn('本地服务已启动', output.getvalue())
        self.assertIn('Web 暂未就绪', error.getvalue())

    def test_loaded_but_unhealthy_status_returns_failure(self):
        with patch.object(sys, 'argv', ['local_service.py', 'status']), patch.object(service, 'launchctl', return_value=result()), patch.object(service, 'ready', return_value=False), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(service.main(), 1)
        self.assertIn('已加载', output.getvalue())

    def test_wait_until_ready_has_timeout_and_success_paths(self):
        with patch.object(service, 'ready', side_effect=[False, True]), patch.object(service.time, 'sleep'):
            self.assertTrue(service.wait_until_ready())
        with patch.object(service, 'ready', return_value=False), patch.object(service.time, 'monotonic', side_effect=[0, 11]), patch.object(service.time, 'sleep') as sleep:
            self.assertFalse(service.wait_until_ready(timeout=10))
            sleep.assert_not_called()

    def test_launcher_uses_existing_service_without_starting_or_opening_new_process(self):
        with patch.object(launch, 'ready', return_value=True), patch.object(service, 'ensure_started') as start, patch.object(launch.subprocess, 'Popen') as popen, patch.object(launch.webbrowser, 'open') as browser, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch.main(), 0)
        start.assert_not_called()
        popen.assert_not_called()
        browser.assert_called_once_with(launch.URL)

    def test_mac_launcher_waits_for_health_before_opening_browser(self):
        with patch.object(launch, 'ready', side_effect=[False, False, True]), patch.object(service, 'ensure_started') as start, patch.object(launch.subprocess, 'Popen') as popen, patch.object(launch.time, 'sleep'), patch.object(launch.webbrowser, 'open') as browser, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch.main(), 0)
        start.assert_called_once_with()
        popen.assert_not_called()
        browser.assert_called_once_with(launch.URL)

    def test_mac_launcher_reports_unhealthy_loaded_service_without_opening_browser(self):
        with patch.object(launch, 'ready', return_value=False), patch.object(service, 'ensure_started'), patch.object(launch.time, 'sleep'), patch.object(launch.webbrowser, 'open') as browser, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launch.main(), 1)
        browser.assert_not_called()
        self.assertIn('暂未就绪', output.getvalue())


if __name__ == '__main__':
    unittest.main()
