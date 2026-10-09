# KANPACE Web 软件升级交付 · 2026-10-04

本版把订单资料识别、工程复核、物料与排程组织为十步 Web 工作流。浏览器是操作端，识别与求解在服务器运行。用户指定的旧源码交付目录没有修改；本版从兼容源码整合既有修复后单独交付。

## 打开与启动

- 浏览器入口：`/factory/index.html#page=workflow`。
- 开发预览：`python3 app.py --port 8788 --data-dir work/preview-data`。
- CPU 引擎安装：`python3.12 tools/setup_web_runtime.py --install --python python3.12`，再运行 `--check`。
- 使用 PDFium 的 Web 主进程：`.venv-optimization/bin/python app.py --port 8788 --data-dir work/preview-data`。
- 正式 Web 的认证、HTTPS origin、数据目录与反代要求见 [README](README.md)；运行时安装和平台边界见 [cloud-runtime.md](docs/upgrade/cloud-runtime.md)。

源码包不含业务数据库、用户凭据、虚拟环境或模型权重。应在目标云服务器按版本重新安装并验收。开发预览使用合成/演示资料；不得作为正式业务数据库迁入生产。

## 本版实现

| 操作阶段 | 原方案 | 本版实现与实际状态 |
|---|---|---|
| 上传、识别与结构化 | 分散的订单解析和本地工程 OCR 入口 | 统一异步识别 API 与 Web 页面；原生 PDF/清单/表格产生可追溯证据；固定 worker 协议；实际配置就绪才开放模型选项 |
| 归属、构件与几何核对 | 拆单草稿、STEP 核对 | 与订单/文件版本绑定的 EvidenceRef；保留原文、哈希、页码/单元格/坐标；连接既有构件与工程核对页面；本版未重新构建 OCCT |
| 工艺、物料、排料与周期 | 工种规则、物料门槛、PackingSolver、关键路径 | 由真实业务记录计算阶段和待处理事项，沿既有操作完成审核；未知加工尺寸、库存或时长保持待补齐；本版未重新构建 PackingSolver |
| 有限资源排程 | 启发式预览、OR-Tools 接入代码 | OR-Tools CPU 运行时已安装并真实求解；独立验证；引擎不可用或无可行解时启发式分支也经过独立验证且明确标识 |
| 复核、采用与执行 | 工程发布、排程采用、任务报工 | 保留权限、工程版本、采用门槛和开工检查；采用不等于自动开工；旧结果换版失效 |
| 可继续分析 | LangGraph 接入代码 | 真实 SQLite checkpoint 跨进程恢复；确定性分析保留复核中断；未配置通用推理模型 |
| Web 服务边界 | loopback 服务为主 | 显式 Web 模式、HTTPS origin、强制认证、Secure cookie、来源检查、整单查看权限；浏览器无需安装引擎 |

Docling CPU worker 为可部署源码，固定版本 **2.133.0**，使用完整标准 PDF pipeline 和显式 PDFium backend；模型文件哈希、离线目录、认证与真实转换自检决定 ready。本次没有下载模型或运行 Docling 模型准确率验收。PP-OCR server 与 PaddleOCR-VL 目前完成接入协议和配置入口，实际服务/模型部署仍待完成。

## 验收与交付依据

- [软件升级实施记录](docs/upgrade/软件升级实施记录-20261004.md)：源代码来源、实现范围、自动化与浏览器验收、待部署事项。
- [设计与状态矩阵](docs/design/20261004-Web订单工作流-设计与状态.md)。
- [统一识别协议](docs/document-recognition.md) 与 [Docling worker](docs/docling-cpu-worker.md)。
- [运行时实测报告](docs/upgrade/web-runtime-verification.json)、传递依赖版本与 LICENSE/NOTICE 在 `docs/upgrade/`。
- `RELEASE-MANIFEST.json` 和 `SHA256SUMS.txt` 记录本次源码包内容。不是原旧包的清单。

商业许可继续按 [LICENSING](LICENSING.md)、[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) 和机器可读清单执行；模型权重和 Linux 部署镜像的完整依赖应按实际选定版本审核。保留上游声明不能替代所有模型或二进制再分发审核。

本次只升级软件和 Web。本软件包保留设备桥接源代码；不含固件目录、固件二进制或实板验收。


本次交付范围：当前完整软件与 Web 源码、测试、依赖输入和许可说明。固件及固件编译测试不在软件包内；业务数据库、上传资料、模型、虚拟环境与原机凭据由部署方单独保存。最新文件与清理记录见 `RELEASE-MANIFEST.json`。
