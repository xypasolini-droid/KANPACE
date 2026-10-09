"""HTTP envelope: validation, authorization boundary and response policy."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlsplit
import access_control
import factory_instances
from kanpace.core.constants import MAX_BODY
from kanpace.core.errors import APIError


class RequestHandlerBase(BaseHTTPRequestHandler):
    server_version = 'KANPACE/1.0'

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt % args))

    def send_bytes(self, status, body, content_type='application/json; charset=utf-8', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        page_url = urlsplit(self.path)
        embedded_viewer = (content_type.startswith('text/html')
                           and page_url.path in ('/model/index.html', '/project-3d/index.html')
                           and parse_qs(page_url.query).get('embed') == ['1'])
        self.send_header('X-Frame-Options', 'SAMEORIGIN' if embedded_viewer else 'DENY')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'same-origin')
        if content_type.startswith('text/html'):
            model_page = urlsplit(self.path).path == '/model/index.html'
            scripts = "'self' 'unsafe-inline'" + (" 'wasm-unsafe-eval'" if model_page else '')
            ancestors = "'self'" if embedded_viewer else "'none'"
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src " + scripts + "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors " + ancestors)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json_response(self, data, status=200):
        data = access_control.filter_response(self, data)
        self.send_bytes(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def error_response(self, exc):
        payload = {'error': exc.message}
        if exc.details is not None:
            payload['details'] = exc.details
        self.json_response(payload, exc.status)

    def validate_host(self):
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        try:
            target = urlsplit(self.path)
        except ValueError as exc:
            raise APIError(403, '请求地址无效') from exc
        if len(hosts) != 1 or len(origins) > 1 or target.scheme or target.netloc:
            raise APIError(403, '请求 Host/Origin 无效')
        host = hosts[0]
        web_origin = getattr(self.server, 'public_origin', None)
        allowed = ({urlsplit(web_origin).netloc} if web_origin else
                   {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)})
        if host not in allowed:
            raise APIError(403, '仅允许通过配置的 Web 域名访问' if web_origin else '仅允许通过本机地址访问')
        authenticated = access_control.authentication_enabled(self.server.store)
        if web_origin and not authenticated:
            raise APIError(503, 'Web 认证配置不可用；服务拒绝访问')
        if web_origin or getattr(self.server.store,'instance_id',None) or authenticated:
            origin=origins[0] if origins else None
            expected_origin = web_origin or 'http://' + host
            if origin is not None and origin != expected_origin:
                raise APIError(403,'拒绝其他工厂来源的请求')
            navigation=(self.headers.get('Sec-Fetch-Mode')=='navigate' and self.headers.get('Sec-Fetch-Dest')=='document' and factory_instances.static_allowed(unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'))
            if self.headers.get('Sec-Fetch-Site') in ('cross-site','same-site') and not navigation:raise APIError(403,'请在当前工厂页面打开资料')
        return host

    def validate_mutation(self):
        host = self.validate_host()
        if self.headers.get('Transfer-Encoding'):
            raise APIError(400, '不支持分块请求')
        origin = self.headers.get('Origin')
        web_origin = getattr(self.server, 'public_origin', None)
        if (web_origin and origin != web_origin) or (origin is not None and origin != (web_origin or 'http://' + host)):
            raise APIError(403, '拒绝跨站写入请求')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise APIError(403, '拒绝跨站写入请求')
        if self.headers.get_content_type() != 'application/json':
            raise APIError(415, '写入请求必须使用 application/json')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise APIError(400, '无效请求长度')
        if size <= 0 or size > MAX_BODY:
            raise APIError(413, '请求为空或超过上传限制')
        try:
            data = json.loads(self.rfile.read(size), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, 'JSON 内容无效')
        if not isinstance(data, dict):
            raise APIError(400, 'JSON 顶层必须为对象')
        return data

    def do_OPTIONS(self):
        self.json_response({'error': '跨站请求不可用'}, 403)
