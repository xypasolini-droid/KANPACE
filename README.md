# KANPACE Web 订单工作流

2026-10-04 软件升级版。浏览器按同一订单的当前工程版本操作：**上传资料 → 识别与结构化 → 归属与构件核对 → 可选几何核对 → 工种与工艺 → 物料与排料 → 周期与关键路径 → 有限资源排程 → 复核与正式采用 → 执行与追溯**。

新入口：`/factory/index.html#page=workflow`。原有拆单、物料、排程、任务和经营功能保持原业务 API，并由十步入口链接到具体操作页面。状态由实际记录计算，原件换版、未知时长、未审核构件、缺料与未发布任务会明确提示需要处理的事项。

## 开发预览

需要 Python 3.10+；推荐按运行时说明使用 Python 3.12。基础服务使用标准库和 SQLite，不依赖前端构建工具。

```bash
python3 app.py --port 8788 --data-dir work/preview-data
```

在浏览器打开 `http://127.0.0.1:8788/factory/index.html#page=workflow`。默认有明确标识的演示数据。正式数据使用独立目录和 `--no-demo`。不要将本次合成测试目录或演示项目迁入生产。

## Web 服务模式

先在服务器 loopback 初始化管理员：启动不带 public origin 的服务，在服务器本机或经 SSH 转发访问已有账号初始化页面，完成 `/api/access/setup`；然后停止并使用明确的 HTTPS origin 启动：

```bash
python3 app.py --no-demo --port 8765 --listen 127.0.0.1 \
  --public-origin https://kanpace.example.com --data-dir /srv/kanpace/data
```

HTTPS 由反向代理处理，代理须保留精确 `Host`。Web 模式要求认证和有效管理员，Cookie 使用 Secure/HttpOnly/SameSite=Strict；写入要求准确的 Origin。默认 loopback 足以供同机反代。显式 `--listen 0.0.0.0` 也必须满足 HTTPS origin 和认证条件；代理头不能绕过来源检查。示例域名须替换为实际域名。

云服务器部署、TLS、数据库迁移、备份、容量压测和 GPU 模型部署由部署阶段完成。本版仍使用现有 SQLite 业务存储；没有实现 PostgreSQL/Temporal 替换，也不把单机线程服务声明为已完成 10–30 人生产验收。浏览器无需安装识别或优化引擎，计算在服务器端完成。

## 统一识别与来源

真实原生文本、CSV、TSV、XLSX、JSON、PDF 解析产生 `DocumentEvidenceV1`，保留原文、文件哈希、文件版本、页码与真实原页位置。扫描 PDF 缺少文字时提示需要 OCR；识别不直接发布生产 BOM。

识别任务保存不可变原件副本和逐文档检查点，刷新或重启后可以查看、继续未完成资料。Docling、PP-OCR、PaddleOCR-VL 使用服务器配置的固定版本 worker；服务实际就绪后才启用。协议、模型版本和坐标边界经过独立核验，不能用模型输出的 approved 绕过人工审核。

- [识别 API、worker 协议与坐标约定](docs/document-recognition.md)
- [识别服务配置示例](config/recognition-services.example.json)
- [本次升级实现及验证](docs/upgrade/软件升级实施记录-20261004.md)
- [按操作流程组织的研究与商用许可方案](docs/upgrade/Web云端升级与商用许可方案-2026-10-04.md)

## 验证与许可

Python 测试使用 `python3 -m unittest discover -s tests`，Node 测试在 `tests/*.cjs`。部分真实原生引擎测试要求独立安装运行时、模型或可执行程序；详细结果和真实跳过原因记录在验收文档。

自有软件未新增公众开源授权。第三方许可证、NOTICE、来源记录继续保留，见 [LICENSING.md](LICENSING.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[third-party-components.json](third-party-components.json)。外部服务 manifest 的许可证标识用于追溯，不能替代实际权重和依赖许可审核。

旧版说明保存在 `docs/legacy/`。本次范围为软件和 Web；原有硬件资料属于历史源码，不是本次固件或实板验收。


本次交付范围：当前完整软件与 Web 源码、测试、依赖输入和许可说明。固件及固件编译测试不在软件包内；业务数据库、上传资料、模型、虚拟环境与原机凭据由部署方单独保存。最新文件与清理记录见 `RELEASE-MANIFEST.json`。
