#!/usr/bin/env python3
"""Package the current KANPACE source with notices; never read business databases.

The allowlist, explicit templates and manifest keep private factory data out of
the reusable source snapshot. Third-party terms remain in THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_NAMES = {'README.md', 'DELIVERY.md', 'LICENSING.md', 'THIRD_PARTY_NOTICES.md',
              'third-party-components.json', '.gitignore'}
ROOT_SUFFIXES = {'.py', '.command', '.bat'}
DOC_DIRS = {'open-source', 'optimization', 'hardware', 'integrations', 'architecture', 'upgrade'}
CONFIG_NAMES = {'industry-templates.json', 'recognition-services.example.json', 'docling-worker.example.json'}
FIRMWARE_TEST_NAMES = {'test_badge_images_firmware.py', 'badge_execution_host.cpp',
                       'badge_images_host.cpp', 'badge_worker_ui_host.cpp'}
ENGINEERING_NAMES = {'真实自动拆图算法.md', '队友出图流程接入说明.md'}
DESIGN_NAMES = {'20261004-Web订单工作流-设计与状态.md', '20260912-R33-排程与整单派工.md', '20260912-六步工作流与胸牌.md', 'DESIGN-SYSTEM.md', 'HARDWARE-UI-STATES.md', 'UX-STATE-MATRIX.md',
                'MODEL-WORKSPACE.md', 'intelligence-integration.md',
                '20260907-LangGraph生产分析交互.md', '20260907-19行业配置入口.md',
                '20260907-双端产品改版.md', '20260908-展柜工厂工作顺序优化.md'}
PRODUCT_NAMES = {'19行业配置与拆解使用说明-20260907.md', '双端使用说明-20260907.md',
                 'KANPACE-历次需求与功能总账-20261004.md',
                 '泉州产业业务链与KANPACE中台规划-20260907.md', 'quanzhou-industries-20260907.json',
                 '20260907-泉州链路-装备建材电子.md', '20260907-泉州链路-鞋服食品纸品.md',
                 '20260907-泉州链路-工艺流程制造.md', '20260907-CAD资料与工程依据.md',
                 '20260908-展柜工厂五步工作流.md', '20260907-工厂配置中台审计.md', '20260907-现场交底产品主线.md',
                 'KANPACE-软件端与硬件端流程图.md', 'KANPACE-产品说明-精简版.md'}
VERIFY_NAMES = {'20260912-R33-排程与整单派工验证.md', '20260912-R32-软硬件与标签验证.md', '20260907-新版源码交付审查.md', '20260907-源码包实际验证.md',
                '20260907-真实工程引擎验收.md', '20260907-工程状态探针修正.md',
                'optimization-engines-tests.txt', 'optimization-engines-fixtures.json',
                '20260908-展柜工厂流程验证.md', '20260908-架构重构验证.md', '20260907-19行业中台验证.md', '20260907-双端产品验证.md'}
OMIT_PARTS = {'__pycache__', '.git', '.pio', 'node_modules', '.DS_Store',
              'data', 'backups', 'work', 'output', 'outputs', 'models', 'build',
              'bin', 'vendor-sources', '.engineering-wheelhouse'}
OMIT_NAMES = {'device-secrets.json', '.env', 'RELEASE-MANIFEST.json', 'SHA256SUMS.txt'}
OMIT_SUFFIXES = {'.pyc', '.pyo', '.log', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx'}
# These three verified build artifacts contain compiler/source-map paths. Rewriting
# them would invalidate the firmware manifest or browser CAD runtime. A future
# rebuild with a different digest must be reviewed before it can be packaged.
EMBEDDED_BUILD_PATH_EXCEPTIONS = {
    'firmware/goldenmorning-display/dist/firmware.bin': 'a00afb8890debaf01fc14b104daa8aa540a898165def746c9af016c5886ba288',
    'static/model/vendor/occt/occt-import-js.js': '3fb44ce11d00611f9b3f3c5775d520ebab48930c1f08279b7b1316f05f0d3379',
    'static/model/vendor/occt/occt-import-js.wasm': '33391fc9d94ea5c869a6718488bf0a9a464222bac9bdc764dfe1690cef281952',
}
VENDOR_PATH_NOTES = {
    'static/model/vendor/occt/occt-import-js.js': 'Unmodified upstream runtime includes the virtual Emscripten filesystem home; this is not a local workstation path.',
    'static/model/vendor/occt/occt-import-js.wasm': 'Unmodified upstream WebAssembly includes upstream OCCT compiler/assertion paths; this is not customer data or a path on the packaging workstation.',
    'firmware/goldenmorning-display/dist/firmware.bin': 'Historical compiled firmware includes compiler paths; never included in software-only scope.',
}


def host_path_markers():
    # Split the literals so the scanner does not flag its own source file.
    posix = tuple(('/' + name + '/').encode() for name in ('Users', 'Volumes', 'home'))
    posix += ((b'/' + b'var' + b'/folders/'), (b'/' + b'private/var' + b'/folders/'))
    windows = tuple((drive + ':').encode() + b'\\' + user + b'\\'
                    for drive in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
                    for user in (b'Users', b'users'))
    return (posix + windows
            + tuple(path.replace(b'/', b'\\/') for path in posix)
            + tuple(path.decode().encode('utf-16-le') for path in posix))


def contains_host_path(content):
    return any(marker in content for marker in host_path_markers())


def assert_portable_stage(stage, reviewed_exceptions=None):
    """Reject unreviewed absolute host paths before writing the manifest/ZIP.

    The narrow, digest-pinned build-artifact exceptions are recorded in the
    release manifest. Textual customer paths are never silently exempted.
    """
    exceptions = EMBEDDED_BUILD_PATH_EXCEPTIONS if reviewed_exceptions is None else reviewed_exceptions
    found_exceptions = []
    for path in sorted(stage.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(stage).as_posix()
        if not contains_host_path(path.read_bytes()):
            continue
        if relative in exceptions and sha(path) == exceptions[relative]:
            found_exceptions.append(relative)
            continue
        raise ValueError('Unreviewed original-machine path in staged file: ' + relative)
    return found_exceptions


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def allowed(relative, scope='software'):
    parts = relative.parts
    if any(p in OMIT_PARTS or p.startswith('.venv') for p in parts):
        return False
    if (relative.name in OMIT_NAMES or relative.name.startswith('.env.')
            or relative.suffix.lower() in OMIT_SUFFIXES
            or '.sqlite' in relative.name.lower()):
        return False
    if len(parts) == 1:
        return (relative.name in ROOT_NAMES or relative.suffix in ROOT_SUFFIXES
                or relative.name.startswith('requirements-') and relative.suffix in {'.txt', '.in'}) and '柜序' not in relative.name
    top = parts[0]
    if top == 'config':
        return len(parts) == 2 and relative.name in CONFIG_NAMES
    if top in {'kanpace', 'workers'}:
        return relative.suffix == '.py'
    if top in {'licenses', 'bridges', 'samples'}:
        return True
    if top == 'tests':
        if scope == 'software' and relative.name in FIRMWARE_TEST_NAMES:
            return False
        return relative.suffix in {'.py', '.cjs', '.mjs', '.js', '.cpp', '.h', '.json', '.csv', '.txt', '.md'}
    if top == 'tools':
        return relative.suffix in {'.py', '.cjs', '.md'}
    if top == 'static':
        if len(parts) > 1 and parts[1] == 'studies':
            return parts[2:] in [('taiwan-jewelry', 'index.html'), ('taiwan-jewelry', 'style.css'), ('taiwan-jewelry', 'view.js')]
        return True
    if top == 'docs':
        if len(parts) == 2:
            return relative.suffix == '.md'
        if parts[1] in DOC_DIRS:
            return True
        if parts[1] == 'engineering':
            return len(parts) == 3 and relative.name in ENGINEERING_NAMES
        if parts[1] == 'design':
            return len(parts) == 3 and relative.name in DESIGN_NAMES
        if parts[1] == 'verification':
            return len(parts) == 3 and relative.name in VERIFY_NAMES
        if parts[1] == 'product':
            return len(parts) == 3 and relative.name in PRODUCT_NAMES
        return False
    if scope == 'software-and-historical-firmware' and top == 'firmware' and parts[1] == 'goldenmorning-display':
        return 'releases' not in parts and relative.suffix not in {'.elf', '.map', '.o', '.a', '.log', '.ppm'}
    return False


def inventory(scope='software'):
    # Prune before descending: venvs, business files and multi-GB source trees are
    # not even inventoried by this tool.
    tops = {'licenses', 'bridges', 'samples', 'tests', 'tools', 'static', 'docs', 'config', 'kanpace', 'workers'}
    if scope == 'software-and-historical-firmware':
        tops.add('firmware')
    for parent, dirs, files in os.walk(ROOT, followlinks=False):
        directory = Path(parent)
        dirs[:] = [d for d in dirs if d not in OMIT_PARTS and not d.startswith('.venv')
                   and not (directory / d).is_symlink()
                   and (directory != ROOT or d in tops)]
        for name in sorted(files):
            path = directory / name
            relative = path.relative_to(ROOT)
            if allowed(relative, scope):
                if path.is_symlink():
                    raise ValueError('Refusing linked source file: ' + str(relative))
                yield path, relative


def firmware_check(folder):
    fw = json.loads((folder / 'dist/manifest.json').read_text())
    for name, item in fw['binaries'].items():
        path = folder / 'dist' / name
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Firmware binary does not match recorded build: ' + name)
    for name, expected in fw['sources'].items():
        if sha(folder / name) != expected:
            raise ValueError('Firmware source does not match recorded build: ' + name)
    return fw


def stage_templates(stage, scope='software'):
    changes = []
    def write(name, content, reason):
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        changes.append({'path': name, 'reason': reason})
    if scope == 'software-and-historical-firmware':
        write('README.md', (stage / 'DELIVERY.md').read_text(), 'Use delivery guide for historical software-and-firmware package entry.')
    else:
        # The workspace README contains the current Web startup and security
        # boundary. Replacing it with DELIVERY.md would erase those directions.
        for name in ('README.md', 'DELIVERY.md'):
            path = stage / name
            if path.is_file():
                content = path.read_text()
                content = content.replace('`firmware/` 与设备桥接为保留的历史源码，未刷写、未实板验证，不能据本版交付日期推断硬件已升级。',
                                          '本软件包保留设备桥接源代码；不含固件目录、固件二进制或实板验收。')
                content += '\n\n本次交付范围：当前完整软件与 Web 源码、测试、依赖输入和许可说明。固件及固件编译测试不在软件包内；业务数据库、上传资料、模型、虚拟环境与原机凭据由部署方单独保存。最新文件与清理记录见 `RELEASE-MANIFEST.json`。\n'
                write(name, content, 'Preserve current Web startup guide and identify the software-only delivery scope.')
        license_guide = stage / 'LICENSING.md'
        if license_guide.is_file():
            content = license_guide.read_text()
            content = re.sub(r'^- 硬件依赖：.+$', '- 历史硬件依赖由独立固件交付携带相应版权与许可说明；本软件包不含固件。',
                             content, flags=re.MULTILINE)
            content = re.sub(r'^本次交付清单会标注实际随包.+$',
                             '本次软件交付清单标注实际随包的 JavaScript、WebAssembly、依赖归档和许可证；本包不含字体派生固件、固件二进制或硬件验收。软件运行时与模型的后续分发仍须按实际组件清单处理相应许可义务。',
                             content, flags=re.MULTILINE)
            write('LICENSING.md', content, 'Clarify software-only artifact scope without altering third-party license or notice text.')
    write('tools/project-render-selection.json', json.dumps({'schema': 1, 'orders': {}}, ensure_ascii=False, indent=2)+'\n',
          'Replace private customer source selection with an empty schema template.')
    write('tools/PROJECT-RENDERS.md', '''# 项目效果图缓存

`build_project_renders.py` 根据经过人工核验的选择清单，把原图生成到当前工厂 `data/drawing-previews/`。

```sh
python3 tools/build_project_renders.py --source-dir /path/to/authorized-order-files --selection /path/to/reviewed-selection.json
```

需要 Pillow；PDF 转页还需要 Poppler 的 `pdftoppm`。通用源码中的 `project-render-selection.json` 是空模板，客户的项目、路径和原文件哈希由所属工厂自行保存。已有项目用 `order_key` 匹配，选择项固定原文件 SHA-256、PDF 页码或 Excel 图片成员；源文件变化后必须重新核验。

- `scope: project` 表示项目/区域整体效果；`scope: cabinet` 表示柜体参考。
- `source_category: effect_file` 表示原效果文件；`concept` 表示概念方案；`spreadsheet_cabinet` 表示表格里的柜体参考。
- `reference_note` 保留版本疑问和人工核验说明。

效果图用于查看整体；生产拆解依据施工图和经过确认的工程数据。本工具不从效果图推断制造尺寸。历史客户选择清单与统计保留在原工厂，不随通用代码交付。
''', 'Replace customer-specific render research notes with portable usage guidance.')
    brand_path = stage/'static/brand/provenance.json'
    brand = json.loads(brand_path.read_text())
    brand['manual'] = Path(brand['manual']).name
    for asset in brand.get('assets', []):
        if 'source' in asset:
            asset['source'] = 'user-provided-brand-assets/' + Path(asset['source']).name
    write('static/brand/provenance.json', json.dumps(brand, ensure_ascii=False, indent=2)+'\n',
          'Preserve brand origin names and hashes while removing original-machine locations.')
    hardware_guide = '''# 开发板联动

板型、引脚、当前固件和烧录方式见 [固件 README](../firmware/goldenmorning-display/README.md)；开源依赖见 [固件第三方说明](../firmware/goldenmorning-display/THIRD_PARTY_NOTICES.md)。

1. USB 连接开发板，在“工牌联动”扫描并选择本机实际端口。端口和设备编号按当前连接读取。
2. 在“胸牌派工”选择项目，核对每位工人的胸牌绑定，然后整单建立派工队列。任务与图片回执分别记录，未连接设备保持待连接。
3. 图片按任务关联自动附带，工人可在图册核对多张施工图、工程图与效果图。图片传输说明见 [图片协议](../firmware/goldenmorning-display/IMAGE-PROTOCOL.md)。
4. 配置 Wi-Fi 时只在本地网页填写网络和密码。使用开发板支持的2.4 GHz网络；无线调用还需要电脑能访问该局域网地址。连接失败时可继续使用USB，并检查VPN/路由；本包不改变电脑网络设置。

新电脑需重新选择设备、配对并核验回执。通用源码包不带设备密码、MAC、SSID、原机IP或整片Flash备份。历史现场测试由项目所有者单独保存；本次打包没有重新执行实板验收。
'''
    if scope == 'software':
        hardware_guide = '''# 软件中的设备桥接

本软件源码包保留 `device_bridge.py`、`badge_image_transfer.py` 与 Web 工牌功能。板型、引脚、固件和图片协议由独立固件交付确定；本包不含固件，不执行烧录或实板验收。

USB 设备端口按当前连接重新扫描、选择并核验回执。工人绑定、整单派工、任务与图片回执通过现有业务权限和工程版本核对。Wi-Fi 密码只在本地页面填写；实际设备与局域网需要在部署现场重新验收。本软件包不携带原机密码、MAC、SSID、IP 或 Flash 备份。
'''
    write('docs/开发板联动.md', hardware_guide, 'Replace device-identifying field history with generic bridge guidance for the selected delivery scope.')
    study = {'title': '图纸分工 · 空白模板', 'summary': '通用源码包保留案例查看器，客户图纸与案例数据由所属工厂单独保管',
             'counts': {'files': 0, 'pdfs': 0, 'pages': 0, 'variants': 0, 'cabinets': 0},
             'work_packages': [], 'cabinet_types': [], 'issues': [], 'flow': []}
    write('static/studies/taiwan-jewelry/study.json', json.dumps(study, ensure_ascii=False, indent=2)+'\n',
          'Private case replaced with an explicit empty template; viewer code preserved.')
    write('static/studies/taiwan-jewelry/source-inventory.json', json.dumps({'schema': 1, 'sources': []}, ensure_ascii=False, indent=2)+'\n',
          'Private source inventory replaced with an explicit empty template; no source files or customer images included.')
    original = stage / 'static/studies/taiwan-jewelry/index.html'
    write(str(original.relative_to(stage)), original.read_text().replace('台湾珠宝柜 · 图纸分工样例', '图纸分工 · 空白模板'),
          'Give the generic template a neutral initial title.')
    viewer = stage / 'static/studies/taiwan-jewelry/view.js'
    if viewer.is_file():
        content = viewer.read_text().replace('台湾珠宝柜 · 图纸分工样例', '图纸分工 · 空白模板')
        content = content.replace('KANPACE-台湾珠宝柜-图纸分工学习.json', 'KANPACE-图纸分工模板.json')
        write(str(viewer.relative_to(stage)), content, 'Use neutral viewer labels and export filename with the empty case template.')
    ledger = stage / 'docs/product/KANPACE-历次需求与功能总账-20261004.md'
    if ledger.is_file():
        content = ledger.read_text()
        content = re.sub(r'(用此前提供的完整展柜订单做盲测：)[^。\n]+',
                         r'\1经过授权的四类历史订单（具体客户名称由所属工厂单独保存）', content)
        if content != ledger.read_text():
            write(str(ledger.relative_to(stage)), content, 'Remove real historical customer names from the generic product capability ledger.')
    draft_guide = stage / 'docs/真实订单拆单草稿接口.md'
    if draft_guide.is_file():
        content = draft_guide.read_text()
        content = re.sub(r'("order_key"\s*:\s*")[^"]+', r'\1DEMO-ORDER-001', content)
        content = re.sub(r'("project"\s*:\s*\{\s*"name"\s*:\s*")[^"]+', r'\1合成展示柜订单', content)
        write(str(draft_guide.relative_to(stage)), content, 'Use synthetic identifiers in the documented import example.')
    importer = stage / 'tools/build_historical_demo.py'
    if importer.is_file():
        content = importer.read_text()
        choices = re.search(r"parser\.add_argument\('--only', choices=\(([^\n]+)\)\)", content)
        if choices:
            slugs = re.findall(r"'([^']+)'", choices.group(1))
            if slugs:
                content = content.replace("'" + slugs[0] + "'", "'demo_jewelry'")
            content = re.sub(r"parser\.add_argument\('--only', choices=\([^\n]+\)\)",
                             "parser.add_argument('--only', help='Select any slug from the private source manifest')", content)
        content = re.sub(r'SIM-[A-Z0-9-]+', 'SIM-DEMO-0001', content)
        content = re.sub(r"模拟排程没有唯一关联[^']+", '模拟排程没有唯一关联演示项目', content)
        write(str(importer.relative_to(stage)), content, 'Make the private-manifest importer portable without hardcoded customer selectors or historical order identifiers.')
    schedule_test = stage / 'tests/test_schedule_0929.py'
    if schedule_test.is_file():
        content = schedule_test.read_text()
        content = re.sub(r"('店铺信息'\s*:\s*')[^']+", r'\1模拟测试-演示展柜店', content)
        content = re.sub(r"(\{'name'\s*:\s*')[^']+", r'\1模拟测试-演示展柜店', content)
        content = re.sub(r'SIM-[A-Z0-9-]+', 'SIM-DEMO-0001', content)
        write(str(schedule_test.relative_to(stage)), content, 'Use fully synthetic shop labels and order identifiers in the schedule regression fixture.')
    draft_test = stage / 'tests/test_order_drafts.py'
    if draft_test.is_file():
        content = re.sub(r"('order_key'\s*:\s*')[^']+", r'\1DEMO-TEST', draft_test.read_text())
        write(str(draft_test.relative_to(stage)), content, 'Use a neutral synthetic order key in the import regression fixture.')
    fpath = stage / 'firmware/goldenmorning-display/dist/manifest.json'
    fw = json.loads(fpath.read_text()) if fpath.is_file() else {}
    if 'hardware_validation' in fw:
        fw['hardware_validation'] = f'Firmware {fw.get("version", "unknown")}: bundled release build and host verification are documented in BUILD-VERIFICATION.md. Device-identifying field logs are excluded. This packaging operation does not flash or physically verify a board.'
        write(str(fpath.relative_to(stage)), json.dumps(fw, ensure_ascii=False, indent=2)+'\n',
              'Remove private device/order details only; preserve all binary and compiled-source digests.')
    # Dependency inventories can record local checkout locations. They are not
    # part of the component's license and have no value on the receiving host.
    for path in stage.rglob('*.json'):
        text = path.read_text()
        cleaned = text.replace(str(ROOT), '${KANPACE_ROOT}')
        if contains_host_path(cleaned.encode()):
            def portable_value(value):
                if isinstance(value, str):
                    return '原机路径已移除' if contains_host_path(value.encode()) else value
                if isinstance(value, list):
                    return [portable_value(item) for item in value]
                if isinstance(value, dict):
                    return {key: portable_value(item) for key, item in value.items()}
                return value
            cleaned = json.dumps(portable_value(json.loads(cleaned)), ensure_ascii=False, indent=2) + '\n'
        if cleaned != text:
            write(str(path.relative_to(stage)), cleaned, 'Remove original-machine paths from dependency metadata.')
    host_prefix = r'/(?:' + '|'.join(('Users', 'Volumes', 'home')) + r')/'
    for path in list((stage/'docs').rglob('*.md')):
        if 'licenses' in path.relative_to(stage).parts:
            continue
        content = path.read_text()
        def portable_link(match):
            label, original_path = match.group(1), match.group(2)
            relative = Path(original_path)
            if relative.parts[:2] == ('output', 'pdf'):
                relative = Path('docs/hardware') / relative.name
            target = stage / relative
            if target.is_file():
                return '['+label+']('+Path(os.path.relpath(target, path.parent)).as_posix()+')'
            return label+'（历史现场资料另存）'
        content = re.sub(r'\[([^\]]+)\]\('+re.escape(str(ROOT)) + r'/([^\)]+)\)', portable_link, content)
        content = re.sub(r'\[([^\]]+)\]\(' + host_prefix + r'[^\)]+\)', r'\1（原机资料另存）', content)
        content = re.sub(r'("source_path"\s*:\s*")' + host_prefix + r'[^"]*', r'\1<由所属工厂填写原文件>', content)
        content = re.sub(r'\[([^\]]+)\]\(codex://[^\)]+\)', r'\1（原任务记录另存）', content)
        content = content.replace(str(ROOT), '${KANPACE_ROOT}')
        # Upgrade provenance also contains bare/backtick paths, not only links.
        content = re.sub(host_prefix + r'[^\s`\]\)"<>，；。]+', '<原机路径已移除>', content)
        content = re.sub(r'[A-Za-z]:\\(?:Users|users)\\[^\s`\]\)"<>，；。]+', '<原机路径已移除>', content)
        if content != path.read_text():
            write(str(path.relative_to(stage)), content, 'Make local documentation links portable; mark excluded historical field material.')
    return changes


def assert_source_snapshot(source_records):
    """Fail if any included workspace input changed while creating the release."""
    for record in source_records:
        source = ROOT / record.get('source_path', record['path'])
        if not source.is_file() or source.is_symlink() or sha(source) != record['source_sha256']:
            raise ValueError('Source changed during snapshot: ' + record['path'])


def verify_archive(archive, stage):
    """Check CRC, exact member list and every archived file against staged bytes."""
    expected = {'KANPACE/' + p.relative_to(stage).as_posix(): p
                for p in stage.rglob('*') if p.is_file()}
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('ZIP CRC verification failed')
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('ZIP member inventory mismatch')
        for name in names:
            if name.startswith('/') or '..' in Path(name).parts or '\\' in name:
                raise ValueError('Unsafe archive path')
            if hashlib.sha256(bundle.read(name)).hexdigest() != sha(expected[name]):
                raise ValueError('ZIP member checksum mismatch: ' + name)
    manifest = json.loads((stage / 'RELEASE-MANIFEST.json').read_text())
    for record in manifest['files']:
        path = stage / record['path']
        if sha(path) != record['sha256'] or path.stat().st_size != record['bytes']:
            raise ValueError('Manifest checksum mismatch: ' + record['path'])
    for line in (stage / 'SHA256SUMS.txt').read_text().splitlines():
        expected_sha, name = line.split('  ', 1)
        if sha(stage / name) != expected_sha:
            raise ValueError('SHA256SUMS mismatch: ' + name)
    return {'zip_crc': 'passed', 'zip_inventory': 'passed', 'zip_member_sha256': 'passed',
            'manifest_sha256': 'passed', 'sha256sums': 'passed'}


def build(output, scope='software'):
    if scope not in {'software', 'software-and-historical-firmware'}:
        raise ValueError('Unknown delivery scope')
    output = output.expanduser().resolve()
    if output == ROOT or output.is_relative_to(ROOT):
        raise ValueError('Output directory must be outside the source repository.')
    for name in ('DELIVERY.md', 'LICENSING.md', 'THIRD_PARTY_NOTICES.md', 'third-party-components.json'):
        if not (ROOT/name).is_file():
            raise ValueError('Required delivery notice is missing: ' + name)
    firmware = firmware_check(ROOT/'firmware/goldenmorning-display') if scope != 'software' else None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    release = 'KANPACE-最新软件源码-' + stamp
    output.mkdir(parents=True, exist_ok=True)
    delivery = output/release
    delivery.mkdir(mode=0o700)
    stage = delivery/'KANPACE'
    stage.mkdir(mode=0o700)
    source_records = []
    for source, relative in sorted(inventory(scope)):
        target = stage/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(source)
        shutil.copy2(source, target)
        if sha(target) != before or sha(source) != before:
            raise ValueError('Source changed during snapshot: ' + str(relative))
        source_records.append({'path': relative.as_posix(), 'source_sha256': before})
    hardware_illustrations = () if scope == 'software' else ('KANPACE-智能胸牌界面示意.png', 'KANPACE-智能胸牌功能规划-2.png',
                 'KANPACE-智能胸牌功能规划-3.png', 'KANPACE-智能胸牌功能与界面规划-20260907.pdf')
    for name in hardware_illustrations:
        source = ROOT/'output/pdf'/name
        # These reviewed synthetic product-plan illustrations are the only
        # explicit exception to excluding generated output and screenshots.
        if source.is_file() and not source.is_symlink():
            relative = Path('docs/hardware')/name
            target = stage/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            source_records.append({'path': relative.as_posix(), 'source_path': 'output/pdf/'+name, 'source_sha256': sha(source)})
    transforms = stage_templates(stage, scope)
    required = ('app.py', 'kanpace/bootstrap.py', 'kanpace/application/store.py',
                'kanpace/infrastructure/sqlite.py', 'kanpace/http/server.py', 'kanpace/ai/scope.py',
                'kanpace/domain/parts.py', 'static/core/http-client.js', 'docs/architecture/ARCHITECTURE.md',
                'engineering_readiness.py', 'static/factory-drawing.css', 'industry_templates.py', 'factory_config.py', 'factory_instances.py',
                'control_platform.py', 'config/industry-templates.json', 'static/control/index.html',
                'static/index.html', 'static/industry-map/industries.json',
                'docs/product/19行业配置与拆解使用说明-20260907.md',
                'docs/product/KANPACE-软件端与硬件端流程图.md',
                'docs/product/KANPACE-产品说明-精简版.md',
                'docs/engineering/真实自动拆图算法.md',
                'document_recognition.py', 'workers/docling_service.py', 'requirements-web.in',
                'requirements-docling-worker.txt', 'config/recognition-services.example.json',
                'config/docling-worker.example.json', 'docs/document-recognition.md',
                'docs/docling-cpu-worker.md', 'docs/upgrade/cloud-runtime.md',
                'docs/upgrade/runtime-locks/optimization.txt', 'docs/upgrade/runtime-locks/agent.txt',
                'docs/upgrade/软件升级实施记录-20261004.md',
                'docs/design/20261004-Web订单工作流-设计与状态.md',
                'docs/product/KANPACE-历次需求与功能总账-20261004.md',
                'tests/test_recognition_xlsx.py', 'tests/test_recognition_pdfium_frames.py',
                'tools/setup_web_runtime.py', 'static/order-workflow.js')
    for name in required:
        if not (stage/name).is_file():
            raise ValueError('Required current runtime file omitted: ' + name)
    industry_catalog = json.loads((stage/'config/industry-templates.json').read_text())
    if len(industry_catalog['industries']) != 19:
        raise ValueError('Industry catalog is incomplete')
    if firmware is not None:
        firmware_check(stage/'firmware/goldenmorning-display')
    assert_source_snapshot(source_records)
    build_path_exceptions = assert_portable_stage(stage)
    files = [{'path': p.relative_to(stage).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
             for p in sorted(stage.rglob('*')) if p.is_file()]
    manifest = {'schema': 2, 'release': release, 'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': scope, 'firmware_included': firmware is not None,
                'firmware_version': firmware['version'] if firmware is not None else None,
                'source_origin': 'Current workspace snapshot; file hashes below identify included inputs without disclosing host paths.',
                'native_environments_included': False, 'customer_data_included': False,
                'verified_build_artifacts_with_embedded_compiler_paths': build_path_exceptions,
                'unmodified_vendor_path_notes': {name: VENDOR_PATH_NOTES[name] for name in build_path_exceptions},
                'transforms': transforms, 'files': files, 'source_snapshot': source_records,
                'excluded': ['data/', 'backups/', '.venv*/', '.engineering-wheelhouse/', 'models/',
                             'bin/', 'build/', 'vendor-sources/optimization/', 'output/', 'outputs/', 'work/',
                             'device secrets', 'customer case PDFs/images/data', 'private drawing selection',
                             'historical firmware releases', 'private field screenshots and logs']
                            + (['firmware/', 'firmware-only compiler tests'] if scope == 'software' else [])}
    (stage/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    all_files = sorted(p for p in stage.rglob('*') if p.is_file())
    (stage/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.relative_to(stage).as_posix()+'\n' for p in all_files))
    archive = delivery/(release+'.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(p for p in stage.rglob('*') if p.is_file()):
            bundle.write(path, 'KANPACE/'+path.relative_to(stage).as_posix())
    verification = verify_archive(archive, stage)
    assert_source_snapshot(source_records)
    assert_portable_stage(stage)
    archive.chmod(0o600)
    result = {'directory': str(delivery), 'source_directory': str(stage), 'archive': str(archive),
              'bytes': archive.stat().st_size, 'sha256': sha(archive), 'files': len(all_files)+1,
              'scope': scope, 'verification': verification,
              'firmware_version': firmware['version'] if firmware is not None else None,
              'firmware_sha256': firmware['binaries']['firmware.bin']['sha256'] if firmware is not None else None}
    (delivery/'交付清单.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (delivery/'SHA256SUMS.txt').write_text(result['sha256']+'  '+archive.name+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path.home()/'Downloads')
    parser.add_argument('--scope', choices=('software', 'software-and-historical-firmware'), default='software',
                        help='Software-only is the default; historical firmware is an explicit separate scope.')
    args = parser.parse_args()
    build(args.output_dir, args.scope)


if __name__ == '__main__':
    main()
