"""CLI integration talks to a temporary real HTTP server, never local live data."""
from contextlib import contextmanager
import http.server
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import kanpace_cli as cli


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = app.Store(self.root / 'data', seed=False)
        self.server = app.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.source = self.root / '测试订单.csv'
        self.source.write_text('订单号,项目,类型\nEX-001,CLI真实测试,cabinet\n', encoding='utf-8-sig')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def run_cli(self, *args, base=None, prefix=None):
        out, error = io.StringIO(), io.StringIO()
        code = cli.run(['--base-url', base or self.base] + list(prefix or []) + list(args), stdout=out, stderr=error)
        return code, json.loads(out.getvalue()) if out.getvalue() else None, error.getvalue()

    def preview(self):
        return self.run_cli('preview', '--file', str(self.source), '--entity', 'projects', '--source-system', 'CLI测试',
                            '--mapping-json', '{"external_key":"订单号","name":"项目","factory_type":"类型"}')

    def test_header_preview_apply_and_export_real_http(self):
        before = self.source.read_bytes()
        code, headers, error = self.run_cli('preview', '--file', str(self.source), '--entity', 'projects')
        self.assertEqual(code, 0, error)
        self.assertIsNone(headers['preview'])
        self.assertEqual(headers['headers'], ['订单号', '项目', '类型'])
        code, body, error = self.preview()
        self.assertEqual(code, 0, error)
        preview = body['preview']
        with self.store.connect() as con:
            self.assertEqual(self.store.all(con, 'projects'), [])
        code, applied, error = self.run_cli('apply', '--preview-id', preview['id'], '--version', str(preview['version']))
        self.assertEqual(code, 0, error)
        self.assertEqual(applied['receipt']['results'][0]['result'], '已应用')
        code, repeated, error = self.run_cli('apply', '--preview-id', preview['id'], '--version', str(preview['version']))
        self.assertTrue(repeated['duplicate'])
        output = self.root / 'CLI回执.xlsx'
        code, exported, error = self.run_cli('export', '--entity', 'projects', '--format', 'xlsx', '--preview-id', preview['id'], '--output', str(output))
        self.assertEqual(code, 0, error)
        self.assertTrue(output.read_bytes().startswith(b'PK'))
        self.assertEqual(exported['output'], str(output.resolve()))
        self.assertEqual(self.source.read_bytes(), before)

    def test_mapping_file_and_existing_output_not_overwritten(self):
        mapping = self.root / '映射.json'
        mapping.write_text('{"external_key":"订单号","name":"项目","factory_type":"类型"}', encoding='utf-8')
        code, body, error = self.run_cli('preview', '--file', str(self.source), '--entity', 'projects', '--mapping-json', '@' + str(mapping))
        self.assertEqual(code, 0, error)
        self.assertEqual(body['preview']['summary']['create'], 1)
        output = self.root / '用户原文件.csv'; output.write_text('keep-me', encoding='utf-8')
        code, _, error = self.run_cli('export', '--entity', 'projects', '--format', 'csv', '--output', str(output))
        self.assertEqual(code, 1)
        self.assertIn('已存在', error)
        self.assertEqual(output.read_text(), 'keep-me')

    def test_remote_url_userinfo_and_paths_rejected_without_network(self):
        for address in ('https://example.com', 'http://192.168.1.8:8765', 'http://127.0.0.1@evil.test',
                        'http://127.0.0.1:8765/path', 'http://localhost:8765?token=secret'):
            with self.assertRaises(cli.CLIError): cli.base_url(address)
        self.assertEqual(cli.base_url('http://[::1]:8765/'), 'http://[::1]:8765')

    def test_cli_does_not_bypass_authentication_and_accepts_cookie_file(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.headers.get('Cookie') != 'test_session=synthetic_cookie':
                    self.send_response(403); self.end_headers(); self.wfile.write(b'{"error":"Forbidden"}')
                    return
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(b'{"authenticated":true}')
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            code, _, error = self.run_cli('apply', '--preview-id', 'preview', '--version', '1', base=base)
            self.assertEqual(code, 1)
            self.assertIn('接口拒绝访问', error)
            cookie = self.root / 'test-cookies.txt'
            cookie.write_text('# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\ttest_session\tsynthetic_cookie\n')
            code, body, error = self.run_cli('apply', '--preview-id', 'preview', '--version', '1', base=base, prefix=['--cookie-file', str(cookie)])
            self.assertEqual(code, 0, error)
            self.assertTrue(body['authenticated'])
            self.assertNotIn('synthetic_cookie', error)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_redirects_cannot_send_request_to_remote_host(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(302); self.send_header('Location', 'https://example.com/steal'); self.end_headers()
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            code, _, error = self.run_cli('apply', '--preview-id', 'preview', '--version', '1',
                                          base='http://127.0.0.1:' + str(server.server_port))
            self.assertEqual(code, 1)
            self.assertIn('重定向', error)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
