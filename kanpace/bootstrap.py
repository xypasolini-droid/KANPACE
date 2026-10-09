"""Local process startup, shared by the compatibility entrypoint and package CLI."""
from __future__ import annotations

import argparse
import os
import factory_instances
from kanpace.core.constants import BASE
from kanpace.application.store import Store
from kanpace.http.server import Server, parse_public_origin


def main():
    parser = argparse.ArgumentParser(description='KANPACE 拆单与任务协同 Web 工作台')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', default=str(BASE / 'data'))
    parser.add_argument('--no-demo', action='store_true')
    parser.add_argument('--isolated-instance', action='store_true',help='仅启动已预置认证的独立工厂')
    parser.add_argument('--listen', choices=('127.0.0.1', '0.0.0.0'), default='127.0.0.1',
                        help='后端监听地址；默认仅本机，公网绑定必须启用 Web 认证模式')
    parser.add_argument('--public-origin', default=os.environ.get('KANPACE_PUBLIC_ORIGIN') or None,
                        help='TLS 反代的单一 HTTPS origin，也可设置 KANPACE_PUBLIC_ORIGIN')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口必须为 1–65535')
    try:
        origin = parse_public_origin(args.public_origin)
    except ValueError as exc:
        parser.error(str(exc))
    if args.listen == '0.0.0.0' and origin is None:
        parser.error('0.0.0.0 必须配置 HTTPS --public-origin 和管理员认证')
    if args.isolated_instance:os.umask(0o077)
    store = Store(args.data_dir, seed=not args.no_demo,empty=args.isolated_instance)
    if args.isolated_instance:factory_instances.assert_ready(store)
    try:
        server = Server((args.listen, args.port), store, public_origin=origin)
    except ValueError as exc:
        parser.error(str(exc))
    print('KANPACE Web 工作台：' + origin if origin else 'KANPACE 本地工作台：http://127.0.0.1:' + str(args.port), flush=True)
    print('数据保存在：' + str(store.data_dir), flush=True)
    print('按 Ctrl+C 停止。' + ('HTTPS 由反向代理终止；后端按配置的 Host/Origin 接收请求。' if origin else '默认仅本机可访问。'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止；本地数据已保存。')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
