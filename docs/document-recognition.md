# 统一文档识别：接口与部署协议

实现入口为 `document_recognition.py`。它读取已登记原件的不可变副本，在独立进程中逐份解析并保存检查点。结果为待复核观察，不创建或改写生产 BOM、工序、任务、数量或制造尺寸。上传已有业务行为由原上传接口管理；识别本身不写业务数据库。

## Web API

- `GET /api/projects/{project_id}/recognition`：返回 `{sources,jobs,capabilities,read_only:true}`。来源选择使用 `sources[].source_id`，包括 `doc:<document_id>`；不接受客户端文件路径、服务地址或模型地址。
- `POST /api/projects/{project_id}/recognition`：`{"source_ids":["doc:doc_x"],"expected_revision":3,"options":{"parser":"auto","max_pages":20,"pages":[1,2]}}`。`pages` 可省略，页码为 1 基。202 返回 `{job}`。
- `GET /api/projects/{project_id}/recognition/{job_id}`：返回 `{job}`，持久结果在 `job.result`，所有文字区域在 `job.result.evidence_refs`；可检查 `job.source_integrity.current` 与 `issues`。
- 续跑同一 POST：`{"resume_job_id":"rec_...","expected_revision":3}`；不得另给来源或选项。只允许 `interrupted/partial/failed`，当前来源哈希/版本必须仍匹配。

状态：`queued/running/completed/partial/failed/interrupted`。`completed` 仅表示选定原件解析结束；`result.documents[].result.completeness` 和 warnings 仍决定是否限页、扫描件缺字或需要复核。完成状态不代表订单资料完整或生产可发布。结果固定 `review_status:"unreviewed"`、`read_only:true`、`manufacturing_release:false`。

`parser` 支持 `auto/native/docling/paddleocr/paddleocr_vl`。`auto` 对文本/CSV/TSV/JSON 使用原生解析，对 PDF 优先使用任务提交时健康且已固定版本的 Docling worker，否则选择 PDFium/Poppler；图像只有已配置健康模型 worker 时可识别。显式模型选项未就绪时返回 503。包已安装与模型可执行分开显示，前端应以 `available` 决定是否启用。

## 已实际可运行的本机路径

UTF-8/GB18030 文本、CSV/TSV 和 JSON 均真实解析，保留引号、多行单元格、原字符串和 JSON 类型。重复 JSON 键拒绝处理，避免静默覆盖；CSV 重复表头/列数不一致明确产生冲突。XLSX 使用有界 OOXML ZIP/XML 原生解析：共享/内联/富文本字符串、原数字文本、布尔、单元格地址与合并跨度均保留；公式保留原文而不计算，缓存值不作为制造值。禁止DTD/实体、外部关系、宏、目录穿越、重复单元格和异常压缩；证据 table_cell 按工作表定位，page为null，无虚构PDF框。XLSX请求须省略pages。

PDF 使用已安装的 PDFium；旋转、非平凡 CropBox、异常字符框时进入 Poppler fallback。Poppler 调用 `pdftotext -bbox-layout`，独立 `pdfinfo -box` 核验 MediaBox、CropBox 与旋转。Poppler XML 对旋转页报告的尺寸与词框空间不同，服务已将显示页尺寸按旋转交换并保留原始页面框。扫描 PDF 没有原生文字时返回 `ocr_required`，不会补造识别内容。

系统 Python 原验证环境有 Poppler，未安装 PDFium/Docling；Web 主进程的 `.venv-optimization` 已用真实 PDFium 4.30.0 验证原生异步识别、关闭文件后重试、持久任务续跑及旋转 Poppler fallback。PDFium 文档、页和文字对象使用显式 try/finally.close，兼容4.30缺少上下文管理器的API。当前仍未配置 Docling、PP-OCR、PaddleOCR-VL 实际模型服务，其能力状态为不可用。远端协议已经实现并通过真实 HTTP 传输测试，但协议测试服务器不运行任何模型，不能作为模型识别能力或精度证据。

## 可信云 worker 配置

服务器设置 `KANPACE_RECOGNITION_SERVICE_CONFIG` 为绝对 JSON 路径，参考 `config/recognition-services.example.json`。文件必须由服务器管理员配置；普通用户请求不可指定该路径/URL。每个服务固定协议、引擎版本、模型 revision、许可证标识和超时（1–180 秒）。凭据通过 `token_env` 指向环境变量，不写入 API 响应。许可证标识用于审计，不能替代逐组件商用许可确认。项目已提供 `workers/docling_service.py` 可启动真实 CPU worker，详见 `docs/docling-cpu-worker.md`；仍需另行准备已审查离线模型，当前没有声称已部署。

服务实现两个端点。`GET /health` 在 2 秒预算内返回 `{"ready":true,"schema_version":"document_evidence.v1","engine_version":"固定值","model_revision":"固定值"}`，必须与 manifest 一致才会展示可用。ready 必须由 worker 在模型加载成功后设置。

`POST /recognize` 接收 `protocol:"kanpace-document-v1"`、`source`（document_id/source_id/source_sha256/source_revision/source_role/source_page）、`input:{filename,content_base64}`、`options`、`source_geometry`、`required_engine_version`、`required_model_revision`。服务应再次验证输入哈希，执行真实完整 pipeline，并将模型原坐标变换到 `source_geometry` 规定的原页坐标。模型不能提供可靠坐标时应返回失败，不能猜测框。

返回 JSON：`schema_version:"document_evidence.v1"`、原样 `source`、固定 `engine_version/model_revision`、`pages`、可选 `tables`。每页保留原几何字段并加入 `regions:[{text_raw,bbox_pdf_points}]`；单图像使用 `bbox_pixels` 与 `page_size_pixels`，坐标单位 `pixels`，不得伪装为 PDF 点。服务端校验来源/哈希/版本、正面积框、有限坐标、边界、页号、原页尺寸、旋转和坐标空间守恒。

可选表格形状：`tables:[{id,page,cells:[{row,column,row_span,col_span,text_raw,region_indices:[0]}]}]`，均为 1 基行列，`region_indices` 为本页 regions 的 0 基索引。应用层生成 evidence_id 并绑定表格单元格，不信任模型生成的证据 ID。工程图尺寸与构件的关联仍为待复核候选，不由文字自动推导加工工艺。

HTTP 端点禁止重定向，忽略环境代理；只有管理员 manifest 指定的目标可接收原件。输入单份上限 100 MB，文本/响应上限 20 MB，单任务 20 份来源、1–100 页、20000 个区域；并行识别进程上限 2、进程运行上限 900 秒。多文档长任务可利用检查点续跑；生产云端应另行配置 worker 身份认证、网段隔离、资源限额与反向代理上传限制。

## 坐标与证据

PDF locator 示例：`{kind:"pdf_region",page:1,page_size_pdf_points:[100,200],bbox_pdf_points:[47.516,20,58.616,40.016],rotation:90,mediabox:[0,0,200,100],cropbox:[0,0,200,100],crop_to_page_transform:null,canonical_origin:"top_left",coordinate_system:"pdf_points",coordinate_space:"pdf_media_display_page"}`。显示尺寸包含旋转；框为左上原点，单位为 PDF 点。共享 normalizer 兼容 `bbox/origin` 别名。

CSV 为 `table_cell`，JSON 为 `json_pointer`，文字为 `text_line`，无真实几何则 bbox/page_size 为 null。图像为 `image_region`，保留 pixels 字段；原页图像缺少 PDF映射时 PDF点字段为 null。`candidate.field/value` 是原值观察，`unit` 未知为 null，`subject_candidates` 为空，不填猜测主体。保留 `evidence_id/document_id/source_sha256/source_revision/source_role/method/engine_version/model_revision`，不能由客户端设置 approved。

作业存储于 `data_dir/recognition-jobs/rec_<uuid>/`：`job.json` 小摘要、原件私有副本、`process.json`、逐文档 `document-N.json` 检查点、`result.json`、`worker.log`。读取单条会检测失联进程并报告 interrupted；轻量列表不启动进程、不修复、不探测模型。原件或项目版本改变时历史结果仍可读，但 `source_integrity` 明确标为过期，不能续跑混用。模型/许可证固定值变更同样不能在原任务中混用。

验证命令：`python3 -m unittest tests.test_document_recognition tests.test_order_evidence_refs tests.test_intelligence_http tests.test_workflow_projection -q`。模型实际部署后仍需用真实授权柜体清单/扫描图/旋转页/合并单元格/尺寸符号集进行逐字段、逐原页框和完整性验收；此次未验证模型精度。
