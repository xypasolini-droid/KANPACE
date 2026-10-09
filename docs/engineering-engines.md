# KANPACE 本地工程引擎

这部分给现有 Web 提供真实扫描图文字识别和源 STEP 几何核对。它不改订单、构件审批、生产任务或报价。服务器只向引擎提交当前用户有权读取的项目文件；识别结果仍需技术员复核。

## 安装和复现

专属环境是项目根目录 `.venv-engineering`。应用原来的 `.venv` 和系统 Python 不安装这些依赖。

```sh
python3 tools/setup_engineering.py --python /path/to/python3.12
```

需要安装 `uv` 和 Python 3.12。本次完整锁包含要求 Python 3.12 的 NumPy 2.5.3，未承诺该锁可用于 Python 3.11。首次安装下载依赖与公开的百度模型，不读取客户图纸。若已有环境，只下载模型：

```sh
python3 tools/setup_engineering.py --models-only
```

选用的兼容基线为 PaddleOCR 3.3.2、PaddlePaddle 3.2.2、PP-OCRv5_mobile_det / PP-OCRv5_mobile_rec，以及 cadquery-ocp 7.8.1.1.post1。它们不是上游最新版本；该基线用于本机原生运行和可重复验证，后续版本升级应重跑实际图纸回归。当前 8 GB Mac 使用 mobile 模型和单 CPU 线程；server 模型在当前内存负载下出现严重换页，未纳入可用默认配置。模型体积与推理成本的取舍不代表已经测得真实订单上的识别准确率。

`requirements-engineering.txt` 固定直接依赖；安装验证后生成的 `requirements-engineering.lock.txt` 固定完整依赖。模型保存在 `models/engineering`，其中 `manifest.json` 记录官方仓库、确切 revision、许可证和文件 SHA256。下载时核验官方 LFS SHA256，执行 OCR 前再次校验本地模型摘要。

公开模型文件可随本地交付放置到相同位置。已下载模型后，客户处理任务不需要联网，不会自动尝试下载缺失模型。缺模型会返回明确失败，可由管理员运行安装命令恢复。

## API 模块契约

服务器使用 Python 标准库导入 `engineering_engines`，不在 HTTP 进程加载 Paddle 或 OCCT。

```python
from engineering_engines import EngineeringJobs

jobs = EngineeringJobs(store.data_dir)
job = jobs.submit(
    kind='ocr',
    source_path=store.uploads / document['storage_name'],
    filename=document['filename'],
    options={'pages': [1, 2], 'dpi': 144},
    metadata={'project_id': project['id'], 'document_id': document['id'],
              'revision': document['revision']},
)
# 返回 queued/running，可轮询；completed 才包含 result。
state = jobs.get(job['id'])
capabilities = jobs.status()
```

`kind='cad'` 支持 STEP/STP，options 为空。OCR 支持 PDF、PNG、JPEG、WebP、TIFF、BMP。PDF 默认前 12 页，可显式选 1—12 个页码；默认 144 DPI，可选 96—300。100 MB 文件限制、每页 2400 万像素限制和 5000 个 CAD 节点限制均有明确错误。每工厂同时最多 2 个任务，单 worker 最长 15 分钟。

原页缓存图可保留其原 PDF 页码：metadata 使用 `source_page` 正整数和 `source_label` 字符串。图片内部 page 仍从 1 开始，额外的 `source_page` 指向真正工程图来源，二者不混用。

输出目录为当前工厂 `engineering-jobs/eng_<随机ID>/`。记录包含 source 文件名、SHA256、任务状态、进度、实际引擎版本、原始结果。原件复制后处理，避免活文件在识别中被版本更新改变。`result.json`、页图和日志都留在该工厂目录。HTTP 接口应检查 job.metadata.project_id / document_id，再受控输出 result 和 page-N.jpg；不能直接开放整个任务目录或 worker.log。

OCR 页结构包含 width/height、preview_filename、regions。每段文字保存 text、score、polygon、bbox、bbox_normalized、page、review_status。bbox 以左上角为原点，单位为像素；PDF 另附 bbox_pdf_points。score 是模型识别分数，不是尺寸正确率。`is_manufacturing_dimension=false`，未确认的 OCR 结果不会成为加工尺寸。

CAD 结果包含装配节点、源定义 ID、实例路径、实例数量、有效性、面数、面积、体积和世界坐标外包范围。统一输出 mm、mm²、mm³，并保留源长度单位。相同定义的多个实例会分别计数；不同定义即使外形一样也不会自动合并。材料、密度和重量当前留空，PMI 尚未解析。外包尺寸明确不是下料尺寸；OCCT 单独不提供自动制造 BOM 或工种分配。

原生 SLDPRT/SLDASM 继续使用安装了 SolidWorks 的 Windows 导出桥接，输出 STEP 后才能送入此检查器。不把网格轮廓重建成假工程实体。

## 本地隔离

提交源必须在当前工厂目录内，拒绝其中的符号链接和跨工厂路径。客户端不能提供 source_path；HTTP 层根据已鉴权 document_id 或项目媒体白名单解析源。元数据仅接受文档/项目/版本、source_id 来源白名单标识与页码标签字段。

每个 job 启动独立原生 worker，模型只读共享，客户输入、页图、结果、缓存和日志按工厂分开。worker 不继承 API 密钥、代理令牌或用户登录模型凭据。macOS 使用 `sandbox-exec` 禁止网络，并限制用户主目录、外接卷和当前工厂父目录内的读取：仅允许工程运行库、公开模型、本任务目录和 worker 程序；相同受保护区域仅本任务目录可写。系统库和系统字体等区域保持可读。Python 层同时拒绝 socket 连接/数据报，并关闭 Hugging Face 联网与遥测。其他操作系统保留 Python 网络拒绝和离线配置；正式服务应额外使用操作系统或容器网络策略。这里不是对本机管理员的文件访问隔离。

## 验证

```sh
.venv-engineering/bin/python -m unittest tests.test_engineering_engines -v
```

测试只在临时两工厂目录中生成资料：

- Raster-only 中文扫描 PDF，选第 2 页，用真实 PaddleOCR 核对“柜体”、600、450 与坐标、页码、置信分数。
- 真实 OCCT 生成并重新读入 STEP：同一 10×20×30 mm 实体的 2 个装配实例，期望总面积 4400 mm²、总体积 12000 mm³；另生成长度单位为 inch、坐标为 10×20×30 的实体，验证两实例总体积换算为 196644768 mm³。
- 非法 STEP 失败，不伪造几何；原生 SolidWorks 提示使用桥接。
- 跨工厂源、跨工厂 job、符号链接与无效页码拒绝。

测试结果和安装版本记录见本次工程引擎验收记录。合成样例证明引擎实际参与，不代表已经测出客户全部施工图的正确率。

## 商用许可与来源

PaddleOCR、PaddlePaddle 代码及本次精确选用的两个 PP-OCRv5 模型均为 Apache-2.0。保留适用许可、版权/NOTICE 和修改说明。未启用方向、表格、VL 等其他模型，不能用此结论覆盖以后添加的组件。

CadQuery/OCP 的包装器许可证和内嵌 Open CASCADE 许可证需要分别保留。本次实际安装的 7.8.1.1.post1 wheel 内 cadquery_ocp/LICENSE 为 Apache-2.0；OCCT 是 LGPL-2.1 加 OCCT 例外，不能把整个 wheel 标成 Apache。分发需提供对应库源码/修改和适用的替换或重新链接材料；若选商业许可另按协议履行。当前 KANPACE 使用独立可替换的后端环境，没有修改这些原生库。

依赖中的 VTK、图像和数学库也有自己的许可。逐包已安装许可证清单、直接依赖许可正文和模型卡存放在 `licenses/engineering`；对应源代码/发布地址记录在其中。

OCP wheel 另包含 FreeImage 3.18.0、LibRaw 0.21.3 等原生库。两者版本由实际动态库 API 核验；FreeImage 提供 FIPL 商业使用路径，标准 LibRaw 可选 LGPL-2.1 或 CDDL-1.0。对应许可正文已补归档。当前本地安装可用于评估和实际工作；本轮没有交付一份已完成原生库分发义务的商业二进制包。对外分发前仍须补齐完整原生依赖声明、选定许可、匹配实际 wheel 的对应源码与构建材料，以及替换/重新链接和源码获取安排。仅下载 stock FreeImage 3.18.0 源包不足以证明与本 wheel 对应；原生可选扩展的构建配置也未获完整证明。详见 `work/engineering-license-audit/embedded-freeimage-libraw-audit.md`。

官方参考：

- https://github.com/PaddlePaddle/PaddleOCR
- https://www.paddleocr.ai/main/en/version3.x/installation.html
- https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det
- https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_rec
- https://github.com/CadQuery/OCP
- https://github.com/Open-Cascade-SAS/OCCT
- https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html
