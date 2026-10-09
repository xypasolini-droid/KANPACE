# KANPACE 第三方软件声明 / Third-party notices

原基线核验日期：2026-09-07；Web 升级补充：2026-10-04。此文件说明实际集成的第三方组件，**不是给 KANPACE 自有代码、商标、客户资料或图纸授予开源许可**。自有代码与交付权利见 [LICENSING.md](LICENSING.md)。第三方保留各自版权和许可条款；下列摘要不替代随附的完整许可证。

本源码交付包含 KANPACE 适配代码、固定版本安装脚本、锁文件、浏览器依赖及其对应源码/许可材料，以及固件单独清单所列文件。`.venv*`、wheel 缓存、OCR 模型权重、优化器本地可执行文件、`vendor-sources/optimization` 构建树及工厂业务资料不属于通用源码包。安装器在收件人机器上下载依赖；不能将“安装后可用”理解为“此包已含所有引擎二进制”。

## 五个核心引擎

| 引擎 | 当前实际基线 | 许可及边界 | 源码包的交付方式 |
| --- | --- | --- | --- |
| PaddleOCR | PaddleOCR **3.3.2**；PaddlePaddle **3.2.2**；PaddleX **3.3.13** | 代码 Apache-2.0。默认 PP-OCRv5_mobile_det / mobile_rec 的**精确权重版本另行核验为 Apache-2.0**，不能从代码许可推导任意模型许可 | 适配源码、安装器、67 个 Python 包的锁文件/许可记录、模型卡和固定 revision/哈希；不随附权重或运行环境 |
| Open CASCADE Technology | 后端 OCCT **7.8.1**，通过 cadquery-ocp **7.8.1.1.post1** | OCP 包装层 Apache-2.0；原生 OCCT **LGPL-2.1 + OCCT exception**。wheel 内的 FreeImage、LibRaw、VTK 等继续适用各自许可 | 适配源码、安装器、原生库清单与许可；不随附 OCP wheel 或 `.dylib` |
| Google OR-Tools | **9.15.6755** | Apache-2.0；其 Python/原生依赖逐项保留许可，不全归为 Apache | 排程适配源码、版本锁与许可证；由安装器下载 |
| PackingSolver | commit **4ba84e45ab4b7697d2fec2bb62bdca09dab56d29** | MIT；本机使用 HiGHS 后端。HiGHS 自身 MIT，内部 AMD 为 BSD-3-Clause、METIS 为 Apache-2.0 等，详见完整清单；Boost 为 BSL-1.0 | 构建安装脚本、固定源码提交、构建选项、许可证；不随附本机优化器二进制或大型构建树 |
| LangGraph | **1.2.11**；checkpoint **4.2.0**；checkpoint-sqlite **3.1.1** | MIT；orjson、certifi 等依赖含独立 MPL/Apache/MIT 义务，不被 LangGraph 的 MIT 覆盖 | 本地工作流适配源码、42 个运行包的锁文件/许可记录；没有随附 LLM 权重、LangSmith 云服务账号或云服务权利 |

代码版权与完整原文分别见 [工程引擎许可证](licenses/engineering/)、[优化引擎许可证](licenses/optimization/)、[LangGraph 运行时许可证](docs/open-source/licenses/langgraph-runtime/)。上游：[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)、[PaddlePaddle](https://github.com/PaddlePaddle/Paddle)、[OCCT](https://github.com/Open-Cascade-SAS/OCCT)、[OCP](https://github.com/CadQuery/OCP)、[OR-Tools](https://github.com/google/or-tools)、[PackingSolver](https://github.com/fontanf/packingsolver)、[LangGraph](https://github.com/langchain-ai/langgraph)。

## 浏览器实际随附依赖

- **QR Code Generator：MIT。** Copyright © 2009 Kazuhiko Arase。2026-09-12 新增本地二维码编码，固定官方提交 `83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8` 的 `js/dist/qrcode.js`，原样保存为 `static/qr-code.js`。完整许可、来源与 SHA-256 在 `licenses/web/qrcode-generator/`。标签数据仅在浏览器本地编码，无外部二维码服务。

- **Three.js 0.180.0：MIT。** Copyright © 2010–2025 three.js authors。实际使用的 8 个 JS/许可文件与官方 npm 原件一致；版权和许可保留在 `static/model/vendor/three/LICENSE`。
- **occt-import-js 0.0.23：LGPL-2.1。** JS/WASM 与官方 npm 原件一致。它实际编入 **OCCT 7.6.1**，并非后端的 7.8.1。KANPACE 使用了 Open CASCADE Technology 的功能。库的 LGPL 文本、OCCT 例外、精确提交的完整对应源码和原始构建脚本均在 `licenses/web/`。完整来源、哈希、构建及替换说明见 [浏览器源码说明](licenses/web/README.md)。
- **Emscripten 3.1.69 构建产生的支持代码：** Emscripten 的 MIT/NCSA 文本，以及 musl、libc++、libc++abi 的各自版权/许可，均在 `licenses/web/` 保留；不能把整个 WASM 只标为 Emscripten MIT。
- **Web 字体：** 当前使用系统字体回退，没有在 `static/` 中分发原始字体文件。系统字体不是本项目重新授权的开源字体。

## 原生嵌入库与权重的特别说明

Web 基础功能另外使用 **pySerial 3.5（BSD-3-Clause）** 连接 USB，以及 **Pillow 12.3.0（MIT-CMU，本机实测）** 验证/处理图片。`requirements-media.txt` 当前声明 `Pillow>=12.0,<13`，不等于固定在 12.3.0；这是 Web 环境，与工程引擎固定的 Pillow 11.3.0 分开。既有 PDF 预览链还以独立进程调用 **Poppler 26.04.0 的 pdfinfo / pdftoppm（GPL v2；本机发行包标注 GPL-2.0-only）**。这些运行包/外部程序均未随本源码包附送，原文与实测来源在 [Web 运行依赖许可](licenses/web-runtime/)。本清单没有因调用外部命令而替 KANPACE 自有代码另行授予 GPL；若以后分发 Poppler 或改为链接其库，应重新核验相应分发与组合条件。

本软件的可选本地工程环境使用 FreeImage 开源图像库，详见 [FreeImage](https://freeimage.sourceforge.io/)。当前本机库为 FreeImage **3.18.0**，按 **FreeImage Public License 1.0（FIPL）** 说明。LibRaw **0.21.3-Release** 提供 LGPL-2.1 或 CDDL-1.0 选项；相关全文和版权文件已经保留。上述声明不会将 FreeImage/LibRaw 改成 Apache，也不表示任意原生 wheel 都已经完成再分发核验。

当前 OCP wheel 的完整对应构建源码、补丁及可选 LibRaw GPL demosaic 包配置尚未完全闭合。**通用源码包不含这些原生 wheel/库。** 如果以后把本机环境或原生库一起打成安装包，需要先完成 [原生分发核验记录](licenses/engineering/embedded-native-distribution-audit.md) 中的事项。

默认 OCR 模型仅使用以下两个已锁定版本，不会把未选用的 server 模型当作当前功能依赖：

- `PP-OCRv5_mobile_det`：`0d63e78e2b680928f6b1747d76a08db6e645efb7`。
- `PP-OCRv5_mobile_rec`：`682f20538d8c086cb2128e5cfac775e6c4904e85`。

两者的官方模型卡、许可声明和文件哈希分别见 `licenses/engineering/PP-OCRv5_mobile_*-MODEL-CARD.md`、`licenses/engineering/model-manifest.json`。安装器下载的是模型，运行时处理的是本厂授权资料，两者不是同一类内容；客户资料不因此成为开源训练数据。

## 固件与完整清单

硬件的芯片 SDK、显示库、ESP32 固件与位图字体请同时保留 [固件第三方声明](firmware/goldenmorning-display/THIRD_PARTY_NOTICES.md) 及其许可证目录。固件的来源/构建材料要求以该专门清单为准；本页不把整块固件概括为 Apache 或 MIT。

机器可读清单见 [third-party-components.json](third-party-components.json)，分发人员操作说明见 [开源使用与分发要求](docs/open-source/开源使用与分发要求.md)。商业销售是许可允许的使用方式之一，但须持续满足版权、通知、源码提供、可替换性等适用条件；没有购买第三方商标或作者背书。

## 2026-10-04 Web 升级新增与实际运行时

原生 PDF 解析新增 pypdfium2 **4.30.0**，本次 CPU wheel 内嵌 PDFium **126.0.6462.0**。wrapper 为 Apache-2.0 或 BSD-3-Clause，内嵌 PDFium 含独立第三方许可，文档为 CC-BY-4.0；按实际 wheel 的 `dep5-wheel` 与 `LicenseRef-PdfiumThirdParty.txt` 保留声明。完整五份许可/版权材料及 SHA-256 在 `docs/upgrade/runtime-licenses/optimization/`；不能仅以 wrapper 的 Apache/MIT 标记覆盖整个二进制。

OR-Tools 9.15.6755、LangGraph 1.2.11 与 SQLite checkpoint 3.1.1 本次在独立 CPU 环境实际安装/验收；两套传递依赖 freeze、官方下载 artifact hash 与许可证归档见 `docs/upgrade/runtime-locks/`、`docs/upgrade/runtime-licenses/`。它们没有随源码包分发，云镜像应按目标系统重新解析/冻结和留存许可，不能复制本次 macOS 环境。

Docling 可选 worker 固定 **2.133.0**，完整上游 MIT 文本/来源 hash 在 `licenses/web-upgrade/docling-2.133.0/`。[固定版本上游许可](https://github.com/docling-project/docling/blob/v2.133.0/LICENSE)允许符合条款的商业使用；本次未安装 Docling 依赖或下载模型。布局、OCR、表格模型及 worker 传递依赖仍需按实际选定 revision 完成审核，不由 Docling 代码的 MIT 自动授权。PP-OCR server 与 PaddleOCR-VL 目前只交付服务接入协议，不随附新权重。

新增前端为本项目自有代码和既有系统字体/图标，没有引入外部商业素材。完整界面升级没有改变 KANPACE 自有代码许可。

Web CPU 运行时另固定 Pillow **12.3.0**，用于原件图片校验、图像/资料预览和安全编码/解码。MIT-CMU 与随 wheel 合订的图像编解码库许可全文已存于 `docs/upgrade/runtime-licenses/optimization/`。此前仅有基础 Web 环境而未安装 Pillow 时，完整图片流程不能使用；本版将它纳入 Web 运行时入口，不需要安装 USB 库或接入硬件。
