"""Fault-injection regression for probe timeouts, persistence and private logs.

Actual native imports and geometry/OCR are exercised separately in
test_engineering_engines.py; these tests force failures without waiting 40s.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import engineering_engines as engines


class EngineeringStatusTests(unittest.TestCase):
    def setUp(self):
        engines._PROBES.clear()
        self.tmp = tempfile.TemporaryDirectory(prefix='kanpace-probe-regression-')
        self.root = Path(self.tmp.name)
        self.python = self.root / 'runtime/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b'synthetic-runtime-marker')
        self.factory = self.root / 'factory'
        self.jobs = engines.EngineeringJobs(self.factory, python_path=self.python)
        self.versions = {name: 'fixture-version' for name in engines.PROBE_PACKAGES}

    def tearDown(self):
        engines._PROBES.clear()
        self.tmp.cleanup()

    def test_timeout_preserves_completed_cad_and_keeps_stderr_private(self):
        error = subprocess.TimeoutExpired(['synthetic-probe'], 40,
                 output=b'{"cadquery-ocp":"fixture-cad"}\n', stderr=b'private loader diagnostic')
        with patch.object(engines.subprocess, 'run', side_effect=error):
            result = self.jobs.status()
        self.assertTrue(result['cad']['ready'])
        self.assertFalse(result['ocr']['ready'])
        self.assertEqual(result['probe']['state'], 'timeout')
        self.assertNotIn('private loader diagnostic', json.dumps(result))
        directory = self.jobs.directory / '_probe'
        self.assertFalse((directory / 'health.json').exists())
        log = json.loads((directory / 'probe-log.json').read_text())
        self.assertEqual(log['stderr'], 'private loader diagnostic')
        self.assertEqual((directory / 'probe-log.json').stat().st_mode & 0o777, 0o600)

    def test_success_record_reused_until_runtime_fingerprint_changes(self):
        response = subprocess.CompletedProcess([], 0, json.dumps(self.versions) + '\n', '')
        with patch.object(engines.subprocess, 'run', return_value=response) as native:
            first = self.jobs.status()
            self.assertEqual(native.call_count, 1)
            self.assertFalse(first['probe']['cached'])
            engines._PROBES.clear()
            second = engines.EngineeringJobs(self.factory, python_path=self.python).status()
            self.assertEqual(native.call_count, 1)
            self.assertTrue(second['probe']['cached'])
            self.python.write_bytes(b'changed-runtime-must-revalidate')
            third = self.jobs.status()
            self.assertEqual(native.call_count, 2)
            self.assertFalse(third['probe']['cached'])

    def test_failure_cache_expires_after_five_seconds(self):
        response = subprocess.CompletedProcess([], 1, '', 'synthetic import failure')
        with patch.object(engines.subprocess, 'run', return_value=response) as native:
            with patch.object(engines.time, 'monotonic', return_value=100):
                self.jobs.status()
            with patch.object(engines.time, 'monotonic', return_value=104):
                self.jobs.status()
            self.assertEqual(native.call_count, 1)
            with patch.object(engines.time, 'monotonic', return_value=106):
                self.jobs.status()
            self.assertEqual(native.call_count, 2)

    def test_malformed_saved_versions_do_not_crash_status(self):
        directory = self.jobs.directory / '_probe'
        directory.mkdir()
        fingerprint = engines._probe_fingerprint(self.python, self.jobs.models, engines._environment(directory))
        (directory / 'health.json').write_text(json.dumps({
            'fingerprint': fingerprint, 'checked_epoch': engines.time.time(), 'versions': []}))
        response = subprocess.CompletedProcess([], 0, json.dumps(self.versions), '')
        with patch.object(engines.subprocess, 'run', return_value=response) as native:
            result = self.jobs.status()
        self.assertEqual(native.call_count, 1)
        self.assertEqual(result['probe']['state'], 'verified')

    def test_parallel_status_does_not_start_another_native_probe(self):
        engines._PROBE_LOCK.acquire()
        try:
            with patch.object(engines.subprocess, 'run') as native:
                result = self.jobs.status()
            native.assert_not_called()
            self.assertEqual(result['probe']['state'], 'running')
        finally:
            engines._PROBE_LOCK.release()


if __name__ == '__main__':
    unittest.main()
