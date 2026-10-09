#!/usr/bin/env python3
"""KANPACE's loopback-only file exchange CLI, using the normal HTTP endpoints."""
import argparse
import base64
import http.cookiejar
import ipaddress
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


class CLIError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        fp.close()
        raise CLIError('本地接口发生重定向，已停止；请核对 --base-url')


def base_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CLIError('本地服务地址无效')
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise CLIError('服务地址仅接受本机 HTTP(S) 主机和端口')
    hostname = parsed.hostname
    if hostname != 'localhost':
        try:
            local = ipaddress.ip_address(hostname).is_loopback
        except (ValueError, TypeError):
            local = False
        if not local:
            raise CLIError('CLI 只连接本机 localhost、127.0.0.1 或 ::1')
    if port is not None and not 1 <= port <= 65535:
        raise CLIError('本地服务端口无效')
    return value.rstrip('/')


def load_object(value, label):
    if not value:
        return {}
    try:
        source = Path(value[1:]).read_text(encoding='utf-8') if value.startswith('@') else value
        result = json.loads(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CLIError(label + '须为 JSON 对象或 @JSON文件路径')
    if not isinstance(result, dict):
        raise CLIError(label + '须为 JSON 对象')
    return result


class Client:
    def __init__(self, address, cookie_file=None, timeout=30):
        self.address = base_url(address)
        self.timeout = timeout
        handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
        if cookie_file:
            jar = http.cookiejar.MozillaCookieJar(cookie_file)
            try:
                jar.load(ignore_discard=True, ignore_expires=False)
            except (OSError, http.cookiejar.LoadError):
                raise CLIError('无法读取 Cookie 文件；请提供有效 Netscape 格式的本机登录 Cookie 文件')
            handlers.append(urllib.request.HTTPCookieProcessor(jar))
        self.opener = urllib.request.build_opener(*handlers)

    def request(self, path, data=None, binary=False):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8') if data is not None else None
        headers = {'Accept': 'application/json', 'Origin': self.address, 'User-Agent': 'KANPACE-CLI/1'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.address + path, data=body, headers=headers)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                error.close()
                raise CLIError('接口拒绝访问（HTTP ' + str(error.code) + '）；请在 Web 端登录并使用有权限的 --cookie-file')
            try:
                result = json.loads(error.read(1024 * 1024))
                message = result.get('error') or result.get('message') or '操作失败'
                if isinstance(message, dict):
                    message = message.get('message') or '操作失败'
            except (ValueError, UnicodeError):
                message = '接口操作失败'
            error.close()
            raise CLIError('HTTP ' + str(error.code) + '：' + str(message))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise CLIError('无法连接 KANPACE 本地服务，请确认 Web 端已启动') from error
        with response:
            try:
                content = response.read(64 * 1024 * 1024 + 1)
            except (OSError, TimeoutError):
                raise CLIError('本地接口响应中断，请核对服务状态；不要在结果不明时改用新的报工事件号')
            if len(content) > 64 * 1024 * 1024:
                raise CLIError('接口返回超过64MB，请缩小导出范围')
            if binary:
                return content
            try:
                return json.loads(content)
            except (ValueError, UnicodeError):
                raise CLIError('本地接口未返回有效 JSON，请核对服务地址')


def parser():
    root = argparse.ArgumentParser(description='KANPACE 本地文件互联 CLI：先预览，再应用；使用与网页相同的业务接口。')
    root.add_argument('--base-url', default='http://127.0.0.1:8765', help='本地服务地址，默认 http://127.0.0.1:8765')
    root.add_argument('--cookie-file', help='Netscape 格式登录 Cookie 文件；启用账号权限时使用')
    root.add_argument('--timeout', type=int, default=30, help='HTTP 超时秒数（1–120）')
    commands = root.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('preview', help='读取表头或提交字段映射，生成待审核预览')
    preview.add_argument('--file', required=True, help='CSV/XLSX 本地文件路径')
    preview.add_argument('--entity', choices=('projects', 'people', 'materials', 'progress'), required=True)
    preview.add_argument('--mapping-json', default='{}', help='规范字段→原表列名 JSON，或 @JSON文件路径；空对象只读表头')
    preview.add_argument('--defaults-json', default='{}', help='明确默认字段 JSON，或 @JSON文件路径')
    preview.add_argument('--source-system', default='Excel', help='原系统命名空间；相同来源应保持一致')
    preview.add_argument('--sheet', help='XLSX 工作表名')
    preview.add_argument('--header-row', type=int, help='原表表头行号')
    apply = commands.add_parser('apply', help='明确应用已核对的预览')
    apply.add_argument('--preview-id', required=True)
    apply.add_argument('--version', type=int, required=True)
    export = commands.add_parser('export', help='导出业务数据或预览应用回执')
    export.add_argument('--entity', choices=('projects', 'people', 'materials', 'progress'), required=True)
    export.add_argument('--format', choices=('csv', 'xlsx'), default='xlsx')
    export.add_argument('--output', required=True, help='新输出文件路径；默认不覆盖已有文件')
    export.add_argument('--overwrite', action='store_true', help='明确允许覆盖已有输出文件')
    export.add_argument('--project-id')
    export.add_argument('--factory-id')
    export.add_argument('--preview-id', help='导出指定预览的应用回执')
    return root


def run(argv=None, stdout=None, stderr=None):
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    args = parser().parse_args(argv)
    try:
        if not 1 <= args.timeout <= 120:
            raise CLIError('超时秒数须为1–120')
        client = Client(args.base_url, args.cookie_file, args.timeout)
        if args.command == 'preview':
            path = Path(args.file).expanduser()
            if path.suffix.lower() not in ('.csv', '.xlsx'):
                raise CLIError('请选择 CSV 或 XLSX 文件')
            try:
                if path.stat().st_size > 20 * 1024 * 1024:
                    raise CLIError('文件超过20MB，请拆成小表')
                content = path.read_bytes()
            except OSError:
                raise CLIError('无法读取指定的本地表格文件')
            payload = {'filename': path.name, 'content_base64': base64.b64encode(content).decode(), 'entity_type': args.entity,
                       'mapping': load_object(args.mapping_json, '字段映射'), 'defaults': load_object(args.defaults_json, '默认字段'),
                       'source_system': args.source_system}
            if args.sheet is not None: payload['sheet'] = args.sheet
            if args.header_row is not None: payload['header_row'] = args.header_row
            result = client.request('/api/exchange/preview', payload)
        elif args.command == 'apply':
            if args.version < 0 or not args.preview_id or len(args.preview_id) > 128:
                raise CLIError('预览编号或版本无效')
            result = client.request('/api/exchange/' + urllib.parse.quote(args.preview_id, safe='') + '/apply', {'expected_version': args.version})
        else:
            output = Path(args.output).expanduser()
            if output.exists() and not args.overwrite:
                raise CLIError('输出文件已存在；请使用新路径或明确指定 --overwrite')
            if not output.parent.is_dir():
                raise CLIError('输出目录不存在，请先创建目录')
            query = {'entity_type': args.entity, 'format': args.format}
            for key in ('project_id', 'factory_id', 'preview_id'):
                if getattr(args, key): query[key] = getattr(args, key)
            content = client.request('/api/exchange/export?' + urllib.parse.urlencode(query), binary=True)
            # Exclusive creation protects a concurrently-created user file.
            try:
                with output.open('wb' if args.overwrite else 'xb') as file:
                    file.write(content)
            except OSError:
                raise CLIError('无法写入输出文件，原文件未被擅自覆盖')
            result = {'output': str(output.resolve()), 'format': args.format, 'bytes': len(content)}
        print(json.dumps(result, ensure_ascii=False, indent=2), file=stdout)
        return 0
    except (CLIError, ValueError) as error:
        print('KANPACE：' + str(error), file=stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
