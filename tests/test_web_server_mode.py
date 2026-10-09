"""Real HTTP tests for explicit TLS-proxy origin and fail-closed Web startup."""
from contextlib import contextmanager
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kanpace.application.store import Store
from kanpace.http.server import Server, parse_public_origin
from kanpace import bootstrap


class OriginConfigurationTests(unittest.TestCase):
    def test_single_https_origin_is_normalized(self):
        self.assertIsNone(parse_public_origin(None))
        self.assertEqual(parse_public_origin('https://Kanpace.Example.com:8443'), 'https://kanpace.example.com:8443')
        self.assertEqual(parse_public_origin('https://[2001:db8::1]:8443'), 'https://[2001:db8::1]:8443')

    def test_ambiguous_or_unsafe_origins_are_rejected(self):
        values = ['', 'http://kanpace.example.com', 'https://user@kanpace.example.com',
                  'https://user:pass@kanpace.example.com', 'https://kanpace.example.com/',
                  'https://kanpace.example.com/path', 'https://kanpace.example.com?x=1',
                  'https://kanpace.example.com#fragment', 'https://kanpace.example.com?',
                  'https://kanpace.example.com#', 'https://one.example,other.example',
                  'https://one.example https://other.example', 'https://*.example.com',
                  'https://kanpace.example.com:', 'https://kanpace.example.com:0',
                  'https://kanpace.example.com:65536', 'https://bad_.example.com',
                  'https://one.example\\@other.example', 'https://one%2eexample.com']
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_public_origin(value)


class WebServerHTTPTests(unittest.TestCase):
    origin = 'https://kanpace.example.test'
    password = 'local-bootstrap-test-password'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name, seed=False)

    @contextmanager
    def running(self, public_origin=None):
        server = Server(('127.0.0.1', 0), self.store, public_origin=public_origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def request(self, server, path='/api/state', *, data=None, host=None, origin=None, cookie=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        request_headers = {'Host': host or '127.0.0.1:' + str(server.server_port)}
        if origin is not None:
            request_headers['Origin'] = origin
        if cookie:
            request_headers['Cookie'] = cookie.split(';', 1)[0]
        request_headers.update(headers or {})
        content = None if data is None else json.dumps(data).encode()
        if content is not None:
            request_headers['Content-Type'] = 'application/json'
        connection.request('GET' if data is None else 'POST', path, content, request_headers)
        response = connection.getresponse()
        body = response.read()
        result = json.loads(body) if response.getheader('Content-Type', '').startswith('application/json') else body
        result_headers = dict(response.getheaders())
        connection.close()
        return response.status, result, result_headers

    def setup_admin(self):
        with self.running() as server:
            status, body, headers = self.request(server, '/api/access/setup',
                data={'username': 'qa_admin', 'name': 'Web 管理员', 'password': self.password})
            self.assertEqual(status, 200, body)
            return headers['Set-Cookie']

    def web_request(self, server, path='/api/state', **kwargs):
        return self.request(server, path, host='kanpace.example.test', **kwargs)

    def test_default_loopback_preserves_local_and_cookie_behavior(self):
        with self.running() as server:
            self.assertIsNone(server.public_origin)
            self.assertIsNone(self.store.web_origin)
            self.assertEqual(self.request(server)[0], 200)
            self.assertEqual(self.request(server, host='evil.example')[0], 403)
        cookie = self.setup_admin()
        with self.running() as server:
            self.assertEqual(self.request(server)[0], 401)
            self.assertEqual(self.request(server, cookie=cookie)[0], 200)
            self.assertEqual(self.request(server, data={}, path='/api/access/logout', cookie=cookie)[0], 200)

    def test_public_mode_refuses_anonymous_or_incomplete_startup(self):
        for listen, origin in [('0.0.0.0', None), ('0.0.0.0', self.origin), ('127.0.0.1', self.origin)]:
            with self.subTest(listen=listen), self.assertRaises(ValueError):
                Server((listen, 0), self.store, public_origin=origin)
        self.setup_admin()
        with self.store.write_transaction() as con:
            admin = self.store.all(con, 'access_users')[0]
            admin['active'] = False
            self.store.put(con, 'access_users', admin)
        with self.assertRaises(ValueError):
            Server(('127.0.0.1', 0), self.store, public_origin=self.origin)

    def test_public_listen_requires_initialized_auth_and_explicit_origin(self):
        self.setup_admin()
        server = Server(('0.0.0.0', 0), self.store, public_origin=self.origin)
        self.addCleanup(server.server_close)
        self.assertTrue(server.web_mode)
        self.assertEqual(server.server_address[0], '0.0.0.0')
        with self.assertRaises(ValueError):
            Server(('192.0.2.1', 0), self.store, public_origin=self.origin)

    def test_web_host_auth_and_existing_session_are_checked(self):
        old_cookie = self.setup_admin()
        with self.running(self.origin) as server:
            self.assertEqual(server.public_origin, self.origin)
            self.assertEqual(self.store.web_origin, self.origin)
            self.assertEqual(self.web_request(server)[0], 401)
            self.assertEqual(self.web_request(server, cookie=old_cookie)[0], 200)
            for host in ('127.0.0.1:' + str(server.server_port), 'evil.example',
                         'other.example.test', 'kanpace.example.test:443'):
                with self.subTest(host=host):
                    self.assertEqual(self.request(server, host=host, cookie=old_cookie)[0], 403)
            status, body, headers = self.web_request(server, '/api/access/login',
                origin=self.origin, data={'username': 'qa_admin', 'password': self.password})
            self.assertEqual(status, 200, body)
            self.assertEqual(headers['Set-Cookie'].split('=', 1)[0], old_cookie.split('=', 1)[0])
            self.assertEqual(self.web_request(server, cookie=headers['Set-Cookie'])[0], 200)

    def test_web_mutations_require_exact_origin_and_ignore_forwarded_headers(self):
        cookie = self.setup_admin()
        with self.running(self.origin) as server:
            body = {'name': '合法 Web 项目', 'quantity': 1}
            for origin in (None, 'null', 'http://kanpace.example.test',
                           'https://evil.example.test', self.origin + '/', self.origin + ':443'):
                with self.subTest(origin=origin):
                    self.assertEqual(self.web_request(server, '/api/projects', cookie=cookie, origin=origin,
                        data=body, headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'kanpace.example.test'})[0], 403)
            status, result, _ = self.web_request(server, '/api/projects', cookie=cookie,
                                                 origin=self.origin, data=body)
            self.assertEqual(status, 200, result)
            self.assertEqual(self.request(server, host='evil.example.test', cookie=cookie,
                headers={'X-Forwarded-Host': 'kanpace.example.test', 'X-Forwarded-Proto': 'https'})[0], 403)

    def test_sensitive_cross_site_gets_fail_and_static_navigation_can_open_login(self):
        cookie = self.setup_admin()
        with self.running(self.origin) as server:
            for site in ('cross-site', 'same-site'):
                for path in ('/api/state', '/api/recognition-status', '/api/access'):
                    with self.subTest(site=site, path=path):
                        self.assertEqual(self.web_request(server, path, cookie=cookie,
                            headers={'Sec-Fetch-Site': site, 'Sec-Fetch-Mode': 'navigate',
                                     'Sec-Fetch-Dest': 'document'})[0], 403)
            self.assertEqual(self.web_request(server, cookie=cookie, origin='https://other.example.test')[0], 403)
            self.assertEqual(self.web_request(server, '/', headers={'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'})[0], 200)

    def test_web_auth_disabled_after_start_cannot_fall_back_to_anonymous(self):
        self.setup_admin()
        with self.running(self.origin) as server:
            with self.store.write_transaction() as con:
                config = self.store.all(con, 'access_config')[0]
                config['enabled'] = False
                self.store.put(con, 'access_config', config)
            self.assertEqual(self.web_request(server)[0], 503)

    def test_duplicate_host_headers_are_rejected(self):
        self.setup_admin()
        with self.running(self.origin) as server:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.putrequest('GET', '/api/state', skip_host=True)
            connection.putheader('Host', 'kanpace.example.test')
            connection.putheader('Host', 'evil.example.test')
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()

    def test_duplicate_origins_and_absolute_proxy_targets_are_rejected(self):
        self.setup_admin()
        with self.running(self.origin) as server:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.putrequest('GET', '/api/access', skip_host=True)
            connection.putheader('Host', 'kanpace.example.test')
            connection.putheader('Origin', self.origin)
            connection.putheader('Origin', 'https://evil.example.test')
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
            self.assertEqual(self.web_request(server, 'https://evil.example.test/api/access')[0], 403)


class WebModeCLITests(unittest.TestCase):
    def test_cli_environment_origin_and_default_loopback_are_passed_to_server(self):
        server = unittest.mock.Mock()
        store = unittest.mock.Mock(data_dir=Path('/tmp/cli-test'))
        with patch.dict(os.environ, {'KANPACE_PUBLIC_ORIGIN': 'https://kanpace.example.test'}), \
             patch.object(sys, 'argv', ['app.py', '--no-demo']), \
             patch.object(bootstrap, 'Store', return_value=store), \
             patch.object(bootstrap, 'Server', return_value=server) as constructor, \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.main()
        constructor.assert_called_once_with(('127.0.0.1', 8765), store, public_origin='https://kanpace.example.test')
        server.server_close.assert_called_once()

    def test_cli_rejects_public_listen_without_origin_before_creating_store(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, 'argv', ['app.py', '--listen', '0.0.0.0']), \
             patch.object(bootstrap, 'Store') as store, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                bootstrap.main()
        self.assertEqual(caught.exception.code, 2)
        store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
