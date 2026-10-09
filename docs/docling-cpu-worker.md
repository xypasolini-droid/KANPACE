# 可直接启动的 Docling CPU worker

入口为 `python -m workers.docling_service`，依赖固定在 `requirements-docling-worker.txt`。当前官方可核实版本为 [v2.133.0](https://github.com/docling-project/docling/releases/tag/v2.133.0)，发布于 2026-10-03。本次只完成服务代码、官方 API 核验与协议/边界测试，没有安装 Docling、下载模型或部署实际模型服务，因此尚无模型识别验收结论。

worker 使用完整 `DocumentConverter` 标准 PDF pipeline：布局模型、RapidOCR ONNX 检测/识别/方向模型、TableFormer ACCURATE 与 PDF cell matching；指定 CPU、4 线程与离线 `artifacts_path`。它独立部署，不导入业务 Store，不接受 URL，不访问客户数据目录。[官方离线选项](https://docling-project.github.io/docling/usage/advanced_options/)与[固定版本 API 源码](https://github.com/docling-project/docling/blob/v2.133.0/docling/document_converter.py)支持这一接法。

部署者先在独立 Python 3.12 环境安装固定依赖，并按已审查的模型许可证准备离线目录。安装依赖会获取运行库；运行 worker 不执行模型下载。不要直接使用带外部符号链接的 Hugging Face cache：部署 artifacts 中的文件应为真实文件，并逐项登记。

`config/docling-worker.example.json` 为配置模板。`model_manifest_path` 指向 JSON `{"files":[{"path":"目录内相对文件名","sha256":"64位小写哈希"},...]}`，登记 artifacts 下所有模型/配置文件；模型清单本身放在 artifacts 外。`model_revision` 为整个清单文件字节的 SHA-256，与统一识别服务 manifest 的 model_revision 保持相同。目录中额外文件、缺文件、符号链接和不匹配的哈希都会阻止启动。OCR四条相对路径必须已登记，方向模型不可省略。

服务器环境变量 `KANPACE_DOCLING_WORKER_TOKEN` 至少 32 字符；统一识别调用方使用同一 token 环境变量。凭据只在环境中保存。使用者先运行：

```sh
python -m workers.docling_service --config /srv/kanpace/config/docling-worker.json --drycheck
```

drycheck 只验证配置、文件哈希与固定依赖，不加载模型，输出 `ready:false/models_loaded:false`；依赖缺失会返回退出码 2。检查 HTTP 接线可用 `--no-autoload` 启动，健康接口保持 ready=false，识别返回 503，没有远程加载模型的匿名接口。

准备完成后启动完整服务：

```sh
python -m workers.docling_service --config /srv/kanpace/config/docling-worker.json --port 8091
```

省略 `--no-autoload` 才会加载 pipeline，并实际转换内置 0°/90°原生 PDF 自检。引擎初始化、两个 selftest 的文字/页框都成功后，`/health.ready` 才为 true；失败退出并维持不可用。自检不等于客户中文工程图或复杂表格精度验收。统一识别服务用 `KANPACE_RECOGNITION_SERVICE_CONFIG` 指向 `config/recognition-services.example.json` 的实际部署副本，固定 Docling 2.133.0、相同模型清单 hash、许可证清单标识、token_env 与 URL。

绑定只允许 `127.0.0.1`，所有 `/health` 与 `/recognize` 都要求 Bearer token。默认在同一云服务器运行 Web API 与 worker；跨服务器须通过明确认证的网关/隧道接入，不能把本服务改为公开匿名接口。完整加载时关闭外发 socket连接，并启用 HF/Transformers 离线标志、禁用 Docling remote services，以避免依赖自动取模型。生产服务管理器应另加 CPU、内存、进程期限与文件目录隔离；每次转换有 120 秒 Docling 文档预算，超时/部分结果不标作成功。

坐标使用固定版本的 [PyPdfium backend](https://github.com/docling-project/docling/blob/v2.133.0/docling/backend/pypdfium2_backend.py)，其源码明确将未旋转字框转换至已旋转显示页；PDFium `get_size` 与 render同在显示空间。worker 独立 render核验尺寸，检查原件哈希和请求原页身份/旋转/页面框，再对 prov.bbox 只做 [BOTTOMLEFT→TOPLEFT origin 转换](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/base.py)，不再次旋转。框须正面积、有限且在原页内。非平凡 CropBox/非零 MediaBox origin、多页表格映射或单元格缺真实 bbox 当前明确失败，不猜测框。

服务返回 `kanpace-document-v1` 协议的 `document_evidence.v1` JSON：原样来源身份、固定引擎/modelrevision、pages与regions、表格单元格原文/行列/跨度/区域索引。下游仍是 unreviewed，不能自动生成制造尺寸。SaaS部署与分发的许可义务见项目尽调/第三方清单；worker中的许可证标识不构成法律保证。

验证：`python -m unittest tests.test_docling_worker tests.test_recognition_xlsx tests.test_document_recognition tests.test_order_evidence_refs -q`。测试中的模型字节只是清单安全边界夹具，并未运行或模拟一个已验收模型。实际模型环境需要重新完成启动自检和业务样本验收。
