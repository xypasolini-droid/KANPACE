#!/usr/bin/env python3
"""Build a standalone synthetic demo from a verified, sanitized source release.

Never inventories live data, uploads, credentials or installed model folders.
The few edition-specific source changes are explicit and recorded in the demo
manifest. They are not applied to the production application's source files.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def build(source, output):
    source = source.resolve()
    original = json.loads((source / 'RELEASE-MANIFEST.json').read_text(encoding='utf-8'))
    if original.get('customer_data_included') is not False:
        raise ValueError('Use an already sanitized source release.')
    for item in original['files']:
        path = source / item['path']
        if path.is_symlink() or sha(path) != item['sha256']:
            raise ValueError('Base source release failed validation: ' + item['path'])
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
    release = output.resolve() / ('KANPACE-独立演示-' + stamp)
    release.mkdir(parents=True, mode=0o700)
    stage = release / 'KANPACE演示体验'
    stage.mkdir(mode=0o700)
    # Copy only the reviewed manifest inventory. Extra local files in the
    # extracted source folder are never included, even if someone ran it there.
    for item in original['files']:
        target = stage / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / item['path'], target)
    overlays = ['launch_demo.py', 'tools/demo_fixture.py', 'tools/build_demo_delivery.py']
    for directory in ('static/demo', 'static/demo-assets'):
        overlays.extend(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob('*') if p.is_file())
    for relative in overlays:
        path = ROOT / relative
        if path.is_symlink():
            raise ValueError('Demo sources cannot be symlinks')
        (stage / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, stage / relative)
    changes = []
    # All records retain demo=True. Only read scopes in this edition accept
    # them after launch_demo validates a marked data directory and sets its
    # server-owned flag. Ownership, authorization and release rules stay intact.
    for relative, names in [('kanpace/ai/scope.py', ('p', 't')), ('engineering_readiness.py', ('p', 't', 'd'))]:
        path = stage / relative
        content = path.read_text(encoding='utf-8')
        for name in names:
            before = f"not {name}.get('demo')"
            if before not in content:
                raise ValueError('Demo scope patch is stale: ' + relative)
            content = content.replace(before, f"(getattr(store, 'standalone_demo', False) or not {name}.get('demo'))")
        content = '# Standalone demo edition: server-owned synthetic-data read scope.\n' + content
        compile(content, relative, 'exec')
        write(path, content)
        changes.append({'path': relative, 'reason': 'Include synthetic records in read-only Agent/engineering scope only when the validated demo server enables its flag.'})
    for name in ('启动KANPACE.command', '启动柜序.command'):
        write(stage / name, '#!/bin/zsh\ncd -- "$(dirname -- "$0")"\nif ! command -v python3 >/dev/null 2>&1; then\n  echo "请先安装 Python 3，再双击启动。具体步骤见 先看这里.html。"\n  read\n  exit 1\nfi\npython3 launch_demo.py\nif [ $? -ne 0 ]; then\n  echo "请查看上方提示，按回车退出。"\n  read\nfi\n')
        (stage / name).chmod(0o755)
    shutil.copy2(stage/'启动KANPACE.command', stage/'Mac-启动演示.command')
    windows = '@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nwhere py >nul 2>nul\r\nif %errorlevel% equ 0 (\r\n  py -3 launch_demo.py\r\n) else (\r\n  python launch_demo.py\r\n)\r\nif errorlevel 1 (\r\n  echo 请先安装 Python 3，具体步骤见 先看这里.html。\r\n  pause\r\n)\r\n'
    for name in ('Windows-启动演示.bat', '启动KANPACE.bat'):
        (stage / name).write_bytes(windows.encode('utf-8'))
    # The inherited general launcher must not accidentally open a 8765 system.
    write(stage/'launch.py', '"""Independent demo compatibility entrypoint."""\nfrom launch_demo import main\nif __name__ == "__main__":\n    raise SystemExit(main())\n')
    # Remove inherited stop shortcuts: they control the regular launchd job,
    # while this edition runs in its own terminal and stops with Ctrl+C.
    for name in ('停止KANPACE.command', '停止柜序.command'):
        (stage/name).unlink(missing_ok=True)
    readme = '''# KANPACE 独立演示版

给队友体验工厂端与配置中台。使用合成展柜订单、图片、构件和人员，每台电脑独立保存，不连接原电脑，不含真实客户资料。

## 第一次打开

1. **先完整解压 ZIP**，不要在压缩包里直接运行文件。
2. 电脑需要 Python 3.10 或更新版本，推荐 Python 3.12。已有 Python 无需另外安装基础依赖；没有时从 https://www.python.org/downloads/ 安装。Windows 安装时选中 **Add python.exe to PATH**。
3. Mac 双击 **Mac-启动演示.command**；Windows 双击 **Windows-启动演示.bat**。浏览器会自动打开演示入口。

请保留启动窗口。停止时按 Ctrl+C，体验操作会保存在本包的 `data-demo`。再次启动继续使用；如果再次解压一份到新目录，就得到一套新的演示，不影响旧目录。

默认使用 http://127.0.0.1:8769/demo/index.html ，端口被其他程序占用会选择后续空闲端口，实际地址以启动窗口为准。不会打开原本的 8765 正式系统。地址是每个人电脑自己的本机地址，不能作为远程共享链接。

## 五分钟体验

- 打开“先看这张柜子”：看整体效果、施工示意、构件及不同工种。
- 打开“检查能不能下单”：核对缺项，用工作助手检查这张订单。
- 打开“让任务开始流转”：选一道可执行任务，体验开工、暂停、恢复；前序限制仍有效。
- 查看生产排程、BI 和 Excel 文件互联；中台浏览 19 行业及不同生产类型的流程。

所有图片为明确标注的合成示意，工时、尺寸和价格只用于流程体验，不是可用于生产的施工依据。演示目录首次启动生成，ZIP 内没有数据库或账号。

## 当前边界

基础 Web、合成图文、任务操作、本地规则助手与行业目录只需 Python 标准库和浏览器。OCR/CAD 原生识别、OR-Tools/PackingSolver 优化、LangGraph 扩展和实体工牌需要额外依赖，不会伪装已安装。

Mac 已实际验证启动与浏览器流程。提供 Windows 启动脚本，当前环境未执行 Windows 实机验收。中台自动开通独立工厂后台服务目前依赖 macOS；演示跨平台范围为基础单机 Web 和行业浏览。

许可和开源要求见 `LICENSING.md`、`THIRD_PARTY_NOTICES.md` 及各组件目录；本演示没有更改第三方许可，也未授予公开转售或重新分发自有代码的额外权利。`DEMO-MANIFEST.json` 记录基线源码、演示适配与文件摘要，`SHA256SUMS.txt` 可校验文件。
'''
    write(stage/'README.md', readme)
    write(stage/'先看这里.html', '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KANPACE · 开始体验</title><style>body{font:18px/1.9 -apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif;background:#f5f6f2;color:#243d2a;margin:0}main{max-width:780px;margin:48px auto;padding:32px;background:white;border:1px solid #dce3d6;border-radius:12px}h1{font-size:32px}strong{color:#1d4d27}li{margin:16px 0}a{color:#2f5a36}.note{font-size:16px;color:#5e6d60;border-top:1px solid #dde4d9;padding-top:20px}code{background:#f1f4ee;padding:4px 7px}@media(max-width:700px){main{margin:16px;padding:22px}}</style><main><img src="static/brand/KANPACE-Handoff-Black.svg" width="220" alt="KANPACE"><h1>三步，开始体验。</h1><ol><li>先把整个压缩包<strong>完整解压</strong>。</li><li>电脑需安装 <strong>Python 3.10 或更新版本</strong>。没有的话，到 <a href="https://www.python.org/downloads/">Python 官方网站</a>安装，推荐 3.12。Windows 安装时勾选 <strong>Add python.exe to PATH</strong>。</li><li>回到文件夹，Mac 双击 <strong>Mac-启动演示.command</strong>；Windows 双击 <strong>Windows-启动演示.bat</strong>。</li></ol><p>浏览器会自动打开，里面已经准备好合成订单、图文和任务。</p><p class="note">请保留启动窗口。结束时按 Ctrl+C。重新打开会保留体验记录；想从头体验，再解压一份到新文件夹即可。<br>这是一套独立演示，没有客户订单或账号，不会连接原电脑。</p></main></html>''')
    changes.extend([{'path': 'launch.py / startup scripts', 'reason': 'All user launch shortcuts select the isolated demo and keep 8765 unchanged.'}, {'path': 'static HTTP responses', 'reason': 'DemoHandler shows synthetic records, selects execution planning, labels demo pages and keeps industry navigation on the demo origin.'}])
    for path in stage.rglob('*'):
        if path.is_file() and (path.suffix in ('.sqlite3', '.db', '.pyc') or path.name in ('.env', 'device-secrets.json') or 'data-demo' in path.relative_to(stage).parts):
            raise ValueError('Disallowed demo payload: ' + str(path.relative_to(stage)))
    files = [{'path': str(p.relative_to(stage)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(stage.rglob('*')) if p.is_file()]
    manifest = {'schema': 1, 'edition': 'standalone-synthetic-demo', 'source_release': original['release'], 'created_at': datetime.now().astimezone().isoformat(), 'customer_data_included': False, 'python_runtime_included': False, 'native_engines_included': False, 'changes': changes, 'files': files}
    write(stage/'DEMO-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    write(stage/'SHA256SUMS.txt', ''.join(sha(p)+'  '+str(p.relative_to(stage))+'\n' for p in sorted(stage.rglob('*')) if p.is_file()))
    archive = release / (release.name + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(stage.rglob('*')):
            if path.is_file():zipped.write(path, str(Path(stage.name)/path.relative_to(stage)))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:raise ValueError('ZIP CRC failed')
    result = {'directory':str(release), 'source_directory':str(stage), 'archive':str(archive), 'bytes':archive.stat().st_size, 'sha256':sha(archive), 'files':len(files)+2, 'base_release':original['release']}
    write(release/'演示包清单.json', json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.source,args.output)
