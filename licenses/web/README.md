# 浏览器第三方与对应源码

核验日期：2026-09-07。本目录是交付材料，应与 `static/model/vendor/` 一起保留。

## 实际随附文件

| 组件 | 实际版本与许可 | 交付位置 |
| --- | --- | --- |
| Three.js | 0.180.0 / r180，MIT | `static/model/vendor/three/`；本目录 `three-r180-MIT.txt` |
| occt-import-js | 0.0.23，LGPL-2.1 | `static/model/vendor/occt/`；对应 npm 源码 `occt-import-js-0.0.23.tgz` |
| 浏览器内的 Open CASCADE Technology | **7.6.1**，LGPL-2.1 + OCCT exception 1.0 | `OCCT-d2abb6d844231cb8f29be6894440874a4700e4a5.tar.gz`、`OCCT-7.6.1-browser-LGPL.txt`、`OCCT-browser-exception.txt` |
| Emscripten 生成代码及支持库 | 构建脚本锁定 3.1.69；Emscripten MIT 或 NCSA，musl、libc++、libc++abi 各自许可 | 本目录 `Emscripten-3.1.69-*.txt` |

KANPACE 的浏览器 CAD 导入使用了 Open CASCADE Technology 的功能。其版权归 Open CASCADE SAS 及各源文件列明的贡献者；occt-import-js 的版权与条款见原始源码。OCCT 例外主要涉及头文件被对象代码使用的情形，**不会把 OCCT 库本体改成 MIT，也不会取消库源码的分发义务**。

## 已核验的来源

- npm `occt-import-js@0.0.23` 的 `gitHead` 为 `c2148e54b456b571238d35cac037d304053d64b2`；该提交将 OCCT 子模块固定到 `d2abb6d844231cb8f29be6894440874a4700e4a5`。OCCT 的 `Standard_Version.hxx` 明确写 7.6.1。这与后端 OCCT 7.8.1 是两套依赖。
- npm 原始 tarball 的 SHA-512 integrity 已核对。`vendored-verification.json` 记录 14 个实际 vendored 文件的 SHA-256 与 npm 成员路径：全部字节相同，包括 WASM。
- `occt-npm-source-git-verification.json` 比对 123 个 npm 文件与精确 Git 提交；其差异仅为 Windows CRLF/LF 换行，源码和构建内容匹配。
- `web-source-provenance.json` 记录 OCCT 完整源码与补充许可的固定下载 URL、大小及 SHA-256。源码来自 Open CASCADE 官方仓库的精确提交，并非最新版通用链接。
- Three.js 只随附本应用实际使用的 8 个源文件；`three-0.180.0-distributed-files.tar.gz` 保留同一组源文件及 MIT 文本。**完整 Three.js npm 中的示例字体、其他库和示例没有随包加入。**

上游入口：[occt-import-js 精确提交](https://github.com/kovacsv/occt-import-js/tree/c2148e54b456b571238d35cac037d304053d64b2)、[OCCT 精确提交](https://github.com/Open-Cascade-SAS/OCCT/tree/d2abb6d844231cb8f29be6894440874a4700e4a5)、[Three.js r180](https://github.com/mrdoob/three.js/tree/r180)。

## 使用随包源码重建可替换库

1. 在新的工作目录解压 `occt-import-js-0.0.23.tgz`，得到 `package/`。
2. 解压 `OCCT-d2abb6d844231cb8f29be6894440874a4700e4a5.tar.gz`，把其中完整目录放到 `package/occt/`，使 `package/occt/src/` 和 `package/CMakeLists.txt` 对应。
3. 原始 `package/tools/setup_emscripten_win.bat` 指定 **Emscripten 3.1.69、mingw-7.1.0-64bit**；原始 GitHub 工作流使用 Windows 2022、Node.js 18.x 和 CMake（上游说明要求至少 3.6）。工具链需要另行安装，未打入本源码交付包。
4. 在 Windows 命令提示符运行原始 `tools\setup_emscripten_win.bat`，再运行 `tools\build_wasm_win_release.bat`。编译选项、参与的 OCCT 源目录和链接参数均在随附 `CMakeLists.txt` 中。
5. 将生成的 `build/wasm/Release/occt-import-js.js` 和 `.wasm` 成对替换 `static/model/vendor/occt/` 中对应文件，重载浏览器。原始 JS 与 WASM 是两个独立文件，通过 Worker 加载；没有加入签名锁定、禁止替换或混淆限制。
6. 若改变库，保留原许可、版权、修改者与日期，并同时提供修改后的完整对应库源码及构建材料。对库进行调试所需的修改、替换和反向工程权利不受 KANPACE 自有代码条款限制。

以上为原始构建材料与替换说明。本次核验没有重编译 WASM，**没有宣称可逐位复现同一二进制**。提供完整来源与脚本，不等于保证所有未来主机均能无调整构建；升级工具链或库之后，应重新生成来源清单与验证哈希。

## Web 字体

目前 `static/` 没有 `.ttf/.otf/.woff/.woff2` 字体文件，页面采用操作系统字体回退。本包没有复制 Apple/Microsoft 系统字体，也未把系统字体标作 OFL。ESP32 位图字库与其 OFL 原字体由 `firmware/goldenmorning-display/THIRD_PARTY_NOTICES.md` 单独说明。
