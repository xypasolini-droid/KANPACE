"""Threaded local server composition; business logic lives in application services."""
from __future__ import annotations

from pathlib import Path
from http.server import ThreadingHTTPServer
import ipaddress
import re
from urllib.parse import urlsplit
import factory_instances
from device_bridge import DeviceBridge
from kanpace.core.constants import BASE
from kanpace.http.base import RequestHandlerBase
from kanpace.http.queries import QueryRoutes
from kanpace.http.commands import CommandRoutes
from kanpace.http.exports import ProjectExports
from kanpace.application.project_dispatch import ProjectDispatchCoordinator


class Handler(QueryRoutes, CommandRoutes, ProjectExports, RequestHandlerBase):
    """Compose the stable request boundary with read, write and export routes."""


def parse_public_origin(value):
    """One explicit HTTPS origin; forwarded headers never configure this value."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('public-origin 必须为单一 HTTPS 来源，例如 https://kanpace.example.com')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError('public-origin 地址或端口无效') from exc
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
            or '?' in value or '#' in value or ',' in parsed.netloc or '%' in parsed.netloc or '\\' in parsed.netloc):
        raise ValueError('public-origin 仅接受 HTTPS origin，不可含用户信息、路径、查询或多个域名')
    hostname = parsed.hostname or ''
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if (len(hostname) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                                       for label in hostname.split('.'))):
            raise ValueError('public-origin 主机名无效，请使用 ASCII/punycode 域名')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('public-origin 端口必须为 1–65535')
    if parsed.netloc.endswith(':'):
        raise ValueError('public-origin 端口不可为空')
    return 'https://' + parsed.netloc.lower()


def require_web_authentication(store):
    """Fail before binding if localhost account initialization is incomplete."""
    with store.connect() as con:
        config = next(iter(store.all(con, 'access_config')), {})
        people = {person['id']: person for person in store.all(con, 'people')}
        admins = [user for user in store.all(con, 'access_users')
                  if user.get('role') == 'admin' and user.get('active') and user.get('password_hash')
                  and (not user.get('person_id') or (user['person_id'] in people
                       and not people[user['person_id']].get('demo')
                       and people[user['person_id']].get('employment_status', 'active') == 'active'))]
        if not config.get('enabled') or not admins:
            raise ValueError('Web 模式要求已启用账号权限和有效管理员；请先以 localhost 模式完成 /api/access/setup')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, store, static_dir=None, *, public_origin=None):
        self.store = store
        self.public_origin = parse_public_origin(public_origin)
        self.web_mode = self.public_origin is not None
        if address[0] not in ('127.0.0.1', 'localhost', '0.0.0.0'):
            raise ValueError('服务仅支持本机地址或明确授权的 0.0.0.0')
        if address[0] == '0.0.0.0' and not self.web_mode:
            if getattr(store, 'instance_id', None):
                raise factory_instances.InstanceError(403, '独立工厂仅允许绑定本机地址')
            raise ValueError('0.0.0.0 必须配置 HTTPS public-origin 与管理员认证')
        if self.web_mode:
            require_web_authentication(store)
        if getattr(store,'instance_id',None):
            factory_instances.assert_ready(store)
            if address[0] not in ('127.0.0.1','localhost') and not self.web_mode:
                raise factory_instances.InstanceError(403,'独立工厂仅允许绑定本机地址')
        # Cookie attributes are deployment configuration, never guessed from
        # X-Forwarded-Proto or user-controlled request headers.
        store.web_origin = self.public_origin
        self.static_dir = Path(static_dir or BASE / 'static').resolve()
        super().__init__(address, Handler)
        self.device_bridge = DeviceBridge(store, execution_handler=store.handle_device_execution)
        self.project_dispatch = ProjectDispatchCoordinator(store, self.device_bridge)

    def server_close(self):
        if hasattr(self, 'project_dispatch'):
            self.project_dispatch.close()
        if hasattr(self, 'device_bridge'):
            self.device_bridge.disconnect()
        super().server_close()
