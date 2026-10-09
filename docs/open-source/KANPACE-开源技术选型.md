# KANPACE 开源技术选型与接入建议

研究日：2026-09-06，America/New_York。部分上游取证时间为 UTC 2026-09-07。

本轮围绕现有 KANPACE，整理 **72 个候选与对照条目、37 项重要功能**。条目包含单个项目、组合技术栈，以及不适合默认集成的附条件/商业对照项；不能把 72 条统称为 72 个无条件可商用的开源软件。本报告是官方资料核验与工程选型，尚未安装或运行候选项目，未修改正式订单数据或烧写设备。

**建议保留现有 Web、Python 业务服务、真实图纸与工牌基础。优先引入成熟的文档解析、约束求解、图表和通信组件。** 生产规则、来源证据、图纸变更、暂停插单、物料质量放行及实际成本继续由 KANPACE 统一管理。OSS 能缩短通用技术开发，不能替代对工厂规则与真实订单的验证。

## 用户指定：omniverse-cad-to-usd 能用在哪里

**能用，适合作为原生 CAD 到装配可视化资产的补充转换节点。** 官方确有 [NVIDIA omniverse-cad-to-usd skill](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/SKILL.md)。当前 v0.2.0 采用独立 Python 3.12 wheel，不要求安装 Omniverse Kit。已读取 skill，并按其要求核验格式、平台、数据映射与限制；没有执行安装或转换。

它读取 STEP、SLDPRT、SLDASM 等真实文件，输出 USD/USDA/USDC。可以保留已读取的装配层级、实例、零件显示名、变换、材质/颜色及按选项导出的元数据。对 KANPACE 的价值，是把真实柜体或设备装配组织成可选择的部件，再关联工程清单与工种任务。它输出三角网格，不保留完整 CAD 参数/配合、可视或可编辑 PMI；抑制零件、缺少引用与过滤选项会影响结果。当前映射也不写 UV 坐标，因此不能承诺原效果材质/贴图完全复现。[官方映射](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/docs/concept_mapping.md)

官方 wheel 支持 Windows x86_64、Linux x86_64/aarch64，**没有 macOS 包**。Linux aarch64 还不支持该转换器的 AutoCAD DWG/DXF 和 Revit 读取。当前 Mac 上的 KANPACE 可以继续运行，将转换发给合适的自有 Windows/Linux 节点。转换器自己不输出 GLB；保留 Three.js 时，需另验证 USD→GLB/网页网格适配与部件 ID 映射。[实际 wheel 索引](https://pypi.nvidia.com/usd-convert-cad/)、[限制说明](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LIMITATIONS.md)

许可证分层：skill 代码 Apache-2.0、文档 CC-BY-4.0；实际转换运行时受 NVIDIA 协议约束，并包含专有 HOOPS Exchange。公开 skill 不能视为整个转换器全开源。Kitless 技术要求没有列 RTX 型号，但 NVIDIA 专有组件条款仍有 NVIDIA Platforms 条件；生产部署与随产品分发前，须按选定包与使用方式核对权益。不能仅由可下载推断可无条件商用，也没有依据断言一定需要另购 HOOPS。[技能许可](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/LICENSE.md)、[运行时许可](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LICENSE.md)、[第三方声明](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/THIRD_PARTY_NOTICES.md)、[NVIDIA 产品条款](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/)

建议试验链路：真实 CAD 装配与全部引用 → 隔离转换作业 → USD 场景与源 ID 清单 → 网页资产适配 → 部件关联工程 BOM → 技术员确认 → 工种任务。效果图继续用来展示真实设计外观；不能用此技能从效果图恢复加工尺寸、孔位、公差或工艺。先验收层级/实例数量、隐藏件、材质与贴图丢失、毫米/米与坐标轴、缺失引用和任务回链，再决定接入。

## 建议采用的组合

| KANPACE 能力 | 第一选择 | 借用方式 | 仍需掌握的业务部分 |
|---|---|---|---|
| 施工图查看、原文定位 | PDF.js + 现有后端渲染 | 本地浏览器库 | 字段→页区→版本→任务追溯 |
| DXF、扫描图、清单 | ezdxf + PaddleOCR + Docling | Python 后端工作进程，OCR待核 | 单位、数量、尺寸、材料与冲突复核 |
| 真实3D与几何 | 已有 Three.js / occt-import-js，按需 FreeCAD/OCCT | 保留现有查看，精确几何后置 | 部件与工程清单映射，禁止伪造模型依据 |
| 原生多CAD格式补充 | omniverse-cad-to-usd | 合适的 Windows/Linux 转换节点 | 专有依赖与平台条件，USD网页适配 |
| 工艺模板、串并联 | diagram-js 或 bpmn-js | 可视化工艺编辑器 | 工种、输入/输出、放行、冻结版本；编辑器不是引擎 |
| 有限产能排程 | OR-Tools + Frappe Gantt | Python 求解＋网页展示 | 工时、班次、物料、双资源、暂停/插单与冻结任务 |
| 板材/型材排料 | PackingSolver | 先一维和矩形 CLI 试验 | 已确认尺寸、纹理、切缝、余料、机床约束 |
| 物料、质量、外协 | ERPNext / Tryton / InvenTree | 参考成熟单据模型，按客户对接 | 主数据归属、齐套、返工、批次序列与放行 |
| 客户 Excel 互联 | openpyxl | 保留原件，映射预览后提交 | 公式缓存/日期/合并单元格、原单号、导入幂等 |
| ERP/设备接口 | Node-RED + 统一业务 API | 独立适配器 | 来源、权限、重试、对账与业务事务 |
| 老板 BI | ECharts；按需 Superset | 先轻量图表，后自助分析 | 准交、等待、返工、实付/预计成本和回款口径 |
| 工牌屏幕与图片 | 沿用 Arduino/Adafruit；按需 LVGL | 优先实测现界面，避免只为换库重写 | 当前任务、图册、暂停/继续的最少操作 |
| 无线与回执 | ESP-MQTT + Mosquitto + 主机Paho | MQTT传输层 | event_id、持久队列、事务ACK和任务版本 |
| USB升级与OTA | esptool；官方 IDF OTA 后期 | 保留已验证USB；OTA先做分区预算 | 图片/字体/配置保留、启动自检和失败恢复 |
| 工位扫码与语音备注 | ZXing + 主机 whisper.cpp | 手机/工位主机 | 任务/物料/批次绑定，语音只做待确认备注 |
| 机台数据 | open62541 / PyModbus | 现场主机网关 | 设备字典、质量码、计数归属；遥测不是完工证据 |
| AI与历史知识 | LangGraph + Ollama + Qdrant | 按需拆单建议/知识检索 | 证据完整度、人工确认、实际结果反馈 |
| Agent接口 | 官方 MCP Python SDK | 与CLI/Web复用业务服务 | 不绕过发布/授权/幂等与版本门槛 |
| 可靠性和规模 | Playwright；按需 Dexie/Workbox、PostgreSQL、Keycloak、OTel | 先验收，出现需求再扩平台 | 单一业务事件队列、事务、对象权限和生产审计 |

以上是工程选择摘要。各项目的能力、许可证与维护证据见后文逐项档案，表中“第一选择”不代表已通过 KANPACE 实测。

## 三个场景共用什么、分别配置什么

| 场景 | 工作对象 | 关键门槛 | 老板愿意付费的结果 |
|---|---|---|---|
| 展柜工厂 | 柜号、部件、包装箱 | 木作/金属/玻璃/灯光齐套，表面处理等待，装配与装箱核对 | 少错版、少漏件补发，及时知道缺料和迟交责任 |
| 非标机械装配 | 单机序列号、子装配、测试项 | 关键件实装与批次记录，通电/联调/测试放行 | 单机成本与进度可追，故障定位和验收资料完整 |
| 装修/工程现场 | 项目、区域、楼层、作业面 | 材料到场、上道移交、隐蔽验收、变更签认 | 班组少空等，变更不漏算，验收与收款节点清楚 |

共用订单、工程版本、工序依赖、资源/班次、事件、异常、质量、成本和交付机制；按模板配置对象、工种、门槛、表单和统计。不能用一个状态标签掩盖三类现场不同的放行要求。

## 四组最值得先做的验证

这些是建议的下一步验证计划，本轮没有执行，时间需按真实样本和设备条件估计。

1. **图纸到任务的可追溯拆解。** 用台湾珠宝柜项目与另一份施工图，技术员先独立给出标准清单；对比 PDF.js/ezdxf/PaddleOCR/Docling 的读取结果。记录漏项、错数量、缺单位和错误来源；重复原图不增加需求数量，未知字段保持待核。发布任务必须回到正确图纸版本。真实 STEP/SolidWorks 装配单独检查实例数量、层级和材质，不拿截图模型替代。
2. **生产排程表回放。** 使用真实 Excel、班次、工作中心和工时，比较现有排程与 OR-Tools：正常、缺料、人员请假、紧急插单、任务做到一半切换、改图返工。硬约束冲突必须为零；记录逾期、换线、等待和计划改动，不只比较甘特图是否好看。设置求解时限，对不可行/未知给出可解释结果并保留当前排程回退。
3. **工牌上的完整工作动作。** 真实工人完成看图→开工→部分报量→缺料暂停→切单→恢复→完工。分别验证 USB、无线断连、重复回执、重启/掉电和图册版本，检查服务器不重复计件。保持当前4MB板的可靠USB升级路径；双槽OTA先核算镜像/字体/图片/配置占用。
4. **Excel互联与老板收益。** 对照客户原单据预览字段映射、冲突和重复导入；检查成本、交期、质量和回款数字可追到来源。记录每张订单拆单时间、每次催问时间、等待时长、返工/补发费用、数据对账差异、首次配置和月支持工时。管理时间节省与现金利润分开计量。

## 关键选型纠错

- **frePPLe CE 当前为 MIT。** 8.0.0 起已从 AGPL 变更；仍需区分 CE 与商业版的交互甘特、交期报价、换型优化等。[官方许可](https://frepple.com/docs/current/license.php)、[版别](https://frepple.com/editions/)
- **Timefold Python beta 已停止主动开发。** 如果选它，应按 Java/Kotlin 外挂求解服务评估，当前 Python 后端优先 OR-Tools。[官方公告](https://github.com/TimefoldAI/timefold-solver/discussions/1698)
- **occt-import-js 是 LGPL-2.1；Deepnest 包含 GPLv3 组件。** 不能只看首页某处 MIT 就给整个技术栈贴同一个标签。[occt-import-js许可](https://github.com/kovacsv/occt-import-js/blob/main/LICENSE.md)、[Deepnest组件表](https://github.com/deepnest-next/deepnest/blob/main/LICENSES.md)
- **bpmn-js 有可见水印许可要求，diagram-js 为 MIT。** 两者都不自动执行生产业务流程。[bpmn-js许可](https://github.com/bpmn-io/bpmn-js/blob/develop/LICENSE)、[diagram-js许可](https://github.com/bpmn-io/diagram-js/blob/develop/LICENSE)
- **EMQX 5.9+ 为 BSL1.1，旧5.8开源版已EOL；n8n不是OSI开源。** 它们可以作为客户现有系统，但不列为默认无限制分发底座。[EMQX许可](https://github.com/emqx/emqx/blob/master/LICENSE)、[EOL公告](https://www.emqx.com/en/news/a-notice-on-the-emqx-5-8-open-source-version)、[n8n许可说明](https://docs.n8n.io/sustainable-use-license/)
- **Univer 的核心与 Pro、Odoo CE 与高级制造、qcadoo CE 与商业 API 均须拆开。** 免费打开项目源码不代表所需的高级功能免费。[Univer导入导出](https://docs.univer.ai/guides/sheets/features/import-export)、[Odoo版别](https://www.odoo.com/page/editions)、[qcadoo官方仓库](https://github.com/qcadoo/mes)
- **本板不能仅因为写着 ESP32 就套用全部示例。** C3 的4MB分区、RAM和SDK版本限制需要逐项验证；新 ESP-MQTT/LVGL配套组件有 IDF 版本门槛。[ESP-MQTT依赖](https://github.com/espressif/esp-mqtt/blob/master/idf_component.yml)、[C3 OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/system/ota.html)
- **本地Web可运行不等于手机网页具备离线同步。** 手机入口需要局域网部署与认证；Service Worker 需要可信来源。Workbox 先管静态缓存，Dexie 管唯一业务队列。[Service Worker要求](https://www.w3.org/TR/service-workers/#register)、[Workbox后台同步](https://developer.chrome.com/docs/workbox/modules/workbox-background-sync)

许可证影响取决于选定版本、修改与分发方式。GPL/LGPL/AGPL 并不等于不能商用；本报告也不把它们概括为一律要求公开全部业务代码。选定依赖后需要固定版本、保留许可/NOTICE、核验组件与模型，并按实际部署方式完成许可确认。

## KANPACE 应形成的核心积累

价值集中在“工程资料 → 构件 → 工艺 → 工人动作 → 实际成本与交付”的连续数据：同一零件来自哪版图、由谁确认、工艺为什么这样走、缺什么料、做了一半怎样恢复、实际花了多久、返工因为什么。成熟开源项目提供通用技术，但这些可追溯的规则、复核记录、真实工时与客户模板需要 KANPACE 自己沉淀。

客户继续用 Excel 或已有 ERP 管理熟悉的主数据；每个字段约定权威来源，KANPACE 提升现场执行和工程到生产的联动。一个新工厂应主要通过模板、字段映射、工种/资源与门槛配置接入，持续衡量配置工时和定制代码量，不能靠复制一套分叉代码维持三个行业。

## 研究方法与边界

使用 `modern-web-guidance` 的 search、list 和 guide 获取前端性能与 WebMCP 指导；通用指南适合帮助设计，CAD/制造能力仍以项目官方源码和文档核验。指南中部分 WebMCP 状态已被新官方资料替代：Chrome149在2026-06开始Origin Trial，9月官方资料仍有试验条件。因此 WebMCP 作为浏览器增强候选，核心互联继续使用稳定 HTTP/CLI 与官方 MCP SDK。[Chrome公告](https://developer.chrome.com/blog/ai-webmcp-origin-trial)、[WebMCP官方说明](https://developer.chrome.com/docs/ai/webmcp/secure-tools)

本轮核验仓库、LICENSE、逐组件许可、指定模型卡、官方功能文档、release/commit记录；不按星数直接排序成熟度。遇到 GitHub API 字段不可得时保留缺失，使用官方 Atom/发布页补充，并区分发布日期与条目更新日期。模型权重不自动继承代码许可证；被归档的历史文档/镜像仓库不自动代表主项目停更。

当前未承诺解决的缺口：单张效果图恢复可制造模型、完整无损 SolidWorks 参数树/配合、任意 DWG 与复杂 CAD 100%兼容、未知工艺参数自动生成可安全加工的程序、没有合同/费用依据的真实利润、以及未现场测试就宣称多工牌可靠。这些边界应保留在研发与验收记录中，而不增加工人屏幕上的冗余提示。

## 37 项功能覆盖与验收

每项“当前基础”来自现有仓库文档，不代表本次重新实测；验收条件是下一轮建议。

### C01 · 工程原件归档与证据定位

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已保存原始文件与SHA-256，并记录BOM行号、DXF实体句柄、源构件编号和版本；原始文件仍在同一实例共享。
- 推荐项目：PDF.js；ezdxf；Docling。
- 必须自建：统一项目/原文件/页码或实体/构件/任务证据ID；处理同名不同内容、同内容不同来源和无来源字段，不用识别置信度替代工程证据。
- 验收：用客户实际PDF、CAD与BOM建立订单；抽取技术员指定的关键部件，逐一从任务返回正确文件、页码/实体/行号和版本。缺来源字段保持待核，不得自动发布；应追溯的发布任务来源覆盖100%。
- 顺序：先验证。

### C02 · PDF交互查看、原页与局部定位

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：现有PDF能展示真实页图、页数、翻页放大，依赖Poppler；新PDF不自动成为已批准BOM。
- 推荐项目：PDF.js。
- 必须自建：文档页码、尺寸标注区域、变更云线与构件/任务的定位映射；错误页、损坏文档、过大文件与权限失败状态。
- 验收：选客户实际多页施工图，核对显示页序、文字可读性、缩放与原件一致；从两道不同工序跳到对应页/区域，刷新和换项目后不能串页或串图。
- 顺序：先验证。

### C03 · DXF/DWG结构读取与工程语义候选

- 场景：展柜工厂；非标机械装配。
- 当前基础：自有有限ASCII DXF读取器可读声明支持的图元/文字/块属性；DWG只归档，需设计方转换；未集成完整ezdxf或通用DWG解析。
- 推荐项目：ezdxf；GNU LibreDWG。
- 必须自建：图层/块属性到企业部件类别的映射、单位确认、图纸视图与真实实例区分、解析失败回退；DWG兼容性按版本锁定，LibreDWG仅按许可与样本评估。
- 验收：用客户至少两类CAD来源和不同导出版本，与CAD软件中的图元/块、单位和部件表对照；未知单位不生成尺寸，多视图不多算料，转换丢失的属性必须列出。
- 顺序：先验证。

### C04 · 扫描图OCR及BOM表格提取

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：没有已验收的通用OCR→制造BOM链路；现有新PDF保持预览/人工处理，不伪报工程拆单完成。
- 推荐项目：PaddleOCR（建议先锁 PP-OCRv5 det/rec）；Docling；LangGraph；Ollama。
- 必须自建：候选字段与原图框关联、合并单元格/跨页表归并、料号/数量/公差/尺寸单位校核、人工纠错和发布门槛。
- 验收：用客户扫描图、模糊标注和跨页清单，先由技术员独立给基准；分别记录字段错误、漏行、数量错和修改次数。关键材料/尺寸/数量无依据不补齐；盲测订单未经核准不生成正式任务。
- 顺序：按需引入。

### C05 · 制造BOM、数量与配置实例核对

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：CSV/JSON BOM、约定DXF可生成构件草稿并人工复核；整单BOM数量不再乘项目套数；无通用自动EBOM→MBOM转换。
- 推荐项目：ERPNext + Frappe Framework；FreeCAD（含 Assembly / TechDraw / CAM）；IfcOpenShell（核心 / Python / IfcConvert）；InvenTree。
- 必须自建：工程BOM到制造BOM映射、自制/采购/外协分类、用量单位与损耗、装配实例/配置和原编号去重；效果图与网格节点不能决定用量。
- 验收：选含重复柜型、左右件、不同配置及电气附件的客户订单，与已发布人工BOM逐项核对；数量及已填写尺寸与来源一致，关键部件/玻璃/电气/外协漏项为0，未知字段单列待核。
- 顺序：先验证。

### C06 · 真实效果图与项目图片去重

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已默认显示订单真实效果/参考图；按像素内容合并重复展示，保留原页码/单元格/文件引用；缺主图项目不借样例补齐。
- 推荐项目：。
- 必须自建：工程资料与展示图分开、项目边界、图片角色与来源、像素去重但不丢原引用；上传效果图不改变工程版本和工序。
- 验收：用现有客户订单的重复PDF页、清单内重复图与一张真实新图验证：同图只显示一次、全部来源可追溯；另一项目和无图项目不串图；效果图替换前后BOM/发布版本/实绩完全不变。
- 顺序：先验证。

### C07 · 真实3D、装配树、单位与选件

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已用本地OCCT WASM和Three.js读取兼容的真实模型；无模型不显示模型入口；网格测距为近似，BREP/OBJ/STL单位需确认。
- 推荐项目：Three.js；occt-import-js；Open CASCADE Technology (OCCT)；web-ifc；NVIDIA Omniverse CAD to USD skill / usd-convert-cad。
- 必须自建：真实文件与装配/部件ID映射、单位确认、实例数量、隔离/剖切选择、显示测量与工程制造尺寸的区分；不从效果图猜制造几何。
- 验收：由设计方提供同订单STEP或自包含GLB和已知尺寸；核对装配位置、零件选择、旋转和单位，模型与BOM链接指向正确件；近似测距明确标记，模型加载成功不得自动批准下料。
- 顺序：先验证。

### C08 · 原生SolidWorks导出与IFC工程来料

- 场景：非标机械装配；装修现场。
- 当前基础：SLDPRT/SLDASM目前归档，已有依赖安装SolidWorks的Windows导出桥但尚待该环境实测；IFC不是当前已验收导入路径。
- 推荐项目：FreeCAD（含 Assembly / TechDraw / CAM）；Open CASCADE Technology (OCCT)；IfcOpenShell（核心 / Python / IfcConvert）；web-ifc；NVIDIA Omniverse CAD to USD skill / usd-convert-cad。
- 必须自建：保留原生文件/活动配置/被抑制组件与输出版本；STEP只代表导出的几何/属性。IFC需建立区域/构件GUID/专业到施工对象映射。
- 验收：在客户真实Windows+SolidWorks环境导出一个含子装配和配置的订单，逐项核对漏件、实例数量及属性；若客户交付IFC，用原BIM清单核对GUID和单位。无法读取参数树必须保持未支持，不伪造成功。
- 顺序：按需引入。

### C09 · 工程版本、去重与改图影响

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：工程源哈希、复核版本、发布快照和受影响任务失效已存在；未受影响的完成状态/人员/时间可承接，模板迁移会阻断在途返工或受影响实绩。
- 推荐项目：ezdxf；Open CASCADE Technology (OCCT)；bpmn-js / diagram-js。
- 必须自建：跨图纸/BOM/配置的业务身份、变更范围和生效对象、已采购/加工/外协处置、新版工位确认；字节哈希不等于语义版本判断。
- 验收：对客户同订单R1/R2预埋材料、尺寸、数量及两柜局部变更；受影响部件和下游全部要求重审，未受影响历史保留；旧网页/工牌事件不得覆盖新版，重复上传不得重复计料。
- 顺序：先验证。

### C10 · 准确下料尺寸与钣金展开

- 场景：展柜工厂；非标机械装配。
- 当前基础：当前仅用明确下料属性；不把未展开钣金包围盒、装配外形或视图尺寸当生产下料尺寸；尚无已验收的自动钣金展开。
- 推荐项目：FreeCAD SheetMetal Workbench；FreeCAD（含 Assembly / TechDraw / CAM）；Open CASCADE Technology (OCCT)；CadQuery。
- 必须自建：材料厚度、折弯参数、余量、公差、纹理及本厂工艺规则；参数模板必须来自确认尺寸，不能AI猜值。
- 验收：以客户已经加工过且有展开基准的钣金件比对展开轮廓、孔位、厚度和折弯余量；由工艺员确认后再试件，未知参数阻断下料；复杂成形无法展开须明确失败。
- 顺序：后期。

### C11 · 板材排料、余料与CAM交付

- 场景：展柜工厂；非标机械装配。
- 当前基础：未实现可直接生产的排料/CAM链路；不能将现有尺寸或3D预览当作已验证刀路。
- 推荐项目：PackingSolver；libnest2d；FreeCAD（含 Assembly / TechDraw / CAM）。
- 必须自建：板/棒规格、锯缝、纹理方向、旋转禁限、孔洞与余料复用、同批材料及实际机床后处理/装夹；排料和刀路分别验收。
- 验收：用客户已完成排料单、真实余料和机床参数先离线对比；所有件数量齐全且约束无违反，输出经工艺审核/仿真和小范围试切后才可投产；材料利用率须与同样订单人工方案比较。
- 顺序：后期。

### C12 · 三场景对象、组织技能与工作中心

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已建工厂/班组/人员/自定义技能/设备工位作业面及三套参考模板；未知容量不自动参与派工，真实订单不分给演示人员。
- 推荐项目：ERPNext + Frappe Framework；Tryton；OpenProject Community。
- 必须自建：柜号/柜组、设备序列号/子装配、楼层/区域的对象层级；资格、班次、跨组借调、工作中心容量和作用域须企业核准。
- 验收：用客户实际人员班次、工作中心和一个订单建立资源；无技能/未知容量不得被自动指派；同人跨岗位和同工位冲突可见；在机械与现场各回放一个对象结构而非只改行业名称。
- 顺序：先验证。

### C13 · 工艺DAG、企业模板与可执行门槛

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已支持参考模板复制、草稿/发布、前序、工时、开工检查、验收项、工作包复核和版本迁移预览。
- 推荐项目：bpmn-js / diagram-js；Flowable Open Source。
- 必须自建：可执行串并行/汇合、分批转序、外协、返工路径和版本迁移语义；可视化图保存不等于引擎已正确执行。
- 验收：用客户工艺卡分别覆盖木作/五金并行总装、电控测试和封板前机电验收；未完成必需前置不能开工，缺料仅阻塞关联分支；模板升级预览准确，进行中或返工实例不能被静默覆盖。
- 顺序：先验证。

### C14 · 标准工时、有效实绩与校准

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已按真实完成任务的有效作业段取样，暂停/关闭不计作业；分工厂/工序要求/单位保留P50/P80与来源，样本不足不显示准确率。
- 推荐项目：现有实绩统计＋PostgreSQL（规模需要时）。
- 必须自建：加工/准备/等待/返工时间口径、独立项目划分、异常样本处理、历史费率/模板版本、留出评估；求解器不自动校准工时。
- 验收：用客户报工与考勤/工艺记录核对开始暂停恢复时间段；同项目修改版不得同时落入训练和测试，留出订单报告误差/样本量与基线对比；无有效样本保持未知。
- 顺序：先验证。

### C15 · 有限产能、班次、等待与交期试算

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有分钟粒度启发式，同时占用人员与工作中心，尊重前序、到料、准备、等待；已有日排程冻结，采用前重验输入；非通用最优APS。
- 推荐项目：Google OR-Tools；frePPLe Community；Timefold Solver Community；Frappe Gantt。
- 必须自建：双资源/技能约束、日历与自然等待区分、冻结窗、材料承诺、方案版本与可解释未排原因；求解结果必须再过执行门槛。
- 验收：用客户原排程和核定班次/工时/料期回放同一订单；验证无人员/设备超占、固化等待不被压缩、未知项不偷补；正常/缺料/插单三种情形对比可行性与交期，并在现场核对排程兑现率。
- 顺序：先验证。

### C16 · 暂停、部分进度、交接与急单换做

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有累计整件进度、五类暂停、现场交接、四级优先级、原子换单和恢复；工牌执行需业务回执，质量验收仍在Web。
- 推荐项目：Google OR-Tools；Timefold Solver Community。
- 必须自建：暂停/交接内容保留、半成品状态、剩余数量、目标可开工检查、原子切换、插单影响接受与恢复责任；急单优先不等于可绕过门槛。
- 验收：让工人用真实任务完成3/10后缺料暂停，换到已放行急单，再恢复余7件；重发/断线/目标前序未完成时不重复计量或只暂停未开新单；半件只记交接，暂停时长不计作业。
- 顺序：先验证。

### C17 · 物料齐套、预留、领退与批次追溯

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有已验收预留物料、关联工序、缺口责任与开工条件；实际库存主要人工/文件登记，完整库存账和跨库批次未做实厂验收。
- 推荐项目：InvenTree；ERPNext + Frappe Framework；Tryton；OpenBoxes。
- 必须自建：主责库存系统、订单/柜/设备/区域占用、领退/报废与替代审批、批次/序列实装关系；不能由重复回执二次扣料。
- 验收：用客户实际料表和仓库单据回放部分到货、两单争料、退料及替代；占用总量不超已验收可用量，缺料仅阻塞指定分支，每笔变化追溯单据/批次并与ERP账对平。
- 顺序：先验证。

### C18 · 采购到货与外协供料回收

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：采购/库存目前人工或Excel登记；有项目外协费用与生产协同门槛，无已接通客户供应链API。
- 推荐项目：ERPNext + Frappe Framework；Odoo Community 19；Tryton；InvenTree。
- 必须自建：采购承诺/变更/部分到货、外协供料与损耗、回收检验、负责人和延误传播、费用归属及撤销对账。
- 验收：选客户真实玻璃/喷涂外协或长周期电气件，回放供料、部分交回、检验不合格和延期；未验收来料不放行，外协余量和费用与采购单/回执一致，重复导入不重复收货或计费。
- 顺序：先验证。

### C19 · 质量验收、隔离、返工与复验

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有关联检验、质量暂停、返工复验；质量暂停使旧合格结果失效，未解除质量问题不能借关单/发货放行。
- 推荐项目：ERPNext + Frappe Framework；Tryton；InvenTree。
- 必须自建：企业控制点/测量单位/允许范围/证据和授权角色；版本绑定、失败隔离、返工路径、复验与放行；不将测试记录工具称作完整QMS。
- 验收：以客户质检表回放进料、过程、电气/装配或隐蔽验收失败；旧合格结果失效、返工不覆盖原记录、复验缺项不能放行；所有安全或工程参数由负责人确认，系统不补造。
- 顺序：先验证。

### C20 · 装箱核齐、分批发货与验收移交

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有分批交付、完成待发货/已发货及重新打开，关闭后移出生产待办并保留历史；装箱扫码和一机一档需按场景补齐。
- 推荐项目：OpenBoxes；ERPNext + Frappe Framework；InvenTree。
- 必须自建：柜/箱/设备/区域与交付批次、附件清单、数量余额、现场缺件补发、检验/版本条件与出厂现场验收关系。
- 验收：用客户实际装箱/送货清单演练20组先发18组、剩余2组继续生产；发货量不超可交付合格数量，箱号/附件可追溯；关闭/重开不重复完工，缺件补发单独留痕。
- 顺序：先验证。

### C21 · 现场变更、签认与工程量

- 场景：装修现场；非标机械装配；展柜工厂。
- 当前基础：已有现场变更签认和合同节点登记；尚未接入客户既有审批平台或真实施工/装配规范试点。
- 推荐项目：OpenProject Community；ERPNext + Frappe Framework。
- 必须自建：变更与图纸位置/设备/区域、生效范围、核量、费用及审批证据关联；待签认、已认可和已收款分开，例外有授权记录。
- 验收：用客户真实灯位/开孔或设备变更单，核对原版本、工程量、材料及追加费用；未签认金额单列，不能当收入/利润；签认后只影响指定对象，并可追到原审批证据。
- 顺序：按需引入。

### C22 · 内部估价、实际成本与经营基准

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有材料/损耗/人工/外协/管理费/目标毛利估价、缺价阻断，实际费用和人工核定基准；无正式报价审批/合同锁价/会计总账。
- 推荐项目：ERPNext + Frappe Framework；Tryton；Odoo Community 19。
- 必须自建：企业计价单位/费率和生效期、预算与已发生/已承诺/剩余成本口径、返工/运输/安装费用归属，防止估价重算改写合同事实。
- 验收：用客户实价BOM、外协发票/费用单和有效工时独立复算同订单；各行与总额一致，缺价/缺重量/缺量阻止完整报价，重复费用只记一次，费率变化不能伪造历史成交价。
- 顺序：先验证。

### C23 · 合同节点、开票与回款事实

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已登记合同节点，财务以合同及已登记费用为依据；没有真实财务系统连接，不从任务完成率换算收入、利润或回款。
- 推荐项目：ERPNext + Frappe Framework；Odoo Community 19。
- 必须自建：完工/验收/可申报/开票/应收/已收款各自事实、金额来源、冲销与核销、逾期责任，财务字段权限和主系统。
- 验收：用客户合同、验收单、发票及收款记录对照同订单节点；100%工序完成但未验收/未收款时不得显示已收款；分次收款/退款按单据核对，未签变更不计现金。
- 顺序：先验证。

### C24 · 老板行动台与可追溯经营BI

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有任务/交付/暂停等BI及老板风险行动台；以真实登记事实汇总，无样本或无财务来源不造收益/准确率。
- 推荐项目：OpenProject Community；ERPNext + Frappe Framework；Apache ECharts；Apache Superset。
- 必须自建：风险到责任/原单/最后更新/下一动作的钻取；等待、作业、返工与计划工时区分；收益口径和防重复统计。
- 验收：由老板给出同一真实项目当天五个问题：迟交、卡料、加急代价、成本偏差和待收款；每项能回原记录并与人工台账对平。空/未知显示未知，不把节省查询时间直接当现金节省。
- 顺序：先验证。

### C25 · CSV/XLSX文件互联与客户Excel习惯

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已支持订单/人员/物料/报工CSV与XLSX、工作表/表头映射、差异预览、原编号、版本冲突、整批事务、去重、回执/导出；原表只读。
- 推荐项目：OpenProject Community；frePPLe Community；ERPNext + Frappe Framework；openpyxl；SheetJS Community Edition；Univer。
- 必须自建：每客户模板映射、字段权威来源、单位/时区/公式值/空值策略、批次身份、更新冲突、回执和原编号对账；不得绕过业务权限和质量门槛。
- 验收：直接用客户正在用的四类Excel，而非新造标准表；含合并表头、空值、旧行、重复行、同编号改值与过期报工。预览不写入，应用后逐行对平，重导不重复，错误整批不半写，源表字节保持不变。
- 顺序：先验证。

### C26 · ERP/MES/WMS API、CLI与事件适配

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：自有HTTP API和CLI共用业务动作；已做35项接口研究，但没有客户账号接入，不代表连接器实现。
- 推荐项目：ERPNext + Frappe Framework；Odoo Community 19；InvenTree；Temporal；Node-RED；MCP Python SDK。
- 必须自建：首家客户版本/许可接口验证、原ID映射、字段主责、幂等键、增量游标、失败重试/死信和对账；跨系统状态由同一业务规则校验。
- 验收：在客户批准的测试环境以真实脱敏单据验证新增/修改/撤销和乱序/重复/超时回放；ERP与KANPACE数量/状态一致，失败可追溯并重放，API/CLI/Excel不能绕开同一负责人/版次/质量门槛。
- 顺序：按需引入。

### C27 · 岗位权限、审计及多人组织隔离

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：可选管理员/主管/技术/仓管/质检/工人/老板角色，工人仅本人任务，结构化财务受限并记账号审计；正式账号默认未启用，同实例项目和原文件共享，无跨厂隔离。
- 推荐项目：Keycloak；PyCasbin；PostgreSQL。
- 必须自建：多人部署身份、会话与HTTPS、项目/工厂/客户数据隔离、原文件/附件授权、岗位最小权限、操作审计与撤权；不能以登录页替代租户隔离。
- 验收：用实际岗位矩阵在隔离实例建立至少两工厂/项目和工人/质检/老板账号，直接请求API与原件URL检验越权；本人报工、财务可见和跨项目访问符合约定，撤权后旧会话失效且审计可追责。
- 顺序：先验证。

### C28 · 工牌任务屏、中文图册与触控

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：实板1.5.2已有简洁任务首页、按需要点、中文和施工/效果各一张图，USB校验传图/重启留存已实测；手指触控观感和图纸可读性待用户确认。
- 推荐项目：Arduino-ESP32；LVGL；LovyanGFX；esp_lcd + esp_lcd_touch + esp_lvgl_port（ESP-BSP）。
- 必须自建：岗位卡内容、中文字体/长交接、误触确认与待回执状态、板级ST7789/CST816D适配、C3内存预算、图像来源上下文与原子存储。
- 验收：让真实工人独立完成看当前任务、查施工/效果图、放大移动、暂停交接再返回；用实际长中文和小字号尺寸图记录误触/阅读时间/失败，弱内存下不崩溃；不能把渲染预览或串口displaying当人工通过。
- 顺序：先验证。

### C29 · USB发现、配对、下发与真实报工

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有兼容固件被动公告/握手、USB任务及图册下发、设备/请求/任务/版本匹配回执；执行队列和业务ACK已接入，实板启动/保留/连接已验。
- 推荐项目：Arduino-ESP32；esptool。
- 必须自建：串口所有权、设备/人员配对、测试任务标记、接收ACK与生产业务ACK区分、旧固件拒写、业务重放防重和换机恢复。
- 验收：用现有真实板与第二块兼容板轮换端口，核对设备身份；普通串口/旧固件不误发命令，已发送不冒充已接收，接收不冒充开工；真实任务事件丢ACK重发只记一次，测试任务不能生产报工。
- 顺序：先验证。

### C30 · Wi-Fi/MQTT双向通信与多工牌

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有USB配网和局域网HTTP令牌任务通道，但VPN/网段可达性和无线报工/看图未完成同等实板验收；未引入MQTT。
- 推荐项目：ESP-MQTT + Mosquitto + MQTT.js（Python侧优先Paho）。
- 必须自建：兼容当前Arduino2/IDF4客户端、设备主题/ACL/TLS、会话与业务事件身份、多板派发撤回、掉线/冲突状态；MQTT QoS不等于业务成功，图片走受控分块下载。
- 验收：在客户真实AP/VPN/防火墙条件，用至少两块工牌同时下发不同人/任务，断网重连并重放事件；无串单、无二次完工；QoS回执后业务拒绝仍显示失败，无法连broker有明确原因并可USB恢复。
- 顺序：按需引入。

### C31 · 断网掉电、持久事件队列与幂等

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：工牌已有最多8条持久待发事件、每任务最多1条待确认操作，软件/PTY已验；实板业务掉电中断仍待现场验证。本地Web不依赖互联网，但服务停止时不能保存。
- 推荐项目：Arduino-ESP32；ESP-IDF（含官方 OTA、rollback、Secure Boot、Flash/NVS encryption）；Dexie.js；Workbox。
- 必须自建：统一USB/HTTP/MQTT事件ID、业务事务、队列满策略、掉电写入原子性、旧版本冲突处置、时钟漂移与收到ACK后状态；浏览器弱网草稿另设计。
- 验收：用客户任务在开始/部分完成/暂停三个动作发送前、写库后丢ACK、落盘中分别断电/断线；重启后有效事件最终一次入账，未确认不装作成功，旧版事件明确冲突，队列满不丢历史或静默放行。
- 顺序：先验证。

### C32 · 固件升级、OTA、回滚与设备维护

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已验证esptool仅应用分区升级，保留NVS/LittleFS/任务/图册；当前4MB布局为单大app，未实现可承诺双槽回滚的OTA。
- 推荐项目：esptool；ESP-IDF（含官方 OTA、rollback、Secure Boot、Flash/NVS encryption）；ESP Web Tools + esptool-js。
- 必须自建：发布镜像/板型/分区/协议版本清单、串口释放、更新前后读回、数据迁移、失败恢复和签名策略；先算4MB双槽+图册预算再设计OTA。
- 验收：先在备用同型板用现有客户任务/图册升级，核对配置和摘要不变；错板/错分区镜像拒绝，升级中断可受控恢复。新增OTA必须实测下载失败、启动自检失败回滚及业务队列保留，未通过不量产。
- 顺序：按需引入。

### C33 · 扫码定位与语音备注

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：没有已验收的扫码业务/自由语音报工闭环；本C3板未确认麦克风/摄像头/音频链路，不能运行完整Whisper。
- 推荐项目：ZXing for JS：@zxing/browser + @zxing/library；whisper.cpp。
- 必须自建：料号/设备/工序二维码身份和服务端权限、相机与键盘扫描枪并列输入；主机语音保留原音/转写/人工修正，识别文本不直接触发完工或质量放行。
- 验收：用客户实际脏污/反光标签和车间噪声，在手机/工位试扫与转写料号数量；错误标识不能操作他人/旧版任务，数字须确认；统计成功率和纠错时间，C3语音需求先确认硬件再立项。
- 顺序：按需引入。

### C34 · 真实订单验收、回归、备份与商用部署

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：有隔离库Python/HTTP/前端/C++/PTY回归及SQLite+原图备份；最新图册验收393项Python、15前端文件，但不是实厂或量产验收；服务默认127.0.0.1，多人TLS/隔离/多板需单独验证。
- 推荐项目：Playwright；OpenTelemetry Python；SeaweedFS。
- 必须自建：按完整订单划分真实基准/盲测、三场景异常包、生产数据隔离、备份恢复演练、客户升级兼容性、工人独立操作和实际收益基线；测试数量不等于业务覆盖。
- 验收：先用3个已完结资料完整项目校准，再用2个未参与调整订单盲测并由技术员独立基准核对；至少一真实订单/里程碑从资料到质量交付走通。另在新目录恢复备份核对原图/版本/实绩，演练双用户并发与两工牌，记录全部未通过项。
- 顺序：先验证。

### C35 · 拆单 Agent 编排与本地推理

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：本轮作为拆单增强候选评估；未接入这些 Agent/推理运行时，不能宣称已具备自主制造决策。
- 推荐项目：LangGraph；Ollama；Docling；PaddleOCR。
- 必须自建：候选结构化、原文证据、单位和数量校验、人工中断与复核、模型版本；持久checkpointer和工具写入幂等；正式发布仍用生产业务事务。
- 验收：用独立真实订单盲测关键字段，保留缺失和矛盾；模拟中途服务重启，检查能恢复复核状态且不重复创建正式工单。模型生成尺寸不得自动放行。
- 顺序：按需引入。

### C36 · 历史相似图纸、工艺与返工知识检索

- 场景：展柜工厂；非标机械装配；装修现场。
- 当前基础：已有来源和版本资料可作为索引基础；本次没有建立向量库或验证实际检索召回。
- 推荐项目：Qdrant；Docling；Ollama。
- 必须自建：按项目隔离的提取与embedding管线、文件/页区/构件引用、确认状态与版本、删除同步；相似度不能合并料号或推断需求数量。
- 验收：技术员先标注一批相似/不相似项目和工艺，统计召回及误匹配；检索结果可回到真实版本，未授权项目不可被检出，不能因图片相同将不同订单数量去重。
- 顺序：按需引入。

### C37 · OPC UA / Modbus机台采集与停机分析

- 场景：展柜工厂；非标机械装配；有机电设备的工程现场。
- 当前基础：工牌业务回执不等于机台采集；本次仅筛选协议网关，没有接入PLC、读取实际寄存器或验证设备计数。
- 推荐项目：open62541（OPC UA）；PyModbus（Modbus TCP / RTU）；Node-RED；Apache ECharts。
- 必须自建：厂商NodeId/寄存器字典、单位/倍率/字节序、源时间与质量码、计数清零/回绕、设备与工序归属；计划生产时间/理想节拍/合格数不全时不报完整OEE。
- 验收：使用模拟器后对一台有官方点表的设备只读采集，与实际计数对照；断线记未知而不是0；重复或清零不重复记产量。机器遥测不绕过工人报工与质量放行。
- 顺序：按需引入。

## 72 个候选与对照档案

建议等级表示采用顺序，不是成熟度评分。每条附官方能力与许可来源。

### PDF.js

**图纸与3D · 优先验证**　[PDF.js 官方仓库](https://github.com/mozilla/pdf.js)

- 覆盖：PDF浏览；页码与坐标定位；文本层；批注展示
- 许可：Apache-2.0。[许可原文](https://github.com/mozilla/pdf.js/blob/master/LICENSE)
- 维护证据：发布 v6.3.289 · 2026-08-29。[记录](https://github.com/mozilla/pdf.js/releases/tag/v6.3.289)

可用能力：浏览器渲染 PDF 页，支持文本层、缩放、页面导航和批注相关 API。 从原生文本 PDF 取得文字及位置，为 BOM 行与施工图页区互相定位提供基础。

接入判断：在现有附件查看器嵌入本地托管的 pdfjs-dist 与 worker；保存 file_hash、page、bbox、draw_revision，将提取字段回链到原始页区。Poppler 可继续承担后端渲染/提取，PDF.js 负责交互。

能力边界：

- 不是 OCR，也不是 CAD 语义解析器；PDF 画线与文字不会自动变成可制造实体。
- 纸面坐标与真实尺寸之间需要图纸标注/已确认比例；不可从显示像素推断加工尺寸。
- mozilla/pdfjs-dist 旧 GitHub 仓库归档不等于 pdf.js 主项目停更；npm pdfjs-dist 构建产物应从主项目当前发布链核验。

组件许可补充：浏览器库代码为 Apache-2.0；字体、CMap、图像编解码依赖按选定分发包另保留第三方声明。无必需 AI 权重。

官方证据：[来源1](https://github.com/mozilla/pdf.js) · [来源2](https://github.com/mozilla/pdf.js/blob/master/LICENSE) · [来源3](https://mozilla.github.io/pdf.js/examples/) · [来源4](https://mozilla.github.io/pdf.js/getting_started/) · [来源5](https://github.com/mozilla/pdfjs-dist) · [来源6](https://github.com/mozilla/pdf.js/commit/4c6025719e324761f9ee32e52b052565887c283a) · [来源7](https://github.com/mozilla/pdf.js/releases/tag/v6.3.289)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### ezdxf

**图纸与3D · 优先验证**　[ezdxf 官方仓库](https://github.com/mozman/ezdxf)

- 覆盖：DXF读取/写入；图层/块/文字/标注；二维轮廓；施工图BOM字段辅助
- 许可：MIT。[许可原文](https://github.com/mozman/ezdxf/blob/master/LICENSE)
- 维护证据：默认分支提交 · 2026-08-26。[记录](https://github.com/mozman/ezdxf/commit/d6f2ac10caeddc712ed1824aaeb3b9c050de4a04)

可用能力：Python 读取、修改、写出多版本 DXF，覆盖 ASCII/Binary、图层、块引用、文字、标注等实体。 提供实体查询、审计/恢复和绘图导出附加模块；可按实体 handle 保留来源。

接入判断：在现有 Python 上传解析任务中输出标准化 entities、layers、blocks、dimensions 与单位；先双跑旧解析器比对，再逐步切换。BOM 草稿每项关联 entity handle、文件版本，缺失/歧义标注待确认。

能力边界：

- 不直接读取 DWG；官方 odafc 附加模块调用的 ODA File Converter 不是 ezdxf 自身的开源能力。
- 无法自动理解企业图层命名、零件编号、材料规则或恢复参数化设计意图。
- 绘图/渲染附加功能不保证与 AutoCAD 完全同像；曲线离散、块变换、单位与字体都要回归实际图纸。

组件许可补充：核心 MIT；可选 PyMuPDF 绘图后端、ODA 转换器等依赖有独立许可，不能用 ezdxf 的 MIT 概括。选择仅核心/已核验宽松后端。无模型权重。

官方证据：[来源1](https://github.com/mozman/ezdxf) · [来源2](https://github.com/mozman/ezdxf/blob/master/LICENSE) · [来源3](https://ezdxf.readthedocs.io/en/stable/introduction.html) · [来源4](https://ezdxf.readthedocs.io/en/stable/addons/drawing.html) · [来源5](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html) · [来源6](https://github.com/mozman/ezdxf/commit/d6f2ac10caeddc712ed1824aaeb3b9c050de4a04)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### GNU LibreDWG

**图纸与3D · 谨慎评估**　[GNU LibreDWG 官方仓库](https://github.com/LibreDWG/libredwg)

- 覆盖：DWG读取；DWG转DXF/JSON；DWG图层/文字检索
- 许可：GPL-3.0-or-later。[许可原文](https://github.com/LibreDWG/libredwg/blob/master/COPYING)
- 维护证据：发布 0.14 · 2026-06-27。[记录](https://github.com/LibreDWG/libredwg/releases/tag/0.14)

可用能力：C 库及 CLI 可读写 DWG；官方提供 DWG/DXF/JSON 转换、文字检索与图层枚举工具。 可作为 DWG 输入到 ezdxf/自有标准 JSON 的前置解码器。

接入判断：Python 任务队列调用受限本地转换进程，保留原 DWG、转换日志和跳过实体清单；结果只进入待复核图纸/BOM，不静默覆盖工程尺寸。闭源商用安装包的分发方案单独定版。

能力边界：

- GNU 官网将其标为 beta，说明部分高级 R2010+ 实体可能跳过；DWG 高保真并非无条件覆盖。
- 应按选定版本核验写入年代和实体覆盖，不能将 reader 覆盖等同 writer 覆盖。
- GPL 分发义务需要结合真实组合方式落实；改成子进程并不自动免除所有分发责任。

组件许可补充：程序为 GPLv3+；GNU 手册为 GFDL-1.3-or-later。不是 ODA Drawings SDK；GNU 项目明确与 ODA 无关联。无模型权重。

官方证据：[来源1](https://github.com/LibreDWG/libredwg) · [来源2](https://github.com/LibreDWG/libredwg/blob/master/COPYING) · [来源3](https://www.gnu.org/software/libredwg/) · [来源4](https://www.gnu.org/software/libredwg/manual/LibreDWG.html) · [来源5](https://www.gnu.org/software/libredwg/manual/html_node/Programs.html) · [来源6](https://github.com/LibreDWG/libredwg/releases/tag/0.14)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### Open CASCADE Technology (OCCT)

**图纸与3D · 沿用完善**　[Open CASCADE Technology (OCCT) 官方仓库](https://github.com/Open-Cascade-SAS/OCCT)

- 覆盖：精确B-rep；STEP/IGES；装配结构与属性；几何检查/测量；网格化
- 许可：LGPL-2.1 with OCCT LGPL exception 1.0；另有商业许可选项。[许可原文](https://github.com/Open-Cascade-SAS/OCCT/blob/master/LICENSE_LGPL_21.txt)
- 维护证据：发布 V8.0.1 · 2026-07-30。[记录](https://github.com/Open-Cascade-SAS/OCCT/releases/tag/V8.0.1)

可用能力：C++ CAD 内核提供曲面/实体、布尔、拓扑、形状修复、几何分析与离散化。 开放数据交换包含 STEP AP203/AP214/AP242、IGES 等；XDE 可携带装配、名称、颜色及受支持属性。

接入判断：保留现有 OCCT WASM 预览；精确尺寸/体积/拓扑验证可由 C++ 或经 CadQuery/OCP 的本地进程读取源 STEP。规范单位和 tessellation 容差，将源零件实例 ID 与 BOM 行关联。

能力边界：

- OCCT 是开发内核，需自建 BOM 映射、材料/工艺/版本流程和用户界面。
- 标准开源交换模块不等于原生 SLDPRT/SLDASM 参数树、配合、配置解析。
- STEP 几何/装配也不保证携带完整原生特征历史；三角网格测量精度不可混同 B-rep。

组件许可补充：必须同时阅读 OCCT_LGPL_EXCEPTION.txt；例外针对对象代码纳入头文件材料，并非把全库改成 MIT。 商业 Advanced Data Exchange 组件另行授权，不能把 OCCT 的开源许可扩展给专有转换器。

官方证据：[来源1](https://github.com/Open-Cascade-SAS/OCCT) · [来源2](https://github.com/Open-Cascade-SAS/OCCT/blob/master/LICENSE_LGPL_21.txt) · [来源3](https://github.com/Open-Cascade-SAS/OCCT/blob/master/OCCT_LGPL_EXCEPTION.txt) · [来源4](https://dev.opencascade.org/doc/overview/html/index.html) · [来源5](https://github.com/Open-Cascade-SAS/OCCT/commit/3d097a0328e71b826377d4814ab05ec3c3d23871) · [来源6](https://github.com/Open-Cascade-SAS/OCCT/releases/tag/V8.0.1)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### FreeCAD（含 Assembly / TechDraw / CAM）

**图纸与3D · 优先验证**　[FreeCAD（含 Assembly / TechDraw / CAM） 官方仓库](https://github.com/FreeCAD/FreeCAD)

- 覆盖：参数化CAD；装配BOM；施工图生成；STEP处理；CAM刀路
- 许可：当前主仓根 LICENSE 为 LGPL-2.1；部分官方贡献/旧文档仍写 LGPL2+。[许可原文](https://github.com/FreeCAD/FreeCAD/blob/main/LICENSE)
- 维护证据：发布 1.1.3 · 2026-07-25。[记录](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.3)

可用能力：桌面参数化实体、装配、TechDraw 工程图及 Python 自动化。 1.1 官方发布说明明确包括装配 Bill of Materials；对有结构与属性的 FreeCAD 装配生成清单。 CAM 提供 Job、stock/tool、轮廓/口袋/钻孔等工序、后处理与刀路检查/仿真。

接入判断：使用固定 FreeCAD 版本的工作站/sidecar，读 STEP/FCStd、输出经过确认的 BOM CSV/JSON、工程图与 GLB/网格。KANPACE 只接收带源文件哈希、装配路径、人工确认记录的产物；CAM 先产出供工程师审查的 job 与 G-code 文件。

能力边界：

- 不能假定原生 SolidWorks 参数树完整导入；中性格式常只有几何与部分属性。
- BOM 依赖源装配实例和已填写属性，采购件、虚拟件、工序耗材及真实制造拆分仍需业务规则。
- CAM 适配机床、刀具、装夹与后处理；不能把候选刀路自动发给机床。部分脚本需要 GUI，headless 能力须按任务实测。

组件许可补充：本次直接读取根文件为 LGPL2.1，不盲从旧 wiki 的 LGPL2.0+ 描述；分发时以锁定版本及逐文件声明确定。 依赖库、外部 workbench 和后处理相关组件需另核验；FreeCAD 文档/站点与程序许可不同。

官方证据：[来源1](https://github.com/FreeCAD/FreeCAD) · [来源2](https://github.com/FreeCAD/FreeCAD/blob/main/LICENSE) · [来源3](https://freecad.github.io/Website/download/releases/1-1/) · [来源4](https://github.com/FreeCAD/FreeCAD/blob/main/CONTRIBUTING.md) · [来源5](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/CAM_Workbench.md) · [来源6](https://github.com/FreeCAD/FreeCAD/commit/a48d5e2a1549cbd88c6b70e46e96ca0dc275eae0) · [来源7](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.3)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### CadQuery

**图纸与3D · 按需引入**　[CadQuery 官方仓库](https://github.com/CadQuery/cadquery)

- 覆盖：代码参数化建模；已知尺寸生成零件；STEP/DXF导入；STEP/GLTF等导出
- 许可：Apache-2.0。[许可原文](https://github.com/CadQuery/cadquery/blob/master/LICENSE)
- 维护证据：发布 v2.8.0 · 2026-06-20。[记录](https://github.com/CadQuery/cadquery/releases/tag/v2.8.0)

可用能力：Python API 构造约束/参数驱动实体和装配，支持 STEP、DXF 等导入及多格式导出。 适合把已确认板厚、孔距、尺寸和料号套入版本化模板，产出可旋转模型与几何核对值。

接入判断：独立 Python worker 接收经过 schema 校验的模板 ID 和数值参数，输出 STEP 与显示网格；禁止把用户上传 Python 当模板执行。SQLite 保存模板版本、输入来源和人工确认后尺寸。

能力边界：

- 读入 STEP 不会恢复设计者原始参数历史；导入格式/装配行为以当前 API 为准。
- 输入效果图或文字不会自动产生可信加工尺寸；模板参数必须来自图纸、BOM 或工程确认。
- 不是通用 SolidWorks、DWG 解析器，也不自带完整 MES/BOM 审批或通用 CAM。

组件许可补充：GitHub 自动识别曾返回 NOASSERTION，但 LICENSE 正文明确 Apache 2.0。 OCP 包装层当前 LICENSE 为 Apache-2.0；底层 OCCT 仍为 LGPL2.1 + 例外，不能将整套分发物概括为 Apache。无权重。

官方证据：[来源1](https://github.com/CadQuery/cadquery) · [来源2](https://github.com/CadQuery/cadquery/blob/master/LICENSE) · [来源3](https://cadquery.readthedocs.io/en/latest/importexport.html) · [来源4](https://github.com/CadQuery/OCP/blob/master/LICENSE) · [来源5](https://github.com/CadQuery/cadquery/commit/a6bedc0d7ceac1829290037259465e918fc00e80) · [来源6](https://github.com/CadQuery/cadquery/releases/tag/v2.8.0)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### occt-import-js

**图纸与3D · 沿用完善**　[occt-import-js 官方仓库](https://github.com/kovacsv/occt-import-js)

- 覆盖：STEP/IGES/BREP浏览器导入；真模型网格；层级/颜色/面映射
- 许可：LGPL-2.1（封装本体）。[许可原文](https://github.com/kovacsv/occt-import-js/blob/main/LICENSE.md)
- 维护证据：发布 0.0.23 · 2024-12-03。[记录](https://github.com/kovacsv/occt-import-js/releases/tag/0.0.23)

可用能力：WASM 在浏览器或 Node 读取 BREP、STEP、IGES，返回层级与兼容 Three.js 的三角网格 JSON。 返回名称、颜色、源 B-rep 面对应三角形范围；可设置输出单位和线性/角度离散参数。

接入判断：沿用现有 importer，将 worker 的 success/error、linearUnit、deflection 与源哈希写入解析记录；用返回 root.children 绑定零件选择和 BOM 定位。精确尺寸从源 B-rep/图纸取得，网格尺寸注明显示近似。

能力边界：

- 仅暴露三类导入函数与网格结果，不能当完整 OCCT 编辑/精确测量 API。
- 不直接支持原生 SLDASM/SLDPRT，层级节点不等于完整制造 BOM。
- 本次观察 release/默认分支提交停留 2024-12-03；需评估维护与底层 OCCT 更新策略，大文件受浏览器内存约束。

组件许可补充：封装本体不是 MIT；另包含 OCCT 子模块，OCCT 有自己的 LGPL2.1 例外。 浏览器向终端用户下发 JS/WASM 也是交付形式，需准备对应许可、修改/源码与替换/重建方案；不能把服务端部署视作自动免责。

官方证据：[来源1](https://github.com/kovacsv/occt-import-js) · [来源2](https://github.com/kovacsv/occt-import-js/blob/main/LICENSE.md) · [来源3](https://github.com/kovacsv/occt-import-js/blob/main/README.md) · [来源4](https://github.com/kovacsv/occt-import-js/commit/41e470890ae0f9dc69ac50ffd5fc73e03576f4eb) · [来源5](https://github.com/kovacsv/occt-import-js/releases/tag/0.0.23)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### Three.js

**图纸与3D · 沿用完善**　[Three.js 官方仓库](https://github.com/mrdoob/three.js)

- 覆盖：真模型旋转/缩放；网格渲染；零件拾取；剖切/高亮交互
- 许可：MIT。[许可原文](https://github.com/mrdoob/three.js/blob/dev/LICENSE)
- 维护证据：发布 r185 · 2026-07-01。[记录](https://github.com/mrdoob/three.js/releases/tag/r185)

可用能力：成熟浏览器 3D 场景、相机、材质与 loader 生态，支持真实 mesh 渲染与相机交互。 可实现零件拾取、高亮、隐藏与裁切平面；通过模型实例 ID 和 BOM 双向定位。

接入判断：保留现有 Three.js；建立 source_part_id/assembly_path 到 mesh 的稳定映射，补拾取、聚焦、剖切及文件级单位提示。所有显示动作使用同一真实模型，禁止用效果图伪造三维几何。

能力边界：

- Three.js 是渲染库，不是工程 CAD 内核、BOM 解释器或 CAM。
- STL/GLB 三角网格不天然具备材料、厚度、设计特征及加工公差；不可仅从表面外观推断它们。
- 大型装配需要实例化、网格简化/分块与性能预算，不能只看简单示例流畅度。

组件许可补充：主库 MIT；示例模型、纹理、字体以及 Draco 等外部编解码器按使用资产/组件单独核验。无必需模型权重。

官方证据：[来源1](https://github.com/mrdoob/three.js) · [来源2](https://github.com/mrdoob/three.js/blob/dev/LICENSE) · [来源3](https://threejs.org/docs/) · [来源4](https://threejs.org/license/) · [来源5](https://github.com/mrdoob/three.js/commit/9941685098b927759ceb06931c24eebbdc9ceb70) · [来源6](https://github.com/mrdoob/three.js/releases/tag/r185)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### IfcOpenShell（核心 / Python / IfcConvert）

**图纸与3D · 按需引入**　[IfcOpenShell（核心 / Python / IfcConvert） 官方仓库](https://github.com/IfcOpenShell/IfcOpenShell)

- 覆盖：IFC读取；BIM语义与属性；数量/清单；几何转换
- 许可：LGPL-3.0-or-later（核心 / Python）；同仓部分组件 GPL-3.0-or-later。[许可原文](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.9.0/COPYING.LESSER)
- 维护证据：同仓 Bonsai alpha 发布（非核心稳定版） · 2026-09-04。[记录](https://github.com/IfcOpenShell/IfcOpenShell/releases/tag/bonsai-0.9.0-alpha2609040826)

可用能力：Python/C++ 读写 IFC，提取对象、关系、属性集与数量；IfcConvert 提供几何格式转换。 IfcCSV 等同仓工具可输出清单；IFC GUID 可作为图形、构件与来源的关联 ID。

接入判断：本地 Python worker 读取 IFC，输出 GUID、类型、层级、属性/数量与显示网格；先映射到工程构件清单，再人工/规则生成制造 BOM。IFC 源值和 KANPACE 人工修订分开保存。

能力边界：

- IFC 构件与制造拆件不一一对应；材料/数量字段仍取决于设计方填报质量。
- 完整 schema 解析支持与各 IFC 版本的几何支持范围不同，不能把 parse 成功等同所有几何完整。
- 同仓 Bonsai alpha release 不是 Python 核心稳定 release；原生 SolidWorks 参数树不在其职责。

组件许可补充：README 逐组件表：ifcopenshell-python、IfcConvert 等为 LGPL3+；Bonsai、ifcsverchok 为 GPL3+。 底层几何/可选依赖的实际构建许可另审；本次未宣称所有第三方预编译 wheel 的依赖清单已完审。

官方证据：[来源1](https://github.com/IfcOpenShell/IfcOpenShell) · [来源2](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.9.0/COPYING.LESSER) · [来源3](https://docs.ifcopenshell.org/ifcopenshell-python.html) · [来源4](https://docs.ifcopenshell.org/ifcopenshell-python/installation.html) · [来源5](https://docs.ifcopenshell.org/ifccsv.html) · [来源6](https://github.com/IfcOpenShell/IfcOpenShell/commit/dc69c19aa7b05de75524acfa1e73e081239c74e6) · [来源7](https://github.com/IfcOpenShell/IfcOpenShell/releases/tag/bonsai-0.9.0-alpha2609040826)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### web-ifc

**图纸与3D · 按需引入**　[web-ifc 官方仓库](https://github.com/ThatOpen/engine_web-ifc)

- 覆盖：浏览器IFC读取/写入；IFC几何；IFC属性查询
- 许可：MPL-2.0。[许可原文](https://github.com/ThatOpen/engine_web-ifc/blob/main/LICENSE.md)
- 维护证据：发布 0.77 · 2026-03-06。[记录](https://github.com/ThatOpen/engine_web-ifc/releases/tag/0.77)

可用能力：C++/WASM 库在浏览器和 Node 读取/写入 IFC，暴露几何与属性 API。 可给现有 Three.js 提供 IFC mesh，并保留 expressID 与 GUID 关联。

接入判断：作为按需加载的 IFC Web Worker，JS/WASM 本地托管并锁同版；只把显示和拾取放前端，需审计的数量/BOM 仍由后端 IfcOpenShell 生成。

能力边界：

- 不是完整 BIM 编辑器；将几何与语义送入 KANPACE 仍需业务映射。
- 多线程 WASM 需要对应 worker 和浏览器隔离配置；JS/WASM 必须配套同版本。
- 大 IFC 的内存、实体几何支持与坐标变换需要真实文件验证。

组件许可补充：MPL 是文件级弱 copyleft；分发被覆盖/修改文件需按其条款提供源码，不可用 Three.js MIT 概括。 That Open 其他组件、付费服务与示例资产不自动适用 web-ifc 的许可。无 AI 权重。

官方证据：[来源1](https://github.com/ThatOpen/engine_web-ifc) · [来源2](https://github.com/ThatOpen/engine_web-ifc/blob/main/LICENSE.md) · [来源3](https://thatopen.github.io/engine_web-ifc/docs/) · [来源4](https://github.com/ThatOpen/engine_web-ifc/blob/main/README.md) · [来源5](https://github.com/ThatOpen/engine_web-ifc/commit/d918114e09ecedd26cc5333acbf636521f21669e) · [来源6](https://github.com/ThatOpen/engine_web-ifc/releases/tag/0.77)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### PaddleOCR（建议先锁 PP-OCRv5 det/rec）

**图纸与3D · 优先验证**　[PaddleOCR（建议先锁 PP-OCRv5 det/rec） 官方仓库](https://github.com/PaddlePaddle/PaddleOCR)

- 覆盖：扫描图OCR；中文/英文标注；坐标与置信度；BOM表格辅助
- 许可：Apache-2.0（代码）。[许可原文](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)
- 维护证据：默认分支提交 · 2026-07-22。[记录](https://github.com/PaddlePaddle/PaddleOCR/commit/2661c7c0ef5c613e8f93c6e93b2e052399f0f854)

可用能力：检测与识别文字，可输出文本、区域坐标和识别分数；有文档结构化管线。 已核验的 PP-OCRv5_server_det/rec 模型支持中英文等文本场景，适合先建立稳定基线。

接入判断：Poppler 生成定 DPI 图块，按图框/表格/标注区分块 OCR；保存原始字符串、bbox、rec_score、模型 revision。与原生 PDF/DXF 文本先比对，结果仅进入 BOM/尺寸复核界面。

能力边界：

- 尺寸符号、上下偏差、孔径/数量、引线归属和图框多尺度是工程图专项难点；普通 OCR benchmark 不证明工程正确率。
- OCR 值不可直接进入下料/CAM；应保留页区与低置信度/冲突状态，交工程人员确认。
- 模型家族和依赖更新快；本条不把仓库全部可选 VLM/第三方权重笼统判为同一许可。

组件许可补充：官方 Hugging Face 模型卡分别确认 PP-OCRv5_server_det、PP-OCRv5_server_rec 为 Apache-2.0。 部署的预处理/方向分类、表格、VL 或第三方模型须逐个锁定模型卡与许可证；本条已核验范围仅上述两权重及 PaddleOCR 代码。

官方证据：[来源1](https://github.com/PaddlePaddle/PaddleOCR) · [来源2](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE) · [来源3](https://www.paddleocr.ai/main/en/version3.x/installation.html) · [来源4](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det) · [来源5](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec) · [来源6](https://github.com/PaddlePaddle/PaddleOCR/commit/2661c7c0ef5c613e8f93c6e93b2e052399f0f854)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### Docling

**图纸与3D · 优先验证**　[Docling 官方仓库](https://github.com/docling-project/docling)

- 覆盖：文档版面；BOM表格结构化；PDF图文抽取；离线文档管线
- 许可：MIT（代码）。[许可原文](https://github.com/docling-project/docling/blob/main/LICENSE)
- 维护证据：默认分支提交 · 2026-09-04。[记录](https://github.com/docling-project/docling/commit/025b27ca2c2f040b5b9628dccffd2611246990ca)

可用能力：将 PDF 等文档转换为结构化文档，识别布局与表格，导出 JSON/Markdown 等。 可预置模型文件在离线环境运行；可以配置 OCR 或 VLM 管线。

接入判断：作为独立文档 worker 解析 BOM 表和技术说明；统一输出 part_number、quantity、material、dimensions_raw 与 page/bbox/模型来源。所有规范化字段保留原值，解析成功不自动审批入库。

能力边界：

- 表格单元格识别不等于零件实体识别，需自行定义 BOM schema、合并单元格规则与行校验。
- 版面模型/通用 VLM 不能从效果图可靠恢复准确工程几何；不得隐式补尺寸。
- 可选 OCR/VLM 引擎与远程服务来源不同，离线默认需要显式配置模型路径与关闭非本地管线。

组件许可补充：docling-project/docling-models 模型卡同时列 CDLA-Permissive-2.0 与 Apache-2.0；不得标成 MIT，实际 TableFormer/布局权重按所选文件归档条款。 docling-layout-heron 模型卡为 Apache-2.0；可选 ibm-granite/granite-docling-258M 为 Apache-2.0。 其他 OCR/VLM 可选组件与权重不自动继承以上许可；本次没有对所有可选模型做全量权利链审计。

官方证据：[来源1](https://github.com/docling-project/docling) · [来源2](https://github.com/docling-project/docling/blob/main/LICENSE) · [来源3](https://github.com/docling-project/docling/blob/main/docs/faq/index.md) · [来源4](https://github.com/docling-project/docling/blob/main/docs/usage/model_catalog.md) · [来源5](https://huggingface.co/docling-project/docling-models) · [来源6](https://huggingface.co/docling-project/docling-layout-heron) · [来源7](https://huggingface.co/ibm-granite/granite-docling-258M) · [来源8](https://github.com/docling-project/docling/commit/025b27ca2c2f040b5b9628dccffd2611246990ca)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### FreeCAD SheetMetal Workbench

**图纸与3D · 按需引入**　[FreeCAD SheetMetal Workbench 官方仓库](https://github.com/shaise/FreeCAD_SheetMetal)

- 覆盖：钣金建模；折弯展开；展开轮廓DXF；K因子/材料表
- 许可：LGPL-2.1-or-later。[许可原文](https://github.com/shaise/FreeCAD_SheetMetal/blob/master/LICENSE)
- 维护证据：默认分支提交 · 2026-08-22。[记录](https://github.com/shaise/FreeCAD_SheetMetal/commit/fd2ab6d07b9110960ff07963584e5a074ec2a6cd)

可用能力：钣金工作台支持折弯、翻边、展开，提供材料表与不同折弯 K 因子。 当前发布记录包含 solid-to-sheet-metal 与展开相关修复；可导出展开草图/DXF。

接入判断：在固定 FreeCAD 工程工作站启用 Engineering UX Mode；KANPACE 向任务传已确认材料/板厚/折弯参数，接收展开 DXF、计算依据和审查结果，再进入排料。

能力边界：

- 需要可展开的几何及真实厚度、折弯半径、K 因子/折弯表；外观无法确定这些参数。
- 复杂/不满足钣金假设的实体可能无法可靠展开，不能把任意 STEP/曲面都当钣金。
- 展开几何不是最终工艺批准：工装、回弹、加工余量和折弯次序仍需企业工艺规则。

组件许可补充：package.xml 明确 LGPL-2.1-or-later，版本 0.8.22，日期 2026-08-22；FreeCAD 与依赖仍单独计入分发清单。无权重。

官方证据：[来源1](https://github.com/shaise/FreeCAD_SheetMetal) · [来源2](https://github.com/shaise/FreeCAD_SheetMetal/blob/master/LICENSE) · [来源3](https://github.com/shaise/FreeCAD_SheetMetal/blob/master/package.xml) · [来源4](https://github.com/shaise/FreeCAD_SheetMetal#engineering-mode) · [来源5](https://freecad.github.io/Addon-Reports/) · [来源6](https://github.com/shaise/FreeCAD_SheetMetal/commit/fd2ab6d07b9110960ff07963584e5a074ec2a6cd)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### PackingSolver

**图纸与3D · 优先验证**　[PackingSolver 官方仓库](https://github.com/fontanf/packingsolver)

- 覆盖：一维型材下料；矩形板材排料；齐头切；异形排料；利用率优化
- 许可：MIT。[许可原文](https://github.com/fontanf/packingsolver/blob/master/LICENSE)
- 维护证据：默认分支提交 · 2026-09-06。[记录](https://github.com/fontanf/packingsolver/commit/c4983a29068346436f4a3bde8c3bf0f98bdd11cb)

可用能力：分别提供一维、矩形、rectangleguillotine、异形和箱体装载求解器；支持 CLI 输入与解证书。 矩形齐头切支持裁边、切缝、缺陷与旋转限制；异形支持非凸、孔、旋转/镜像及间距。

接入判断：Python 将已审批 BOM 按材料/板厚/纹理分组，生成 CSV 或异形 JSON，设置转角、切缝和工艺余量；限时运行，解析 certificate 回显布局与利用率。输出仍为排料方案，再由已验证 CAM/后处理接续。

能力边界：

- 是优化引擎，不读取完整施工图/BOM、不自动确定材料/尺寸，也不生成完整机床 G-code。
- 时间受限搜索结果未必全局最优；必须检查所有零件是否被放入、边界/间距、材料方向和遗漏。
- C++ 构建涉及多个依赖与可选求解器；不能将选择 KNITRO 等专有后端的组合称为全开源。

组件许可补充：主项目 MIT；extern/CMakeLists.txt 明列 Boost、HiGHS、fontanf 组件和可选求解器，需固定依赖清单。 建议开源构建选择 HiGHS（官方 MIT），避免启用未授权 KNITRO；第三方 Python wrapper 另有其许可与维护状态，不等于官方 Python SDK。 当前 CMake 默认 PACKINGSOLVER_USE_CLP=ON、USE_HIGHS=ON、USE_KNITRO=OFF；若选仅 HiGHS 的初版组合，应显式关闭 CLP 并核对产物依赖。未把默认构建说成只有 MIT 依赖。

官方证据：[来源1](https://github.com/fontanf/packingsolver) · [来源2](https://github.com/fontanf/packingsolver/blob/master/LICENSE) · [来源3](https://github.com/fontanf/packingsolver#rectangleguillotine-solver) · [来源4](https://github.com/fontanf/packingsolver#irregular-solver) · [来源5](https://github.com/fontanf/packingsolver/blob/master/extern/CMakeLists.txt) · [来源6](https://github.com/ERGO-Code/HiGHS/blob/master/LICENSE.txt) · [来源7](https://github.com/fontanf/packingsolver/commit/c4983a29068346436f4a3bde8c3bf0f98bdd11cb) · [来源8](https://github.com/fontanf/packingsolver/blob/master/CMakeLists.txt)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### libnest2d

**图纸与3D · 备选**　[libnest2d 官方仓库](https://github.com/tamasmeszaros/libnest2d)

- 覆盖：二维嵌套算法；矩形/凸多边形布局
- 许可：LGPL-3.0。[许可原文](https://github.com/tamasmeszaros/libnest2d/blob/master/LICENSE.txt)
- 维护证据：默认分支提交 · 2022-11-16。[记录](https://github.com/tamasmeszaros/libnest2d/commit/663daa69e1d7478669f714218e27681edbc96640)

可用能力：C++11 模板/可编译库，提供 no-fit-polygon 放置与布局策略；源于 PrusaSlicer 的排列功能。 可以接自有几何后端或默认 Clipper/Boost/NLopt，输出变换后的零件。

接入判断：若仅做凸形/矩形快速布局，可独立 C++ worker PoC；Python 用子进程或自建绑定。复杂凹形/套孔优先评测 PackingSolver，避免在未满足算法边界时强行接入。

能力边界：

- 官方 README 明说功能和文档不完整，目前擅长矩形/凸闭多边形，不考虑孔洞与凹形。
- 上游默认分支可见最新提交 2022-11-16，未归档不代表维护充分。
- 没有完整工艺/库存/余料/刀路管理；新平台编译和几何异常需自行承担。

组件许可补充：主库 LGPL3；默认依赖 Clipper/Boost 为各自 Boost 许可体系，NLopt 有其独立 LGPL 许可。静态/头文件集成需满足实际分发义务。无权重。

官方证据：[来源1](https://github.com/tamasmeszaros/libnest2d) · [来源2](https://github.com/tamasmeszaros/libnest2d/blob/master/LICENSE.txt) · [来源3](https://github.com/tamasmeszaros/libnest2d/blob/master/README.md) · [来源4](https://github.com/tamasmeszaros/libnest2d/commit/663daa69e1d7478669f714218e27681edbc96640)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### Deepnest（deepnest-next 社区维护分支）

**图纸与3D · 谨慎评估**　[Deepnest（deepnest-next 社区维护分支） 官方仓库](https://github.com/deepnest-next/deepnest)

- 覆盖：二维异形排料；共线合并；SVG/DXF转换工作流
- 许可：混合：根 MIT；main/deepnest.js GPLv3；其他 MIT/Boost 等。[许可原文](https://github.com/deepnest-next/deepnest/blob/main/LICENSE)
- 维护证据：默认分支提交 · 2026-07-28。[记录](https://github.com/deepnest-next/deepnest/commit/4d8b57f85ffc1831069549e3555eb7d97c408967)

可用能力：Electron 桌面排料工具，继承 SVGnest/Deepnest，支持共线合并和复杂轮廓近似。 DXF 支持通过转换；社区分支有持续维护。

接入判断：先当工程师外部桌面工具，用已校核 SVG/轮廓文件交换，回收排版结果；本地保密场景先验证并消除在线格式转换依赖。若改造成 Web 服务，按实际 GPL 组件及分发结构评估，不能只改包名。

能力边界：

- README 把无需在线转换的原生 DXF、部分新核心等列为 Upcoming，不能当作已交付功能。
- 官方 LICENSES.md 列 main/deepnest.js 为 GPLv3，根 MIT 不能概括整套。
- 原版 Jack000/Deepnest 长期低活跃；社区新项目 deepnest-next/deepnest-next 又是独立代码线（组织页标 AGPL），不要混用版本/许可。

组件许可补充：许可关键证据是官方 LICENSES.md，而非首页一句 MIT。 原版核心文件头同样声明 GPLv3；deepnest-next/deepnest 与 deepnest-next/deepnest-next 是不同仓库。无 AI 权重。

官方证据：[来源1](https://github.com/deepnest-next/deepnest) · [来源2](https://github.com/deepnest-next/deepnest/blob/main/LICENSE) · [来源3](https://github.com/deepnest-next/deepnest/blob/main/LICENSES.md) · [来源4](https://github.com/deepnest-next/deepnest/blob/main/BUILD.md) · [来源5](https://github.com/deepnest-next) · [来源6](https://github.com/Jack000/Deepnest/blob/master/main/deepnest.js) · [来源7](https://github.com/deepnest-next/deepnest/commit/4d8b57f85ffc1831069549e3555eb7d97c408967)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### PyCAM

**图纸与3D · 备选**　[PyCAM 官方仓库](https://github.com/SebKuzminsky/pycam)

- 覆盖：三轴CAM；2D/3D转刀路；G-code；脚本化加工任务
- 许可：GPL-3.0-or-later。[许可原文](https://github.com/SebKuzminsky/pycam/blob/master/LICENSE.TXT)
- 维护证据：默认分支提交 · 2021-11-25。[记录](https://github.com/SebKuzminsky/pycam/commit/55e3129f518e470040e79bb00515b4bfcf36c172)

可用能力：Python 三轴刀路生成器，从二维/三维模型生成 G-code。 有 GUI 与 scripted toolpath processing CLI，可使用 flow specification 文件。

接入判断：仅在独立 Linux PoC 中读已验证模型和工艺参数并输出文件，比较 FreeCAD CAM 的刀路质量/速度；禁止直接连接机床。若没有特定收益则不引入第二套 CAM 运行时。

能力边界：

- 默认分支最新可见提交 2021-11-25；安装说明 Windows 为 TODO、macOS 仍有 Python2 待迁移文字。
- 不适合作为未经验证的跨平台生产基础；没有理由承诺五轴、所有机床后处理或完整防碰撞。
- 生成刀路前仍需材料、刀具、原点、装夹、进给和机床参数，不能由视觉效果自行推断。

组件许可补充：LICENSE.TXT 明确 GPL3 或以后版本；GUI/几何依赖分别核验。只读调用子进程不等于所有再分发义务消失。无权重。

官方证据：[来源1](https://github.com/SebKuzminsky/pycam) · [来源2](https://github.com/SebKuzminsky/pycam/blob/master/LICENSE.TXT) · [来源3](https://github.com/SebKuzminsky/pycam/blob/master/README.md) · [来源4](https://github.com/SebKuzminsky/pycam/blob/master/INSTALL.md) · [来源5](https://github.com/SebKuzminsky/pycam/commit/55e3129f518e470040e79bb00515b4bfcf36c172)

仅核验官方源码/文档/模型卡/发布元数据；未安装、未运行样例、未用 KANPACE 实际图纸做兼容性或性能测试。

### Google OR-Tools

**制造与排产 · 优先验证**　[Google OR-Tools 官方仓库](https://github.com/google/or-tools)

- 覆盖：有限产能排程；串并行工序；人员班次；重排优化
- 许可：Apache-2.0；仓库整体许可证及需保留的版权/NOTICE按分发依赖核对。。[许可原文](https://github.com/google/or-tools/blob/stable/LICENSE)
- 维护证据：发布 v9.15 · 2026-01-12。[记录](https://github.com/google/or-tools/releases/tag/v9.15)

可用能力：CP-SAT 官方 Job Shop 示例建模前后工序依赖、设备互斥和最短总工期，并提供 Python API。 官方 Employee Scheduling 示例覆盖人员与班次分配、覆盖需求及偏好目标。 将并行前置关系、人员+工作中心双资源、班次休息、插单冻结区、换单代价建模为约束/目标是 KANPACE 的集成工作（判断），不是现成工厂配置界面。

接入判断：第一优先：作为可替换的 Python 排程库/独立进程。输入版本化计划快照，输出建议排程及求解状态，由 KANPACE 校验后发布。

能力边界：

- 求解器不会自动生成正确业务模型，示例的不可中断任务不能直接等同于 KANPACE 暂停/恢复。
- 新增 Python 原生扩展依赖；必须设置求解时限，并处理 FEASIBLE/INFEASIBLE/UNKNOWN，不能承诺总能获得最优解。
- 保持现有启发式为可用回退；缺料、质量和图纸版本门槛仍由 KANPACE 执行。

官方证据：[来源1](https://developers.google.com/optimization/scheduling/job_shop) · [来源2](https://developers.google.com/optimization/scheduling/employee_scheduling) · [来源3](https://github.com/google/or-tools) · [来源4](https://github.com/google/or-tools/blob/stable/LICENSE) · [来源5](https://github.com/google/or-tools/releases/tag/v9.15)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Timefold Solver Community

**制造与排产 · 按需引入**　[Timefold Solver Community 官方仓库](https://github.com/TimefoldAI/timefold-solver)

- 覆盖：约束规划；人员技能与班次；动态重排；任务分配
- 许可：Community Apache-2.0；Enterprise 与 Plus 为专有商业版本。。[许可原文](https://github.com/TimefoldAI/timefold-solver/blob/main/LICENSE.txt)
- 维护证据：发布 v2.6.0 · 2026-09-01。[记录](https://github.com/TimefoldAI/timefold-solver/releases/tag/v2.6.0)

可用能力：Java/Kotlin 约束求解器；官方仓库列员工排班、任务分配、维护计划及 Job Shop 场景。 当前 Solver 文档支持 ProblemChange 和固定部分规划实体，适合在插单或停机后保留已承诺安排。 硬/软约束及惩罚权重需要 KANPACE 自己定义；不能把 Timefold Platform 的预建商业模型能力直接算作开源 Solver。

接入判断：P2 排程备选：当规则持续变化且团队愿意维护 Java/Kotlin 时，作为外挂求解服务；首轮先用 OR-Tools 对照。

能力边界：

- 官方已停止 Python Solver beta 的主动开发与修复；新项目不要依赖该 Python 版本。
- Enterprise/Plus 与开源 Community 不同；当前企业文档将多线程求解、nearby selection、score analysis 等列为商业特性。
- 需新增 JVM 服务与模型，不适合作为当前标准库 Python 的无缝替换。

官方证据：[来源1](https://github.com/TimefoldAI/timefold-solver) · [来源2](https://docs.timefold.ai/timefold-solver/latest/responding-to-change/real-time-planning) · [来源3](https://github.com/TimefoldAI/timefold-solver/discussions/1698) · [来源4](https://docs.timefold.ai/timefold-solver/latest/enterprise-edition/enterprise-edition) · [来源5](https://timefold.ai/terms) · [来源6](https://github.com/TimefoldAI/timefold-solver/blob/main/LICENSE.txt) · [来源7](https://github.com/TimefoldAI/timefold-solver/releases/tag/v2.6.0)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### frePPLe Community

**制造与排产 · 按需引入**　[frePPLe Community 官方仓库](https://github.com/frePPLe/frepple)

- 覆盖：APS；有限物料与有限产能；What-if；Excel/CSV/REST；Odoo互联
- 许可：当前 Community MIT（自8.0.0）；Enterprise/Cloud额外功能专有；旧7.x AGPL须按具体版本区别。。[许可原文](https://github.com/frePPLe/frepple/blob/master/COPYING)
- 维护证据：发布 9.18.0 · 2026-08-28。[记录](https://github.com/frePPLe/frepple/releases/tag/9.18.0)

可用能力：当前官方 editions 页面把有限物料、有限产能生产计划、预测、方案比较、Excel/CSV/REST 和 Odoo 双向集成列入 Community。 资源模型支持有限产能及日历；适合已有订单/BOM/资源/库存数据后的 APS 方案比较。 不是单一 Python 排程函数，而是独立规划系统；工序采集、质量状态与图纸来源仍需由 KANPACE 管。

接入判断：P2 外挂 APS：保留 KANPACE 为执行层。优先验证 CE 的数据导入、有限资源计划及计划建议回传；不要整套替换。

能力边界：

- 关键更正：8.0.0（2023-06-03）已从 AGPL 改为 MIT；AGPL旧宣传册不能用于当前版本结论。
- 交互式 Gantt、库存优化规划、交期报价、换型矩阵优化、保质期规划列在 Cloud/Enterprise，不能算入CE。
- 要建立订单、物料、资源、工序与计划回写映射；避免与客户ERP并列维护两份权威库存。

官方证据：[来源1](https://frepple.com/editions/) · [来源2](https://frepple.com/docs/current/license.php) · [来源3](https://frepple.com/docs/current/release-notes.html) · [来源4](https://frepple.com/docs/current/model-reference/resources.html) · [来源5](https://github.com/frePPLe/frepple) · [来源6](https://github.com/frePPLe/frepple/blob/master/COPYING) · [来源7](https://github.com/frePPLe/frepple/releases/tag/9.18.0)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### ERPNext + Frappe Framework

**制造与排产 · 模式参考**　[ERPNext + Frappe Framework 官方仓库](https://github.com/frappe/erpnext)

- 覆盖：ERP/MRP；工单Job Card；质量检验；采购外协；库存成本；Excel/REST
- 许可：ERPNext GPL-3.0；Frappe Framework MIT。云托管/支持服务与软件许可须分开。。[许可原文](https://github.com/frappe/erpnext/blob/develop/license.txt)
- 维护证据：发布 v16.34.1 · 2026-09-02。[记录](https://github.com/frappe/erpnext/releases/tag/v16.34.1)

可用能力：Work Order/Job Card 与工作中心生产容量、工作时间、假日及加班设置支持基础容量计划。 质量检验可关联收货、交付、外协收货或Job Card，并要求先完成检验再提交相关收发单据。 外协可跟踪供料给供应商后加工；Frappe提供DocType、权限、表单与REST接口，ERPNext支持数据导入。

接入判断：P1 参考业务模型、P2 接客户ERP：用REST/文件交换订单、物料、采购/外协状态、检验及成本；不迁移KANPACE内核到Frappe。

能力边界：

- ERPNext 是 GPL-3.0，不能因其底层 Frappe 是MIT就把ERPNext全部当MIT。
- 基础工作中心排时不等于多资源、插单最小扰动的高级APS。
- 整体替换会改变客户ERP/Excel工作流并引入Frappe运维；优先同步必要主数据/业务结果。

官方证据：[来源1](https://docs.frappe.io/erpnext/production-and-material-planning-capacity-planning) · [来源2](https://docs.frappe.io/erpnext/quality-inspection) · [来源3](https://docs.frappe.io/erpnext/subcontracting-in-erpnext) · [来源4](https://docs.frappe.io/framework/user/en/api/rest) · [来源5](https://docs.frappe.io/erpnext/data-import) · [来源6](https://github.com/frappe/frappe/blob/develop/LICENSE) · [来源7](https://github.com/frappe/erpnext/blob/develop/license.txt) · [来源8](https://github.com/frappe/erpnext) · [来源9](https://github.com/frappe/erpnext/releases/tag/v16.34.1)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Odoo Community 19

**制造与排产 · 按需引入**　[Odoo Community 19 官方仓库](https://github.com/odoo/odoo)

- 覆盖：ERP/MRP；采购库存；BOM；外协；成本/交付接口
- 许可：Community 19 LGPL-3.0；Enterprise Odoo Enterprise Edition License v1.0专有；各App须逐模块核验。。[许可原文](https://www.odoo.com/documentation/19.0/legal/licenses.html)
- 维护证据：默认分支提交 · 2026-09-05。[记录](https://github.com/odoo/odoo/commit/1a13ceeaee12fe5cc50f287c31f217d4be2a2eaf)

可用能力：官方公开19.0仓库包含 Manufacturing (mrp) 与 mrp_subcontracting，后者明确为外协生产模块。 官方版本对比列 Inventory、Manufacturing (MRP)、Purchase 在CE和EE均可用。 适合连接现有客户 Odoo 的物料、BOM、采购、库存与收发单据；高级生产界面须区分版别。

接入判断：P2 客户系统适配；不要为获得更完整ERP而重建KANPACE。可借鉴mrp/stock/purchase模型。

能力边界：

- 官方版本比较的 Barcode、Shopfloor/Control Panel/Scheduling、PLM、Quality 行为 CE叉/EE勾（已读取表格HTML核验）。
- Odoo Apps 的第三方/OCA模块有各自许可证与成熟度；不要把OCA或付费App等同于官方CE。
- 不能把统一官方用户文档中的EE特性整体算入CE；版本升级/本地化有额外工程成本。

官方证据：[来源1](https://github.com/odoo/odoo/blob/19.0/addons/mrp/__manifest__.py) · [来源2](https://github.com/odoo/odoo/blob/19.0/addons/mrp_subcontracting/__manifest__.py) · [来源3](https://www.odoo.com/page/editions) · [来源4](https://www.odoo.com/documentation/19.0/legal/licenses.html) · [来源5](https://github.com/odoo/odoo) · [来源6](https://github.com/odoo/odoo/commit/1a13ceeaee12fe5cc50f287c31f217d4be2a2eaf)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Tryton

**制造与排产 · 模式参考**　[Tryton 官方仓库](https://github.com/tryton/tryton)

- 覆盖：模块化ERP；工艺路线工单工时；外协；批次库存；质量阻断；成本
- 许可：GPL-3.0-or-later；已核对 trytond/pyproject.toml及LICENSE；第三方模块独立核验。。[许可原文](https://github.com/tryton/tryton/blob/main/trytond/LICENSE)
- 维护证据：发布 8.0 LTS · 2026-04-21。[记录](https://discuss.tryton.org/t/tryton-release-8-0/9208)

可用能力：官方生产模块目录提供Production、Routing、Work、Work Timesheet、Outsourcing与Split。 Quality模块把控制点、检验、异常告警分开；检验失败会阻断关联单据，直至告警解决或延期。 Stock Lot扩展库存批次；库存模块有成本计价/重算，外协模块可按工艺路线创建采购并计入生产成本。

接入判断：P2 业务模型参考/P3 可选客户ERP外挂；优先借鉴质量控制点→检验→异常阻断结构。

能力边界：

- GitHub是官方镜像；主代码平台是 code.tryton.org，不应以GitHub星数判断成熟度。
- 没有本次证据支持其具有成熟高级有限产能优化器；工艺路线/工单能力不等于APS。
- ERP结构与权限需要学习，当前KANPACE重写成Tryton模块会扩大范围。

官方证据：[来源1](https://docs.tryton.org/latest/production.html) · [来源2](https://docs.tryton.org/latest/modules-quality/design.html) · [来源3](https://docs.tryton.org/latest/modules-stock-lot/design.html) · [来源4](https://docs.tryton.org/latest/modules-stock/usage/index.html) · [来源5](https://docs.tryton.org/6.0/modules-production-outsourcing/) · [来源6](https://github.com/tryton/tryton/blob/main/trytond/pyproject.toml) · [来源7](https://discuss.tryton.org/t/tryton-release-8-0/9208) · [来源8](https://github.com/tryton/tryton/blob/main/trytond/LICENSE) · [来源9](https://github.com/tryton/tryton)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### OpenProject Community

**制造与排产 · 按需引入**　[OpenProject Community 官方仓库](https://github.com/opf/openproject)

- 覆盖：工程项目/WBS；依赖甘特；工时成本预算；Excel同步参考；工作流
- 许可：GPL-3.0；CE可自托管，Enterprise付费附加功能与托管支持需区分。。[许可原文](https://github.com/opf/openproject/blob/dev/LICENSE)
- 维护证据：发布 v17.8.0 · 2026-09-02。[记录](https://github.com/opf/openproject/releases/tag/v17.8.0)

可用能力：成熟项目工作包、关系/层级、甘特、工时及成本预算系统。 官方提供Excel synchronization文档，适合作为保留Excel编辑习惯的接口设计参考。 适合项目/施工阶段与交付里程碑；不是物料库存系统或制造排程求解器。

接入判断：P2 装修/工程场景的参考系统；必要时仅对接项目与里程碑。不要取代工序状态机。

能力边界：

- 17.7 新Resource management module明确为Enterprise add-on；不能把它当CE免费有限资源排程。
- 项目依赖日期自动计算不等于人员+设备双资源有限产能求解。
- 引入Rails/PostgreSQL应用会增加维护；避免又让工人录入第二套任务。

官方证据：[来源1](https://www.openproject.org/community-edition/) · [来源2](https://www.openproject.org/docs/faq/) · [来源3](https://www.openproject.org/docs/release-notes/17-7-0/) · [来源4](https://www.openproject.org/docs/system-admin-guide/integrations/excel-synchronization/) · [来源5](https://www.openproject.org/docs/user-guide/time-and-costs/cost-tracking/) · [来源6](https://github.com/opf/openproject/blob/dev/LICENSE) · [来源7](https://github.com/opf/openproject) · [来源8](https://github.com/opf/openproject/releases/tag/v17.8.0)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### bpmn-js / diagram-js

**制造与排产 · 优先验证**　[bpmn-js / diagram-js 官方仓库](https://github.com/bpmn-io/bpmn-js)

- 覆盖：可视化流程模板；BPMN2.0导入导出；流程图编辑
- 许可：bpmn-js：bpmn.io License（MIT式基础+不可移除/遮挡水印条款）；diagram-js：MIT。。[许可原文](https://github.com/bpmn-io/bpmn-js/blob/develop/LICENSE)
- 维护证据：发布 v18.28.0 · 2026-09-04。[记录](https://github.com/bpmn-io/bpmn-js/releases/tag/v18.28.0)

可用能力：bpmn-js 是浏览器 BPMN 2.0 渲染与建模工具；diagram-js 是底层通用图编辑工具。 可用来编辑工艺串并行结构、任务节点和业务扩展属性；自定义节点/校验及KANPACE流程模板映射仍需实现（判断）。 流程图保存成功只说明模型可序列化；运行中的版本选择、权限、前置门槛与工牌事件执行需要后端状态机。

接入判断：P1 UI能力候选：只做流程模板编辑器，转换到受约束的KANPACE工艺DAG；若无BPMN互操作需求可优先diagram-js。

能力边界：

- bpmn-js 当前是 bpmn.io 自定义许可证，附必须保留且完整可见的bpmn.io水印要求；不能标成纯MIT。
- diagram-js 才是MIT；用它自建业务图编辑器仍需自行实现序列化/校验。
- BPMN UI不等于BPMN执行引擎，也不会提供有限产能、库存或质量业务。

官方证据：[来源1](https://bpmn.io/toolkit/bpmn-js/) · [来源2](https://github.com/bpmn-io/bpmn-js) · [来源3](https://github.com/bpmn-io/bpmn-js/blob/develop/LICENSE) · [来源4](https://github.com/bpmn-io/diagram-js/blob/develop/LICENSE) · [来源5](https://github.com/bpmn-io/diagram-js/releases/tag/v15.26.0) · [来源6](https://github.com/bpmn-io/bpmn-js/releases/tag/v18.28.0)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Temporal

**制造与排产 · 后期考虑**　[Temporal 官方仓库](https://github.com/temporalio/temporal)

- 覆盖：可靠长流程；重试恢复；外部系统编排；Python SDK
- 许可：Temporal Server MIT；具体SDK及依赖按版本核验；Temporal Cloud为另行提供的商业托管服务。。[许可原文](https://github.com/temporalio/temporal/blob/main/LICENSE)
- 维护证据：发布 v1.31.2 · 2026-07-08。[记录](https://github.com/temporalio/temporal/releases/tag/v1.31.2)

可用能力：Temporal Server执行持久化Workflow，可处理间歇失败并重试操作；提供Python SDK。 可以编排耗时的ERP导入、图纸处理、外协回执等跨服务工作（判断）。 不提供生产排程、BOM、库存、成本或可视化工艺模板；它处理软件流程的持久性。

接入判断：P3 后期可靠集成基础设施；当前不要替换状态机或为单机部署过早引入。

能力边界：

- 需要独立Server和Worker运维，以及确定性Workflow、版本演进和Activity幂等设计。
- 自动重试不能保证ERP收货/扣料这类副作用自动恰好一次；仍需业务幂等键（判断）。
- 将当前本地状态机整体搬进Temporal会提高系统复杂度且不能直接补齐制造规则。

官方证据：[来源1](https://github.com/temporalio/temporal) · [来源2](https://docs.temporal.io/develop/python) · [来源3](https://github.com/temporalio/temporal/blob/main/LICENSE) · [来源4](https://github.com/temporalio/temporal/releases/tag/v1.31.2)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Camunda 8 / Camunda 7 CE（排除性比较）

**制造与排产 · 谨慎评估**　[Camunda 8 / Camunda 7 CE（排除性比较） 官方仓库](https://github.com/camunda/camunda)

- 覆盖：BPMN执行；人工任务；流程编排
- 许可：Camunda8核心源码Camunda License v1/编译版本专有生产许可；Camunda7 CE历史Apache-2.0但已结束官方社区维护。。[许可原文](https://docs.camunda.io/docs/reference/licenses/)
- 维护证据：发布 8.9.19 · 2026-09-04。[记录](https://github.com/camunda/camunda/releases/tag/8.9.19)

可用能力：成熟流程编排产品，包含Zeebe、Operate、Tasklist等组件。 当前8.6+许可规则与历史Camunda 7 Apache开源模型不同。

接入判断：排除默认方案；需要开源BPMN执行时评估Flowable，只有可视化需求用bpmn-js/diagram-js。

能力边界：

- 8.6及以后核心源码为Camunda License v1，编译分发为专有许可；生产使用需购买Enterprise。
- 官方Camunda 7 CE在2025-10-14最终7.24后不再给社区版安全/维护更新；不能为避开8的商业许可回退到7新建商用系统。
- Desktop Modeler MIT、部分Connector SDK Apache不代表Camunda 8执行平台整体开源。

官方证据：[来源1](https://docs.camunda.io/docs/reference/licenses/) · [来源2](https://camunda.com/blog/2024/10/camunda-licensing-what-you-need-to-know/) · [来源3](https://camunda.com/platform-7/performance/) · [来源4](https://forum.camunda.io/t/camunda-7-community-end-of-life-eol-clarification/60208) · [来源5](https://github.com/camunda/camunda) · [来源6](https://github.com/camunda/camunda/releases/tag/8.9.19)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### Flowable Open Source

**制造与排产 · 后期考虑**　[Flowable Open Source 官方仓库](https://github.com/flowable/flowable-engine)

- 覆盖：BPMN执行；DMN规则；CMMN案例；人工/系统任务；REST
- 许可：Open-source engine Apache-2.0；Flowable商业平台另行许可。。[许可原文](https://github.com/flowable/flowable-engine/blob/main/LICENSE)
- 维护证据：发布条目更新 Flowable 8.0.0 Release · 2026-02-27。[记录](https://github.com/flowable/flowable-engine/releases/tag/flowable-8.0.0)

可用能力：Java开源BPMN、CMMN、DMN引擎，可嵌入Java应用或独立服务，提供Java与REST API。 适合真正需要可部署BPMN语义、等待人工操作和规则决策的流程后端。 生产工艺、批次库存、资源排程与成本规则仍是业务应用责任。

接入判断：P3 真正BPMN运行时备选；先用受约束流程模板+现有状态机，复杂度达到需要时再挂接。

能力边界：

- 开源Engine与Flowable商业平台/设计服务分开；免费使用某设计服务不等于该服务代码开源。
- 新增Java服务和流程引擎持久状态，需防止其与KANPACE状态机同时决定同一工单。
- 仅为画图无须引擎。

官方证据：[来源1](https://github.com/flowable/flowable-engine) · [来源2](https://www.flowable.com/open-source-download) · [来源3](https://www.flowable.com/open-source/docs/bpmn/ch02-GettingStarted) · [来源4](https://github.com/flowable/flowable-engine/blob/main/LICENSE) · [来源5](https://github.com/flowable/flowable-engine/releases/tag/flowable-8.0.0)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### OpenBoxes

**制造与排产 · 模式参考**　[OpenBoxes 官方仓库](https://github.com/openboxes/openboxes)

- 覆盖：WMS；库位/批次/有效期；收货拣货发运；采购；Excel/API
- 许可：EPL-1.0；仓库LICENSE.md已核验。。[许可原文](https://github.com/openboxes/openboxes/blob/develop/LICENSE.md)
- 维护证据：发布 v0.9.8-hotfix1 · 2026-08-14。[记录](https://github.com/openboxes/openboxes/releases/tag/v0.9.8-hotfix1)

可用能力：有医疗/人道物流背景的仓储系统；支持库位、批次/序列、有效期、库存流水、收货、拣货和发运。 官方提供REST API与表格导入；批次/有效期要求可在关键事务时校验。 可借鉴库存流水/批次追溯及装箱发运，不是完整MES。

接入判断：P2 WMS参考/P3外挂；本期优先借鉴出入库流水与批次，只有仓库复杂度足够才独立部署。

能力边界：

- 产品模型主要服务仓储/医疗物流，不提供工艺执行、BOM制造排程或专用质量管理。
- 若客户ERP已有库存账，另建WMS必须先决定仓库操作与财务库存的权威边界。
- EPL不是MIT；分发修改版本时需遵守其源代码/许可证义务。

官方证据：[来源1](https://github.com/openboxes/openboxes) · [来源2](https://openboxes.com/features/) · [来源3](https://docs.openboxes.com/en/stable/about/features/) · [来源4](https://help.openboxes.com/article/69-lot-and-expiry-control) · [来源5](https://github.com/openboxes/openboxes/blob/develop/LICENSE.md) · [来源6](https://github.com/openboxes/openboxes/releases/tag/v0.9.8-hotfix1)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### qcadoo MES Community

**制造与排产 · 谨慎评估**　[qcadoo MES Community 官方仓库](https://github.com/qcadoo/mes)

- 覆盖：MES参考；工艺版本；BOM与工序；工时成本定额
- 许可：GNU AGPLv3（LICENSE文件允许v3或以后版本）；商业版本另行提供。。[许可原文](https://github.com/qcadoo/mes/blob/master/LICENSE.txt)
- 维护证据：发布 3.1.19 · 2026-08-27。[记录](https://github.com/qcadoo/mes/releases/tag/3.1.19)

可用能力：长期维护的中小制造企业MES项目；官方产品工艺页说明BOM+生产工序、工艺版本状态、每道工序的时间和成本定额。 可作为工艺模板、工单与成本结构的参考，但官网全部功能并不都是开源Community。

接入判断：仅P2参考，不作为KANPACE默认替换或免费REST外挂；受版别与AGPL边界限制。

能力边界：

- 官方README明确 REST API集成、现成ERP/SCADA连接、Gantt排程、仓库物料流、维护计划等为商业版附加功能。
- Community AGPLv3；嵌入/修改后交付或网络使用需审视具体许可义务，不能标成闭源产品随意复制的模块。
- 不得把商业官网的完整MES功能推断为开源仓库已有；本次未跑系统验证CE功能细节。

官方证据：[来源1](https://github.com/qcadoo/mes) · [来源2](https://www.qcadoo.com/en/functions-technologies/) · [来源3](https://github.com/qcadoo/mes/releases/tag/3.1.19) · [来源4](https://github.com/qcadoo/mes/blob/master/LICENSE.txt)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### InvenTree

**制造与排产 · 模式参考**　[InvenTree 官方仓库](https://github.com/inventree/InvenTree)

- 覆盖：库存零件/BOM；批次序列；装配Build；测试验收；采购外协；REST插件
- 许可：MIT；插件/第三方工具按各自许可核验。。[许可原文](https://github.com/inventree/InvenTree/blob/master/LICENSE)
- 维护证据：发布 1.5.2 · 2026-08-25。[记录](https://github.com/inventree/InvenTree/releases/tag/1.5.2)

可用能力：Python/Django库存系统，提供REST与插件机制，适合零件/库存与BOM管理。 Build Order按BOM分配与消耗库存，可创建子装配、批次输出、外部供应商制造；可记录每件可追踪输出的测试结果。 测试模板可定义必需结果/附件/数值；适合作为非标装配与工牌硬件自身的零部件、验收追溯参考。

接入判断：P1 业务参考、P2可选外挂：优先验证小型装配/库存/测试模型；客户已有ERP时用其作为边界设计参考即可。

能力边界：

- Build的开始/目标日期与日历不是有限产能排程。
- 库存/装配系统不是完整财务ERP或覆盖CAPA/审核的完整QMS；不能把测试结果记录等同于全部质量管理。
- 官方完成Build存在允许人工覆盖部分未完成/未分配警告的选项；KANPACE关键质量/缺料门槛应明确由谁执行。

官方证据：[来源1](https://github.com/inventree/InvenTree) · [来源2](https://docs.inventree.org/en/stable/manufacturing/build/) · [来源3](https://docs.inventree.org/en/latest/manufacturing/build/) · [来源4](https://docs.inventree.org/en/1.5.x/api/schema/build/) · [来源5](https://docs.inventree.org/en/latest/api/schema/stock/) · [来源6](https://github.com/inventree/InvenTree/blob/master/LICENSE) · [来源7](https://github.com/inventree/InvenTree/releases/tag/1.5.2)

官方文档/源码元数据核验，未安装运行或回放实际生产数据。

### ESP-IDF（含官方 OTA、rollback、Secure Boot、Flash/NVS encryption）

**硬件与工业通信 · 沿用完善**　[ESP-IDF（含官方 OTA、rollback、Secure Boot、Flash/NVS encryption） 官方仓库](https://github.com/espressif/esp-idf)

- 覆盖：官方 ESP32-C3 SDK；FreeRTOS、Wi-Fi、NVS、HTTP/TLS；OTA 双槽、启动自检回滚、签名与设备密钥能力
- 许可：主仓库 Apache-2.0；包含的第三方组件和二进制库须按各自许可证核验，不把整个 SDK 供应链一概当 Apache。。[许可原文](https://github.com/espressif/esp-idf/blob/master/LICENSE)
- 维护证据：发布条目更新 ESP-IDF Release v6.1 · 2026-08-27。[记录](https://github.com/espressif/esp-idf/releases/tag/v6.1)

可用能力：ESP32-C3 RISC-V 正式目标 2.4GHz STA/AP、TCP/IP、HTTPS esp_https_ota / esp_ota_*，可做固件签名验证

接入判断：保留 cabinet-badge-1/protocol1 的业务状态机与持久化语义，将硬件、传输、UI 分层。
为 OTA 先拿真实 firmware.bin 大小和字体/图片占用做预算；可能需要瘦身字体、共享只读资源，或下一代更大 Flash 机型。
未来双槽版在首次启动检查显示、触摸、NVS、业务存储后才 mark_app_valid；失败回滚。
不把安全启动/加密开关直接带入当前试验板；本次只读研究，没有烧写或 eFuse 操作。

能力边界：

- 本板 README 为 4MB Flash，单个 3MB app 加 0xF0000 LittleFS；仅有 otadata 不构成双槽 OTA，不能直接承诺回滚。
- C3 单核最高160MHz、400KB SRAM；没有可按 S3 示例使用的大容量 PSRAM。
- 版本跨 IDF4→5→6 涉及驱动及接口迁移；最新 SDK 可维护不代表当前 PlatformIO 依赖可无改动替换。
- Secure Boot、Flash encryption 与 HTTPS 分别解决镜像真实性、静态存储和传输问题；NVS 凭据须另用 NVS encryption。首次量产 eFuse 方案需要独立恢复设计。

官方证据：[来源1](https://documentation.espressif.com/esp32-c3_datasheet_en.html) · [来源2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/system/ota.html) · [来源3](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32c3/security/secure-boot-v2.html) · [来源4](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/security/flash-encryption.html) · [来源5](https://github.com/espressif/esp-idf/blob/master/LICENSE) · [来源6](https://github.com/espressif/esp-idf) · [来源7](https://github.com/espressif/esp-idf/releases/tag/v6.1)

仅研究；未连接或烧写设备，未执行候选固件。

### Arduino-ESP32

**硬件与工业通信 · 沿用完善**　[Arduino-ESP32 官方仓库](https://github.com/espressif/arduino-esp32)

- 覆盖：当前固件所用 API 与编程模型；WiFi、WebServer、Preferences、LittleFS、USB Serial；可作为 ESP-IDF component 使用
- 许可：核心 LGPL-2.1-or-later；依赖和子组件分别核验。。[许可原文](https://github.com/espressif/arduino-esp32/blob/master/LICENSE.md)
- 维护证据：发布条目更新 Arduino Release v3.3.11 based on ESP-IDF v5.5.5 · 2026-07-23。[记录](https://github.com/espressif/arduino-esp32/releases/tag/3.3.11)

可用能力：正式支持 ESP32-C3 兼容当前 Adafruit 显示依赖及 Python USB NDJSON 桥

接入判断：保持现有 platformio.ini 和固定 Git 提交，新增 transport adapter 复用 execution_event / execution_ack。
需要 IDF5.3+ 的新组件时单独建升级验证分支，不把新组件 manifest 生搬到旧 core。
记录 LGPL 核心及现有字体/图像库的第三方声明。

能力边界：

- PlatformIO espressif32@6.12.0 不等于 Arduino core 6.12；README 明确当前以 Arduino2 兼容代码为基线。
- 上游当前 3.3.11 基于 IDF5.5.5；4.0.0-alpha1 是预发布，不能把 alpha 当量产默认。
- 升级 core 后需重验 SPI_MODE3、40MHz、USB枚举、ESP-NOW 回调、LittleFS、触摸、报工重试。

官方证据：[来源1](https://github.com/espressif/arduino-esp32/releases/tag/3.3.11) · [来源2](https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/Arduino.h) · [来源3](https://esphome.io/components/esp32/) · [来源4](https://github.com/espressif/arduino-esp32/blob/master/LICENSE.md) · [来源5](https://github.com/espressif/arduino-esp32)

仅研究；未连接或烧写设备，未执行候选固件。

### LVGL

**硬件与工业通信 · 按需引入**　[LVGL 官方仓库](https://github.com/lvgl/lvgl)

- 覆盖：嵌入式按钮、标签、滚动、图像与状态控件；局部渲染和多缓冲；可独立设计显示及输入适配层
- 许可：LVGL core MIT；可选字体、图片与商用编辑工具另算。。[许可原文](https://github.com/lvgl/lvgl/blob/master/LICENCE.txt)
- 维护证据：发布条目更新 Release v9.5.0 · 2026-02-18。[记录](https://github.com/lvgl/lvgl/releases/tag/v9.5.0)

可用能力：C 库可用于 C3 RGB565 partial rendering 与现有驱动或 esp_lcd / esp_lvgl_port 连接

接入判断：做显示 flush 和 CST816D input 回调，先迁首页与一次确认，保持主操作按钮、明确返回、700ms确认保护。
禁用未用控件/动画/大图片缓存；中文保留既有字形管线或按任务字集生成。
同一时刻图像解码、TLS、Wi-Fi重连下记录最低空闲堆与帧时延后决定是否迁移。

能力边界：

- 170×320 RGB565 一帧108800字节；双全帧217600字节，未含 Wi-Fi/TLS/任务/解码和堆。
- 宜用约1/10屏局部缓冲10880字节，视性能再调；这是计算与建议，不是本板测量。
- LVGL 不自动提供完整中文字体，也不自动解决图片存储、工业业务状态及触摸驱动。
- v8/v9 API不同，禁止混拼例程；LVGL Pro Editor 的许可证不等同于开源 LVGL 核心。

官方证据：[来源1](https://github.com/lvgl/lvgl) · [来源2](https://lvgl.io/docs/open/9.2/porting/display) · [来源3](https://components.espressif.com/components/espressif/esp_lvgl_port/versions/2.9.0/readme) · [来源4](https://github.com/lvgl/lvgl/blob/master/LICENCE.txt) · [来源5](https://github.com/lvgl/lvgl/releases/tag/v9.5.0)

仅研究；未连接或烧写设备，未执行候选固件。

### LovyanGFX

**硬件与工业通信 · 备选**　[LovyanGFX 官方仓库](https://github.com/lovyan03/LovyanGFX)

- 覆盖：SPI绘图、DMA、sprite、缩放旋转；部分兼容 AdafruitGFX/TFT_eSPI API；ST7789 与 CST816S 类触摸
- 许可：原创部分 FreeBSD/BSD-2-Clause 风格；含 Adafruit MIT/BSD 及其他第三方声明，须保留整份 license.txt。。[许可原文](https://github.com/lovyan03/LovyanGFX/blob/master/license.txt)
- 维护证据：发布条目更新 1.2.28 · 2026-08-25。[记录](https://github.com/lovyan03/LovyanGFX/releases/tag/1.2.28)

可用能力：官方矩阵明确 C3 硬件 SPI/I2C 和触摸 Arduino-ESP32 和 ESP-IDF

接入判断：单独 LGFX board class 设置现有引脚、CS固定有效、40MHz、MODE3和170×320窗口偏移。
先保留现有CST816D输入读取，换显示后再评估统一触摸抽象。
用已有施工/效果JPEG和中文长任务比较耗时、RAM、重连时触摸响应。

能力边界：

- 支持ST7789不等于有金逸晨170×320板级预设。
- 官方列 CST816S；本板是 CST816D，需验证芯片ID、寄存器、IRQ、坐标旋转和唤醒，不能宣称即插即用。
- 大sprite仍占SRAM；库支持PSRAM功能不意味着C3具备PSRAM。

官方证据：[来源1](https://github.com/lovyan03/LovyanGFX) · [来源2](https://github.com/lovyan03/LovyanGFX/releases/tag/1.2.28) · [来源3](https://github.com/lovyan03/LovyanGFX/blob/master/license.txt)

仅研究；未连接或烧写设备，未执行候选固件。

### TFT_eSPI

**硬件与工业通信 · 备选**　[TFT_eSPI 官方仓库](https://github.com/Bodmer/TFT_eSPI)

- 覆盖：ST7789及多种TFT；快速绘图、sprite、字体；Arduino/PlatformIO配置
- 许可：原创 FreeBSD/BSD-2-Clause 风格；继承代码含 MIT/BSD，字体另有声明。。[许可原文](https://github.com/Bodmer/TFT_eSPI/blob/master/license.txt)
- 维护证据：维护记录 Update README.md · 2026-04-03。[记录](https://github.com/Bodmer/TFT_eSPI/commit/16e37595040eac69cd628e4bffb56fc30cad6299)

可用能力：发布历史明确增加 ESP32-C3 支持 可与现有 TJpg_Decoder 回调连接

接入判断：将板级配置纳入本项目版本管理，避免修改全局库User_Setup造成别的板被影响。
保留触摸与业务层，只替换绘图backend，比较同图同字库的稳定性。

能力边界：

- 最新可见release V2.5.43 是2024-03-06，但默认分支有2026-04-03提交；不能仅因旧release说已停止维护。
- User_Setup 不是本板现成配置，C3 core版本、SPI host、ST7789偏移需实测。
- 库触摸集成不能等同于本板CST816D支持，需独立输入驱动。

官方证据：[来源1](https://github.com/Bodmer/TFT_eSPI) · [来源2](https://github.com/Bodmer/TFT_eSPI/releases) · [来源3](https://github.com/Bodmer/TFT_eSPI/commit/16e37595040eac69cd628e4bffb56fc30cad6299) · [来源4](https://github.com/Bodmer/TFT_eSPI/blob/master/license.txt)

仅研究；未连接或烧写设备，未执行候选固件。

### esp_lcd + esp_lcd_touch + esp_lvgl_port（ESP-BSP）

**硬件与工业通信 · 按需引入**　[esp_lcd + esp_lcd_touch + esp_lvgl_port（ESP-BSP） 官方仓库](https://github.com/espressif/esp-bsp)

- 覆盖：官方显示面板/总线/触摸抽象；IDF内置ST7789 panel；LVGL8/9 bridge与任务、timer、锁
- 许可：上述 Espressif components Apache-2.0；LVGL依赖MIT。。[许可原文](https://components.espressif.com/components/espressif/esp_lcd_touch_cst816s/versions/1.1.2/license)
- 维护证据：维护记录 Merge pull request #822 from Kainarx/feat/add_lt9611_conponent · 2026-09-04。[记录](https://github.com/espressif/esp-bsp/commit/b1bc71e7980663110055fbeba7eab59d5e689c2b)

可用能力：C3可使用SPI LCD，不套用S3/P4的RGB/MIPI/USB Host能力 esp_lcd_touch_cst816s v1.1.2，I2C esp_lvgl_port v2.9.0

接入判断：IDF升级完成后，esp_lcd_new_panel_st7789连接原GPIO；面板偏移/颜色反转/旋转照现有实测配置迁移。
注册触摸irq到UI任务，不在中断内画图；接入锁与短DMA缓冲。
用当前部件图册和BOOT返回案例重验，绝不照搬S3开发板引脚。

能力边界：

- 当前 cst816s v1.1.2 和 esp_lvgl_port v2.9.0 manifest 均要求 IDF>=5.2。
- 触摸组件名称/README只承诺CST816S；本板CST816D还需板测，不把supports all targets解读为所有触摸芯片兼容。
- CST816S类芯片可能只在触摸后短暂回应I2C，初始化扫描失败不等于硬件不存在。
- GenericBSP支持的别的芯片能力，不代表C3有RGB或USB Host。

官方证据：[来源1](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/lcd/index.html) · [来源2](https://components.espressif.com/components/espressif/esp_lcd_touch_cst816s/versions/1.1.2/readme) · [来源3](https://github.com/espressif/esp-bsp/blob/master/components/lcd_touch/esp_lcd_touch_cst816s/idf_component.yml) · [来源4](https://github.com/espressif/esp-bsp/blob/master/components/esp_lvgl_port/idf_component.yml) · [来源5](https://components.espressif.com/components/espressif/esp_lcd_touch_cst816s/versions/1.1.2/license) · [来源6](https://components.espressif.com/components/espressif/esp_lvgl_port/versions/2.9.0/license) · [来源7](https://github.com/espressif/esp-bsp) · [来源8](https://github.com/espressif/esp-bsp/commit/b1bc71e7980663110055fbeba7eab59d5e689c2b)

仅研究；未连接或烧写设备，未执行候选固件。

### esptool

**硬件与工业通信 · 沿用完善**　[esptool 官方仓库](https://github.com/espressif/esptool)

- 覆盖：官方串口Flash读写/校验；镜像合并、芯片识别；espsecure / espefuse相关工具
- 许可：GPL-2.0-or-later（官方README明确）。。[许可原文](https://github.com/espressif/esptool/blob/master/LICENSE)
- 维护证据：发布条目更新 Version 5.4.0 · 2026-09-02。[记录](https://github.com/espressif/esptool/releases/tag/v5.4.0)

可用能力：官方有ESP32-C3专用文档 Python CLI适合现有Python主机 支持保留分区的指定地址写入

接入判断：在Web硬件维护中先显示识别结果、当前/目标版本、板型与应用SHA256，保留现有全Flash备份策略。
已采用现有分区的板，仅写0x10000应用并重握手；新的分区变更另作数据迁移。
此次没有调用任何串口或刷机命令；建议接入方案不等于已刷写。

能力边界：

- 烧写前串口必须从任务桥释放，连接/复位行为不同于普通JSONL收发。
- C3 bootloader偏移为0x0；不能复制经典ESP32示例的0x1000。
- read_flash/写入/加密功能随芯片安全状态受限；不应盲刷合并全镜像或erase_flash。
- 刷机工具只负责镜像搬运，不验证工人业务与任务数据兼容性。

官方证据：[来源1](https://docs.espressif.com/projects/esptool/en/latest/esp32c3/index.html) · [来源2](https://github.com/espressif/esptool/blob/master/README.md) · [来源3](https://github.com/espressif/esptool/releases/tag/v5.4.0) · [来源4](https://github.com/espressif/esptool/blob/master/LICENSE) · [来源5](https://github.com/espressif/esptool)

仅研究；未连接或烧写设备，未执行候选固件。

### ESP Web Tools + esptool-js

**硬件与工业通信 · 谨慎评估**　[ESP Web Tools + esptool-js 官方仓库](https://github.com/esphome/esp-web-tools)

- 覆盖：浏览器Web Serial刷机；manifest选择芯片镜像；可选Improv串口配网；底层esptool-js可定制
- 许可：ESP Web Tools Apache-2.0；esptool-js Apache-2.0。。[许可原文](https://github.com/esphome/esp-web-tools/blob/main/LICENSE)
- 维护证据：发布条目更新 10.4.0 · 2026-07-15。[记录](https://github.com/esphome/esp-web-tools/releases/tag/10.4.0)

可用能力：ESP Web Tools明确包含ESP32-C3 esptool-js运行在桌面浏览器，不消耗C3运行内存 安全上下文和用户选择串口是浏览器边界

接入判断：本地托管固定版本JS和仅本板镜像，不依赖运行时CDN latest。
为已部署工牌设计app-only写入列表和分区核验；初装与升级分开，维护权限由Web业务层决定。
完成后回到JSONL hello和功能自检，Wi-Fi配网继续现有USB配置协议。

能力边界：

- 本项目使用自定义JSONL配网，没有证据已实现Improv。默认ESP Web Tools无法识别固件时可能走new installation并擦除已有数据。
- 现有Python桥占用串口时浏览器不能同时刷机；需明确释放/重连。
- 不能承诺所有手机浏览器；官方ESP Web Tools文档仍无iOS及完整Android安装支持。使用navigator.serial能力检测并保留Python维护入口。
- esptool-js不包含ELF转镜像、espsecure和espefuse，不能代替完整发布构建。

官方证据：[来源1](https://esphome.github.io/esp-web-tools/) · [来源2](https://github.com/espressif/esptool-js) · [来源3](https://github.com/espressif/esptool-js/releases/tag/v0.6.1) · [来源4](https://github.com/esphome/esp-web-tools/blob/main/LICENSE) · [来源5](https://github.com/espressif/esptool-js/blob/main/LICENSE) · [来源6](https://github.com/esphome/esp-web-tools) · [来源7](https://github.com/esphome/esp-web-tools/releases/tag/10.4.0)

仅研究；未连接或烧写设备，未执行候选固件。

### ESP-MQTT + Mosquitto + MQTT.js（Python侧优先Paho）

**硬件与工业通信 · 优先验证**　[ESP-MQTT + Mosquitto + MQTT.js（Python侧优先Paho） 官方仓库](https://github.com/espressif/esp-mqtt)

- 覆盖：设备主动长连接与双向消息；QoS、LWT、重连、会话；局域网broker与ACL/TLS；Node/浏览器MQTT.js或现有Python的Paho客户端
- 许可：ESP-MQTT Apache-2.0；Mosquitto EPL-2.0 OR BSD-3-Clause（EDL1.0）；MQTT.js MIT；Paho Python EPL-2.0 / EDL1.0 双许可。。[许可原文](https://github.com/espressif/esp-mqtt/blob/master/LICENSE)
- 维护证据：发布条目更新 v1.1.0 · 2026-07-30。[记录](https://github.com/espressif/esp-mqtt/releases/tag/v1.1.0)

可用能力：MQTT3.1.1/5，TCP/TLS/WebSocket；C3做client、工位电脑做broker 事件、任务投递ACK和执行ACK可独立topic MQTT.js浏览器需WS/WSS，不能直连普通TCP 1883

接入判断：保持protocol1 JSON对象、delivery_id / event_id / revision / execution_version；USB/HTTP/MQTT归一到同一执行处理器。
topic建议 kanpace/v1/devices/{device_id}/task、delivery_ack、execution、execution_ack、availability；按设备ACL，命令不retain。
QoS1+稳定event_id；设备Flash持久化成功再发送；Web去重、状态更新、结果存储同一事务后回业务ACK。
现有8条队列满要拒绝新增并说明，重试同ID、指数退避带抖动；持久拒绝原因、重启恢复、旧ACK不覆盖新任务。
Mosquitto设持久化与明确的队列/会话上限；离线任务带过期和版本，重连先对账。
Python侧Paho与现有服务整合；Web客户端先走既有后端，避免把全设备broker凭据暴露浏览器。

能力边界：

- ESP-MQTT v1.1.0 manifest要求IDF>=5.3，当前Arduino2/IDF4基线不可直接升级；应先用兼容的框架内client或单独迁移。
- ESP-MQTT默认outbox不等于掉电持久业务队列；库中的消息会有过期清理。Paho会话也默认只存内存。
- QoS ACK仅表示协议投递阶段，不能代替业务事务execution_ack，不能提供跨USB/HTTP/MQTT全链路自动exactly-once。
- VPN、网段隔离、防火墙/AP隔离仍可能阻断broker；MQTT不能自动解决当前LAN可达性未完成验证的问题。
- 高质量图片不宜塞入一个MQTT大包；按图像manifest+HTTP分块/校验下载，继续受控原子落盘。

官方证据：[来源1](https://docs.espressif.com/projects/esp-mqtt/en/latest/esp32/) · [来源2](https://github.com/espressif/esp-mqtt/blob/master/idf_component.yml) · [来源3](https://mosquitto.org/) · [来源4](https://github.com/mqttjs/MQTT.js) · [来源5](https://github.com/eclipse-paho/paho.mqtt.python#known-limitations) · [来源6](https://github.com/espressif/esp-mqtt/blob/master/LICENSE) · [来源7](https://github.com/eclipse-mosquitto/mosquitto/blob/master/LICENSE.txt) · [来源8](https://github.com/mqttjs/MQTT.js/blob/main/LICENSE.md) · [来源9](https://github.com/eclipse-paho/paho.mqtt.python/blob/master/LICENSE.txt) · [来源10](https://github.com/espressif/esp-mqtt) · [来源11](https://github.com/espressif/esp-mqtt/releases/tag/v1.1.0)

仅研究；未连接或烧写设备，未执行候选固件。

### ESPHome

**硬件与工业通信 · 谨慎评估**　[ESPHome 官方仓库](https://github.com/esphome/esphome)

- 覆盖：YAML设备配置与自动化；C3、ST7789、CST816触摸组件；LVGL、API、MQTT、OTA生态
- 许可：Python及其他部分MIT；C/C++ runtime GPLv3，官方LICENSE按文件类型划分。。[许可原文](https://github.com/esphome/esphome/blob/dev/LICENSE)
- 维护证据：发布条目更新 2026.8.2 · 2026-08-31。[记录](https://github.com/esphome/esphome/releases/tag/2026.8.2)

可用能力：ESP32-C3平台 CST816文档明确列CST816D 用于独立环境传感器和辅助节点

接入判断：为工位温湿度、呼叫按钮等独立节点使用ESPHome，输出标准遥测到本地服务。
借鉴CST816D识别与触摸行为时先处理runtime许可证；要复制代码必须遵守对应GPL义务。
保持工牌已有正式任务状态机作为业务入口。

能力边界：

- 当前任务/回执状态机、8条持久outbox、中文图册仍须自定义组件重做。
- 运行时C++为GPLv3，不能只看Python部分MIT就复制runtime到闭源固件。
- 显示/触摸芯片支持不等于本板引脚/偏移和现有分区兼容；OTA仍受4MB应用资源预算限制。
- 其Home Assistant模式不是生产任务的事务、版本和验收模型。

官方证据：[来源1](https://esphome.io/components/esp32/) · [来源2](https://esphome.io/components/touchscreen/cst816/) · [来源3](https://esphome.io/components/lvgl/) · [来源4](https://github.com/esphome/esphome/blob/dev/LICENSE) · [来源5](https://github.com/esphome/esphome) · [来源6](https://github.com/esphome/esphome/releases/tag/2026.8.2)

仅研究；未连接或烧写设备，未执行候选固件。

### ThingsBoard Community Edition

**硬件与工业通信 · 后期考虑**　[ThingsBoard Community Edition 官方仓库](https://github.com/thingsboard/thingsboard)

- 覆盖：设备/资产管理、遥测、告警；规则链和设备仪表盘；多协议接入与本地部署
- 许可：Community Edition 主仓库 Apache-2.0；PE/Cloud 产品与功能另行授权。。[许可原文](https://github.com/thingsboard/thingsboard/blob/master/LICENSE)
- 维护证据：发布条目更新 ThingsBoard 4.3.1.4 Release · 2026-08-27。[记录](https://github.com/thingsboard/thingsboard/releases/tag/v4.3.1.4)

可用能力：C3可作为MQTT/HTTP设备接入 平台运行于服务器/工位主机，不在C3运行

接入判断：先只输出在线、RSSI、固件版本、队列深度等遥测给ThingsBoard；任务与完工仍在原事务服务。
需要舰队管理时用设备ID建立映射，避免建立第二套权威任务状态。

能力边界：

- 现有项目/部件/工序/负责人/质检状态不是现成ThingsBoard业务模型。
- 需要额外服务、数据库与运维资源；原生设备RPC回执不是生产事务ACK。
- Community Edition的Apache2不包含所有商业/云功能。

官方证据：[来源1](https://github.com/thingsboard/thingsboard) · [来源2](https://github.com/thingsboard/thingsboard/releases/tag/v4.3.1.4) · [来源3](https://github.com/thingsboard/thingsboard/blob/master/LICENSE)

仅研究；未连接或烧写设备，未执行候选固件。

### EMQX（现行统一版）

**硬件与工业通信 · 谨慎评估**　[EMQX（现行统一版） 官方仓库](https://github.com/emqx/emqx)

- 覆盖：MQTT broker、集群、规则与连接器；设备连接/认证与管理
- 许可：BUSL-1.1（Business Source License），带额外使用授权；特定版本四年后转Apache-2.0。。[许可原文](https://github.com/emqx/emqx/blob/master/LICENSE)
- 维护证据：发布条目更新 EMQX Enterprise (LTS) 6.3.0 · 2026-09-03。[记录](https://github.com/emqx/emqx/releases/tag/6.3.0)

可用能力：C3可使用MQTT client连接 broker运行在服务器；不在C3运行

接入判断：业务协议保持标准MQTT与独立topic/ACL，使未来可换broker。
单工厂内部使用与对外售卖部署包分开判断授权范围；不为避授权锁死已EOL旧社区版。

能力边界：

- 从5.9.0起现行统一版改为BSL1.1 source-available，不能称OSI开源版。
- Additional Use Grant允许单节点生产使用，但排除把它托管或嵌入向第三方提供的产品/解决方案；销售KANPACE集成方案不应假定免费。
- 每特定版本发布四年后转Apache2，不意味着现在已是Apache2。
- 5.8 Apache社区版已于2026-02-28 EOL；Enterprise5.8的较长支持期是另一版本路线，不能混淆。

官方证据：[来源1](https://github.com/emqx/emqx/blob/master/LICENSE) · [来源2](https://www.emqx.com/en/content/license-faq) · [来源3](https://www.emqx.com/en/news/a-notice-on-the-emqx-5-8-open-source-version) · [来源4](https://docs.emqx.com/en/emqx/latest/changes/eol-ee.html) · [来源5](https://github.com/emqx/emqx) · [来源6](https://github.com/emqx/emqx/releases/tag/6.3.0)

仅研究；未连接或烧写设备，未执行候选固件。

### ESP-SR（WakeNet9s / MultiNet / AFE）

**硬件与工业通信 · 后期考虑**　[ESP-SR（WakeNet9s / MultiNet / AFE） 官方仓库](https://github.com/espressif/esp-sr)

- 覆盖：唤醒词、音频前端、命令词算法族；WakeNet9s面向低资源芯片
- 许可：ESPRESSIF MIT（许可授予范围限定用于Espressif产品），非标准MIT；部分算法/模型以预编译资源交付，不能表述为完整算法源代码开源。。[许可原文](https://github.com/espressif/esp-sr/blob/master/LICENSE)
- 维护证据：维护记录 Merge branch 'fix/esp32s31_docs-f' into 'master' · 2026-09-04。[记录](https://github.com/espressif/esp-sr/commit/efa8d907c6d457cd0f99dae6c6b493412d3078d4)

可用能力：官方2025-04-21公告：WakeNet9s支持无PSRAM/无SIMD的ESP32-C3/C5 MultiNet命令识别和AFE官方目标表没有C3

接入判断：工牌保留触摸确认和BOOT返回；语音只提出草稿动作，最终完工等由既有确认与事务校验处理。
优先手机/工位按住说话，转写为暂停说明或交接草稿，再由工人确认。
若下一代硬件确需离线命令识别，选择具有已证实模型支持、麦克风和足够RAM的芯片/板，另做噪声环境验证。

能力边界：

- README未确认本工牌有麦克风、I2S引脚及音频电源；需先确认物理音频链路。
- WakeNet9s识别固定唤醒词，不等同于识别暂停原因、数量、工序或自由文本。
- 当前esp-sr component manifest为2.5.3、要求IDF>=5.0；GitHub旧release2.0.0不足以代表新增C3能力。
- 低资源也需与Wi-Fi、图像和触摸共存实测；不能直接套S3 MultiNet/AFE或PSRAM配置。

官方证据：[来源1](https://github.com/espressif/esp-sr) · [来源2](https://github.com/espressif/esp-sr/blob/master/LICENSE) · [来源3](https://github.com/espressif/esp-sr/blob/master/idf_component.yml) · [来源4](https://github.com/espressif/esp-sr/blob/master/CMakeLists.txt) · [来源5](https://github.com/espressif/esp-sr/commit/efa8d907c6d457cd0f99dae6c6b493412d3078d4)

仅研究；未连接或烧写设备，未执行候选固件。

### whisper.cpp

**硬件与工业通信 · 按需引入**　[whisper.cpp 官方仓库](https://github.com/ggml-org/whisper.cpp)

- 覆盖：本地语音转文字；CPU/Metal等后端、量化；Mac/Windows/Linux/手机/WASM
- 许可：whisper.cpp代码MIT；使用的模型权重与第三方后端按具体来源核验。。[许可原文](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE)
- 维护证据：发布条目更新 v1.9.3 · 2026-08-20。[记录](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.3)

可用能力：适合用户本地电脑或工位网关 中文需多语言模型而非.en模型

接入判断：Web录音或工位麦克风生成短音频，发送本机服务转写为pause_note/handover_note草稿。
既有确认页面显示完整文本与关联任务，确认后走现有execution处理器。
将转写服务隔离于任务事务线程，限制音频时长，断网时触摸/文字仍可完成工作。

能力边界：

- 官方tiny参考模型磁盘75MiB、运行约273MB；远超C3的4MB Flash/400KB SRAM，量化也不使该板可运行完整Whisper。
- 噪声/口音/数字会误识别；识别文本不能直接触发生产完工或质量放行。
- 模型文件许可与代码许可证应一起登记；推理速度须在实际主机测量。

官方证据：[来源1](https://github.com/ggml-org/whisper.cpp) · [来源2](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.3) · [来源3](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE)

仅研究；未连接或烧写设备，未执行候选固件。

### ZXing for JS：@zxing/browser + @zxing/library

**硬件与工业通信 · 按需引入**　[ZXing for JS：@zxing/browser + @zxing/library 官方仓库](https://github.com/zxing-js/browser)

- 覆盖：浏览器相机扫码；QR及一维/二维条码；图片导入和相机切换
- 许可：@zxing/browser MIT；@zxing/library Apache-2.0。。[许可原文](https://github.com/zxing-js/browser/blob/master/LICENSE)
- 维护证据：发布条目更新 v0.2.1 · 2026-07-06。[记录](https://github.com/zxing-js/browser/releases/tag/v0.2.1)

可用能力：手机/工位浏览器运行 C3显示短工单码/设备ID，识别在外部完成

接入判断：为设备/部件打印短ID二维码，扫描后服务端解析并显示项目/部件/工序供确认。
扫码绑定只关联已登录用户和已知device_id，不把Bearer token或Wi-Fi凭据放码里。
纸质标签作为主入口，170px屏幕只在需要时显示有留白、低密度的短码。

能力边界：

- @zxing/browser不支持实体扫描枪协议；USB键盘式扫描枪通过普通输入框接收，不必走相机库。
- 手机相机需浏览器权限与安全上下文；LAN普通HTTP能开网页不保证能用getUserMedia。
- 二维码只是标识，不是操作授权；服务端仍核验用户、设备、任务版次。
- 本板没有已确认摄像头，C3 USB Serial/JTAG也不是通用USB Host扫描枪接口。

官方证据：[来源1](https://github.com/zxing-js/browser) · [来源2](https://github.com/zxing-js/library) · [来源3](https://github.com/zxing-js/browser/releases/tag/v0.2.1) · [来源4](https://www.w3.org/TR/mediacapture-streams/) · [来源5](https://github.com/zxing-js/browser/blob/master/LICENSE) · [来源6](https://github.com/zxing-js/library/blob/master/LICENSE)

仅研究；未连接或烧写设备，未执行候选固件。

### open62541（OPC UA）

**硬件与工业通信 · 按需引入**　[open62541（OPC UA） 官方仓库](https://github.com/open62541/open62541)

- 覆盖：OPC UA客户端/服务端、订阅和信息模型；C99可移植，安全插件
- 许可：核心 MPL-2.0；部分示例/插件CC0，部分仍MPL。分发时修改的MPL文件有源码义务，独立业务文件可用自身许可证。。[许可原文](https://github.com/open62541/open62541/blob/master/LICENSE)
- 维护证据：发布条目更新 v1.5.8 · 2026-09-06。[记录](https://github.com/open62541/open62541/releases/tag/v1.5.8)

可用能力：OPC UA / IEC62541 工位Linux/Windows网关与PLC/设备OPC UA server通信

接入判断：按设备文档列出允许读取的NodeId和证书信任关系，通过订阅/周期读取转成machine_state/计数遥测。
记录源时间、采集时间、质量码，断线写unknown并补齐缺口；不推断未采到的产量。
工牌只接收与当前任务相关的提示，机器写控制和安全回路保持在经验证的PLC系统。

能力边界：

- 官方通用embedded支持不等于金逸晨C3固件已适配；未找到本板资源实测证据。
- 地址空间、证书、连接和加密要占RAM，不能与工牌显示/任务存储竞争后仍宣称可靠。
- 采集机台运行/停机/计数，不等同工人任务完工；工艺归属和设备计数规则需业务映射。

官方证据：[来源1](https://github.com/open62541/open62541) · [来源2](https://open62541.org/) · [来源3](https://github.com/open62541/open62541/releases/tag/v1.5.8) · [来源4](https://github.com/open62541/open62541/blob/master/LICENSE)

仅研究；未连接或烧写设备，未执行候选固件。

### PyModbus（Modbus TCP / RTU）

**硬件与工业通信 · 按需引入**　[PyModbus（Modbus TCP / RTU） 官方仓库](https://github.com/pymodbus-dev/pymodbus)

- 覆盖：同步/异步Modbus client/server；TCP/TLS、RTU/ASCII、RS485；测试用设备模拟器
- 许可：BSD-3-Clause。。[许可原文](https://github.com/pymodbus-dev/pymodbus/blob/dev/LICENSE)
- 维护证据：发布条目更新 Pymodbus v3.15.0 · 2026-08-13。[记录](https://github.com/pymodbus-dev/pymodbus/releases/tag/v3.15.0)

可用能力：Python>=3.10，Windows/Linux/macOS 主机通过网口或USB-RS485采集机台寄存器

接入判断：独立Python采集适配器定时读取白名单寄存器，生成source、timestamp、quality和单位明确的设备遥测。
超时/异常/断网不记作0产量；验证机台累计计数回绕和重启清零规则。
机器遥测提供任务进度参考，完成/暂停/验收仍经原业务事务处理。

能力边界：

- 依赖设备厂家寄存器表、地址基准、字节序、倍率、unit/device ID和轮询负载；不能自动猜寄存器含义。
- RS485需要适当收发器/隔离/接线，不是直接把工业总线接C3 GPIO。
- 传统Modbus TCP/RTU没有应用用户授权；需网关和网络隔离，不能因库支持TLS就假定原机台支持TLS。
- 项目明确次版本可能改API，不按完整SemVer保证，需锁版本。

官方证据：[来源1](https://github.com/pymodbus-dev/pymodbus) · [来源2](https://github.com/pymodbus-dev/pymodbus/blob/dev/LICENSE) · [来源3](https://github.com/pymodbus-dev/pymodbus/releases/tag/v3.15.0)

仅研究；未连接或烧写设备，未执行候选固件。

### Apache ECharts

**BI与界面 · 优先验证**　[Apache ECharts 官方仓库](https://github.com/apache/echarts)

- 覆盖：老板BI；产能负荷；交付趋势；成本偏差
- 许可：Apache-2.0。[许可原文](https://github.com/apache/echarts/blob/master/LICENSE)
- 维护证据：发布 6.1.0 · 2026-05-19。[记录](https://github.com/apache/echarts/releases/tag/6.1.0)

可用能力：原生 JavaScript 图表库，提供交互图表、Canvas/SVG 渲染；可以承载交付趋势、瓶颈工种、返工和成本偏差图。

接入判断：接现有统计 API，在当前原生 JS 页面增加联动筛选和图表，无需重写整套前端。指标定义、去重和权限在后端统一。

能力边界：

- 图表库不定义准交率、毛利和工时统计口径；任务完成比例不能替代收入确认或实际利润。

官方证据：[来源1](https://github.com/apache/echarts) · [来源2](https://github.com/apache/echarts/blob/master/LICENSE) · [来源3](https://github.com/apache/echarts/releases/tag/6.1.0)

文档与源码元数据核验；未安装或运行候选项目。

### Apache Superset

**BI与界面 · 按需引入**　[Apache Superset 官方仓库](https://github.com/apache/superset)

- 覆盖：老板BI；自助报表；SQL指标层
- 许可：Apache-2.0。[许可原文](https://github.com/apache/superset/blob/master/LICENSE.txt)
- 维护证据：发布 6.1.0 · 2026-05-13。[记录](https://github.com/apache/superset/releases/tag/6.1.0)

可用能力：自托管分析平台，提供图表、SQL 查询、指标层、角色权限与 API，适合管理者自助分析。

接入判断：多工厂或大量自助报表需求明确后再部署，通过只读分析视图汇总交付、缺料、成本和产能。小规模先用 ECharts。

能力边界：

- 需要独立服务和分析数据源；嵌入 BI 的身份、行级权限与业务系统需要明确对接；不能直接把生产库全部开放。

官方证据：[来源1](https://github.com/apache/superset) · [来源2](https://github.com/apache/superset/blob/master/LICENSE.txt) · [来源3](https://superset.apache.org/) · [来源4](https://github.com/apache/superset/releases/tag/6.1.0)

文档与源码元数据核验；未安装或运行候选项目。

### Metabase

**BI与界面 · 谨慎评估**　[Metabase 官方仓库](https://github.com/metabase/metabase)

- 覆盖：自助报表；嵌入分析
- 许可：AGPL（社区部分）＋商业许可证（enterprise目录）。[许可原文](https://github.com/metabase/metabase)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/metabase/metabase)

可用能力：提供可自托管的可视化问数和仪表盘；可作为客户已有 BI 的互联对象。

接入判断：优先作为客户独立使用的 BI 对接；KANPACE 自带图表优先 ECharts，嵌入方式和相应许可另做选定版本核验。

能力边界：

- 仓库混合许可；完整应用嵌入官方要求 Pro/Enterprise，不能将免费自托管等同于可免费白标集成全部嵌入功能。

官方证据：[来源1](https://github.com/metabase/metabase) · [来源2](https://www.metabase.com/license) · [来源3](https://www.metabase.com/docs/latest/embedding/full-app-embedding) · [来源4](https://api.github.com/repos/metabase/metabase)

文档与源码元数据核验；未安装或运行候选项目。

### Node-RED

**文件与系统互联 · 优先验证**　[Node-RED 官方仓库](https://github.com/node-red/node-red)

- 覆盖：ERP互联；事件路由；HTTP/MQTT适配；工位网关
- 许可：Apache-2.0（核心）。[许可原文](https://github.com/node-red/node-red/blob/main/LICENSE)
- 维护证据：发布 5.0.6 · 2026-09-01。[记录](https://github.com/node-red/node-red/releases/tag/5.0.6)

可用能力：可自托管的事件流编排，具备 HTTP、消息、流程节点和扩展节点生态，适合客户接口转换与现场网关。

接入判断：外挂连接客户 ERP、文件入口或 MQTT，所有任务变更仍调用 KANPACE 同一业务 API；保留来源单号、重试记录和失败队列。

能力边界：

- 第三方节点许可和质量独立核验；画出一条 flow 并不自动实现业务幂等、事务和跨系统一致性。

官方证据：[来源1](https://github.com/node-red/node-red) · [来源2](https://github.com/node-red/node-red/blob/main/LICENSE) · [来源3](https://nodered.org/docs/) · [来源4](https://flows.nodered.org/) · [来源5](https://github.com/node-red/node-red/releases/tag/5.0.6)

文档与源码元数据核验；未安装或运行候选项目。

### n8n

**文件与系统互联 · 谨慎评估**　[n8n 官方仓库](https://github.com/n8n-io/n8n)

- 覆盖：低代码互联；AI工作流
- 许可：Sustainable Use License＋Enterprise（非OSI开源）。[许可原文](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/n8n-io/n8n)

可用能力：连接器和工作流丰富，可用于企业内部自动化以及客户已经购买并部署的环境。

接入判断：可以作为客户已有系统的对接对象；不作为 KANPACE 默认随产品分发的商业连接器底座。优先核验 Node-RED。

能力边界：

- 官方明确不称 OSI 开源；白标销售、向客户收费托管，以及某些使用客户凭据的产品后端场景受商业许可限制。

官方证据：[来源1](https://github.com/n8n-io/n8n) · [来源2](https://github.com/n8n-io/n8n/blob/master/LICENSE.md) · [来源3](https://docs.n8n.io/sustainable-use-license/) · [来源4](https://api.github.com/repos/n8n-io/n8n)

文档与源码元数据核验；未安装或运行候选项目。

### Univer

**文件与系统互联 · 按需引入**　[Univer 官方仓库](https://github.com/dream-num/univer)

- 覆盖：网页表格；类Excel交互；协同表格
- 许可：Apache-2.0核心＋Pro商业功能。[许可原文](https://github.com/dream-num/univer/blob/dev/LICENSE)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/dream-num/univer)

可用能力：提供可嵌入的电子表格组件，适合排程表或清单需要保留单元格操作习惯时做界面原型。

接入判断：先验证是否真的需要完整电子表格编辑器；当前字段映射、导入预览和校验可保留，避免仅为导入 Excel 增加整套表格服务。

能力边界：

- 官方 XLSX 导入导出方案使用 Pro exchange 客户端及服务端；协作、历史、部分高级能力不能统称免费核心。

官方证据：[来源1](https://github.com/dream-num/univer) · [来源2](https://github.com/dream-num/univer/blob/dev/LICENSE) · [来源3](https://docs.univer.ai/guides/sheets/features/import-export) · [来源4](https://docs.univer.ai/guides/sheets/getting-started/pro) · [来源5](https://api.github.com/repos/dream-num/univer)

文档与源码元数据核验；未安装或运行候选项目。

### SheetJS Community Edition

**文件与系统互联 · 谨慎评估**　[SheetJS Community Edition 官方仓库](https://github.com/SheetJS/sheetjs)

- 覆盖：Excel解析；浏览器文件预检
- 许可：Apache-2.0（CE）。[许可原文](https://github.com/SheetJS/sheetjs/blob/github/LICENSE)
- 维护证据：旧 GitHub 镜像 push · 2024-04-18；主源码已迁移。[记录](https://api.github.com/repos/SheetJS/sheetjs)

可用能力：在浏览器或 Node 读写多种工作簿格式，可做文件上传前的快速工作表预览。

接入判断：若使用则从官方当前分发渠道锁版本和完整性；最终校验和提交仍交后端。后端已有 Python，优先评测 openpyxl。

能力边界：

- GitHub 是旧镜像，主源码已经迁移；官方文档说明 npm 的 xlsx 包源滞后。CE 不是完整 Excel 公式引擎，也不能保证复杂模板原样往返。

官方证据：[来源1](https://github.com/SheetJS/sheetjs) · [来源2](https://github.com/SheetJS/sheetjs/blob/github/LICENSE) · [来源3](https://git.sheetjs.com/sheetjs/sheetjs) · [来源4](https://docs.sheetjs.com/docs/getting-started/installation/nodejs/) · [来源5](https://api.github.com/repos/SheetJS/sheetjs)

文档与源码元数据核验；未安装或运行候选项目。

### ExcelJS

**文件与系统互联 · 备选**　[ExcelJS 官方仓库](https://github.com/exceljs/exceljs)

- 覆盖：Excel导出；样式与工作簿
- 许可：MIT。[许可原文](https://github.com/exceljs/exceljs/blob/master/LICENSE)
- 维护证据：仓库 push · 2025-01-21。[记录](https://api.github.com/repos/exceljs/exceljs)

可用能力：JavaScript 工作簿读写与格式库；流式读写适用于 Node.js 环境，可生成工种、物料和日期导出模板。

接入判断：仅在 JavaScript 侧必须生成复杂导出时使用；Python 主业务侧避免为相同能力新增 Node 服务。

能力边界：

- 本次仓库 push 时间为 2025-01-21，活跃度低于部分替代方案；它不运行 Excel 的完整计算与宏环境。

官方证据：[来源1](https://github.com/exceljs/exceljs) · [来源2](https://github.com/exceljs/exceljs/blob/master/LICENSE) · [来源3](https://api.github.com/repos/exceljs/exceljs)

文档与源码元数据核验；未安装或运行候选项目。

### Frappe Gantt

**BI与界面 · 优先验证**　[Frappe Gantt 官方仓库](https://github.com/frappe/gantt)

- 覆盖：生产排程表；甘特图；前后工序连线
- 许可：MIT。[许可原文](https://github.com/frappe/gantt/blob/master/license.txt)
- 维护证据：发布 v1.0.3 · 2025-02-03。[记录](https://github.com/frappe/gantt/releases/tag/v1.0.3)

可用能力：独立 JavaScript 甘特图组件，可展示工序日期、依赖和交互编辑。

接入判断：用作现有排产结果的可视化编辑器；求解交给 OR-Tools 或现有排程模块，修改后先预览影响再发布。

能力边界：

- 甘特图不是有限产能求解器；拖动条形必须经过后端的工种、班次、缺料、冻结任务和前置依赖校验。

官方证据：[来源1](https://github.com/frappe/gantt) · [来源2](https://github.com/frappe/gantt/blob/master/license.txt) · [来源3](https://github.com/frappe/gantt/releases/tag/v1.0.3)

文档与源码元数据核验；未安装或运行候选项目。

### TanStack Table

**BI与界面 · 按需引入**　[TanStack Table 官方仓库](https://github.com/TanStack/table)

- 覆盖：BOM清单；大表格筛选；列配置
- 许可：MIT。[许可原文](https://github.com/TanStack/table/blob/main/LICENSE)
- 维护证据：仓库 push · 2026-08-31。[记录](https://api.github.com/repos/TanStack/table)

可用能力：Headless 表格引擎提供排序、筛选、分组等状态逻辑，核心不强制使用 React。

接入判断：当 BOM/订单/物料列表复杂度增加时逐页引入核心表格状态管理；保留现有原生 JS 架构。

能力边界：

- 不是现成 Excel 编辑器；样式、可访问性和大列表虚拟化仍需配套实现与实际数据验证。

官方证据：[来源1](https://github.com/TanStack/table) · [来源2](https://github.com/TanStack/table/blob/main/LICENSE) · [来源3](https://api.github.com/repos/TanStack/table)

文档与源码元数据核验；未安装或运行候选项目。

### Keycloak

**基础平台 · 按需引入**　[Keycloak 官方仓库](https://github.com/keycloak/keycloak)

- 覆盖：SSO；账号登录；企业身份互联
- 许可：Apache-2.0。[许可原文](https://github.com/keycloak/keycloak/blob/main/LICENSE.txt)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/keycloak/keycloak)

可用能力：成熟的自托管身份服务，提供企业登录与身份联邦能力。

接入判断：客户需要统一账号或多工厂上线时作为 OIDC 身份源；小规模本地单厂不必先部署一套身份平台。

能力边界：

- 登录成功不等于有权查看某工厂、项目或成本；对象权限、设备身份、租户隔离要在 KANPACE 后端执行。

官方证据：[来源1](https://github.com/keycloak/keycloak) · [来源2](https://github.com/keycloak/keycloak/blob/main/LICENSE.txt) · [来源3](https://api.github.com/repos/keycloak/keycloak)

文档与源码元数据核验；未安装或运行候选项目。

### PyCasbin

**基础平台 · 备选**　[PyCasbin 官方仓库](https://github.com/apache/casbin-pycasbin)

- 覆盖：角色权限；对象权限；策略校验
- 许可：Apache-2.0。[许可原文](https://github.com/apache/casbin-pycasbin/blob/master/LICENSE)
- 维护证据：默认分支提交 · 2026-08-13。[记录](https://github.com/apache/casbin-pycasbin/commits/master.atom)

可用能力：Python 权限策略库，可实现角色或属性策略，与现有 Python 服务语言一致。

接入判断：权限模型变复杂后考虑替代散落判断；先明确老板、厂长、技术员、班组长、工人、客户各自数据范围。

能力边界：

- 权限策略、缓存失效、默认拒绝和每个 API 的调用覆盖仍需逐项验证；账号服务和对象授权是不同层。

官方证据：[来源1](https://github.com/apache/casbin-pycasbin) · [来源2](https://github.com/apache/casbin-pycasbin/blob/master/LICENSE) · [来源3](https://github.com/apache/casbin-pycasbin/releases.atom) · [来源4](https://github.com/apache/casbin-pycasbin/commits/master.atom)

文档与源码元数据核验；未安装或运行候选项目。

### LangGraph

**AI与知识 · 按需引入**　[LangGraph 官方仓库](https://github.com/langchain-ai/langgraph)

- 覆盖：拆单Agent编排；人工复核；断点恢复
- 许可：MIT（开源库）。[许可原文](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)
- 维护证据：仓库 push · 2026-09-06。[记录](https://api.github.com/repos/langchain-ai/langgraph)

可用能力：状态图、持久执行和人工中断机制，适合文件提取→字段匹配→证据检查→技术员复核的多步流程。

接入判断：只处理拆单候选和待复核建议；正式料号、尺寸、工艺版本、工单发布继续经 KANPACE 校验和授权。

能力边界：

- 不会让模型自动具有制造常识；LangSmith 托管等配套产品独立计费与授权。持久执行框架不替代生产事务状态机。
- 重启恢复需要持久 checkpointer 和稳定 thread_id；内存保存器不够，节点重放中的外部写入仍需幂等。

官方证据：[来源1](https://github.com/langchain-ai/langgraph) · [来源2](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) · [来源3](https://docs.langchain.com/oss/python/langgraph/durable-execution) · [来源4](https://docs.langchain.com/oss/python/langgraph/interrupts) · [来源5](https://docs.langchain.com/oss/python/langgraph/persistence) · [来源6](https://api.github.com/repos/langchain-ai/langgraph)

文档与源码元数据核验；未安装或运行候选项目。

### Ollama

**AI与知识 · 按需引入**　[Ollama 官方仓库](https://github.com/ollama/ollama)

- 覆盖：本地AI；私有图纸辅助理解
- 许可：MIT运行时；模型权重另审。[许可原文](https://github.com/ollama/ollama/blob/main/LICENSE)
- 维护证据：仓库 push · 2026-09-05。[记录](https://api.github.com/repos/ollama/ollama)

可用能力：可在 Mac、Windows 或 Linux 主机运行本地模型并提供接口，适合有本地推理需求的客户。

接入判断：放在电脑或局域网推理服务，将输出保存为含来源、证据完整度与待复核标记的建议；不能从效果图生成未经验证的制造尺寸。

能力边界：

- 运行时许可不覆盖模型；效果、内存和吞吐由选定权重及硬件决定。ESP32-C3 不承担此类模型推理。

官方证据：[来源1](https://github.com/ollama/ollama) · [来源2](https://github.com/ollama/ollama/blob/main/LICENSE) · [来源3](https://api.github.com/repos/ollama/ollama)

文档与源码元数据核验；未安装或运行候选项目。

### Qdrant

**AI与知识 · 按需引入**　[Qdrant 官方仓库](https://github.com/qdrant/qdrant)

- 覆盖：相似图纸检索；历史工艺检索；知识库
- 许可：Apache-2.0。[许可原文](https://github.com/qdrant/qdrant/blob/master/LICENSE)
- 维护证据：仓库 push · 2026-09-06。[记录](https://api.github.com/repos/qdrant/qdrant)

可用能力：自托管向量检索服务，支持带结构字段的检索和 API，可寻找相似柜体、历史返工原因和工艺记录。

接入判断：按项目/文件/页区建立可追溯索引，检索结果回链到已确认资料。业务主数据继续保存在关系数据库。 另选图纸提取与 embedding 流程并用历史项目验证召回，向量库本身不理解加工尺寸。

能力边界：

- 相似度不是同一零件、重复文件或数量证据；租户过滤和原始数据删除的索引同步需设计。

官方证据：[来源1](https://github.com/qdrant/qdrant) · [来源2](https://github.com/qdrant/qdrant/blob/master/LICENSE) · [来源3](https://api.github.com/repos/qdrant/qdrant)

文档与源码元数据核验；未安装或运行候选项目。

### MCP Python SDK

**文件与系统互联 · 优先验证**　[MCP Python SDK 官方仓库](https://github.com/modelcontextprotocol/python-sdk)

- 覆盖：MCP互联；Agent调用业务工具；协议入口
- 许可：MIT。[许可原文](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE)
- 维护证据：发布 v2.1.1 · 2026-08-25。[记录](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.1)

可用能力：官方 Python SDK 提供 MCP 服务和客户端能力；本次 README 与发布页核验 v2 为当前稳定线，v2.1.1 发布于 2026-08-25。

接入判断：对外暴露查询订单、预览导入、生成排程建议等受控工具；MCP、CLI、Web 共用同一后端业务逻辑和审计。

能力边界：

- MCP 不自动连接所有 ERP，也不替代登录和审批。不要将旧 v1/FastMCP 示例未经核验直接套用 v2 API。

官方证据：[来源1](https://github.com/modelcontextprotocol/python-sdk) · [来源2](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) · [来源3](https://py.sdk.modelcontextprotocol.io/) · [来源4](https://py.sdk.modelcontextprotocol.io/migration/) · [来源5](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.1)

文档与源码元数据核验；未安装或运行候选项目。

### Playwright

**基础平台 · 优先验证**　[Playwright 官方仓库](https://github.com/microsoft/playwright)

- 覆盖：Web回归测试；多浏览器；关键工作流验收
- 许可：Apache-2.0。[许可原文](https://github.com/microsoft/playwright/blob/main/LICENSE)
- 维护证据：发布 v1.63.0 · 2026-09-04。[记录](https://github.com/microsoft/playwright/releases/tag/v1.63.0)

可用能力：官方测试工具支持 Chromium、Firefox、WebKit，具有隔离上下文、等待和跟踪能力。

接入判断：扩展现有测试覆盖导入预览、确认拆单、暂停切单、完工发货禁派工、权限和报表追溯，用独立测试数据验证。

能力边界：

- 浏览器端通过不代表实体工牌、串口断连、排程算法或财务数据正确；需相应接口测试和硬件实测。

官方证据：[来源1](https://github.com/microsoft/playwright) · [来源2](https://github.com/microsoft/playwright/blob/main/LICENSE) · [来源3](https://playwright.dev/docs/intro) · [来源4](https://github.com/microsoft/playwright/releases/tag/v1.63.0)

文档与源码元数据核验；未安装或运行候选项目。

### Dexie.js

**基础平台 · 按需引入**　[Dexie.js 官方仓库](https://github.com/dexie/Dexie.js)

- 覆盖：离线任务；本地缓存；待上传事件队列
- 许可：Apache-2.0；Dexie Cloud另有服务条款。[许可原文](https://github.com/dexie/Dexie.js/blob/master/LICENSE)
- 维护证据：仓库 push · 2026-09-06。[记录](https://api.github.com/repos/dexie/Dexie.js)

可用能力：浏览器 IndexedDB 封装，适合缓存当前工人授权任务、缩略图和待上传事件。

接入判断：建立带 event_id、任务版本和发生时间的本地 outbox，重连后由服务器去重、验证权限与冲突，显示明确待同步状态。 本机网页先验证；手机工位版另完成局域网入口与认证，结合 Workbox 时按其可信 HTTPS 要求部署。

能力边界：

- 免费本地库不自动具备 Dexie Cloud 同步；浏览器离线数据可能被清除，跨设备冲突需要服务端版本规则。

官方证据：[来源1](https://github.com/dexie/Dexie.js) · [来源2](https://github.com/dexie/Dexie.js/blob/master/LICENSE) · [来源3](https://api.github.com/repos/dexie/Dexie.js)

文档与源码元数据核验；未安装或运行候选项目。

### Workbox

**基础平台 · 按需引入**　[Workbox 官方仓库](https://github.com/GoogleChrome/workbox)

- 覆盖：PWA；离线页面；静态资源缓存
- 许可：MIT。[许可原文](https://github.com/GoogleChrome/workbox/blob/v7/LICENSE)
- 维护证据：仓库 push · 2026-09-02。[记录](https://api.github.com/repos/GoogleChrome/workbox)

可用能力：Service Worker 工具库，提供路由和缓存策略，可让车间网页在网络暂断时仍打开关键界面。

接入判断：与 Dexie 配合缓存应用壳和必要素材，登录退出清理授权缓存；任务提交仍经版本校验与幂等业务接口。 第一版 Workbox 只管页面壳/静态资源，Dexie 统一管业务 outbox，避免两个独立队列重复报工。

能力边界：

- 缓存与后台重试不保证业务恰好一次；不能把上次获取的任务状态当实时状态，也不能缓存他人授权资料。
- Service Worker 需要可信来源；手机访问当前仅监听 127.0.0.1 的服务，还需要局域网部署、可信 HTTPS 和认证。无原生 Background Sync 时主要在 Service Worker 启动时重放；默认只重试抛异常请求，4xx/5xx 不会自动重试。

官方证据：[来源1](https://github.com/GoogleChrome/workbox) · [来源2](https://github.com/GoogleChrome/workbox/blob/v7/LICENSE) · [来源3](https://developer.chrome.com/docs/workbox/) · [来源4](https://www.w3.org/TR/service-workers/#register) · [来源5](https://developer.chrome.com/docs/workbox/modules/workbox-background-sync) · [来源6](https://api.github.com/repos/GoogleChrome/workbox)

文档与源码元数据核验；未安装或运行候选项目。

### PostgreSQL

**基础平台 · 按需引入**　[PostgreSQL 官方仓库](https://github.com/postgres/postgres)

- 覆盖：多人协作；业务事务；多工厂数据
- 许可：PostgreSQL License。[许可原文](https://github.com/postgres/postgres/blob/master/COPYRIGHT)
- 维护证据：仓库 push · 2026-09-06。[记录](https://api.github.com/repos/postgres/postgres)

可用能力：成熟关系数据库，提供事务、约束和行级安全策略等能力，适合业务并发和隔离需求增长后的主数据层。

接入判断：出现持续并发写入争用、多应用实例、跨主机访问或集中运维需求时评估 SQLite 迁移；少量多人共用单服务不构成必须迁移的依据。生产任务、物料、成本和审计明确事务边界，并保留迁移回滚。

能力边界：

- RLS 必须启用与配置；超级用户/BYPASSRLS 以及通常的表所有者可以绕过策略。换数据库不会自动实现多租户隔离。

官方证据：[来源1](https://github.com/postgres/postgres) · [来源2](https://github.com/postgres/postgres/blob/master/COPYRIGHT) · [来源3](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) · [来源4](https://www.sqlite.org/whentouse.html) · [来源5](https://api.github.com/repos/postgres/postgres)

文档与源码元数据核验；未安装或运行候选项目。

### SeaweedFS

**基础平台 · 后期考虑**　[SeaweedFS 官方仓库](https://github.com/seaweedfs/seaweedfs)

- 覆盖：图纸对象存储；多工厂附件；S3接口
- 许可：Apache-2.0。[许可原文](https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/seaweedfs/seaweedfs)

可用能力：自托管文件/对象存储，具备 S3 等接口，适合大量图纸、模型和设备图片分离存放。

接入判断：当前本地文件量可控时保留现有存储与备份；扩展后抽象 artifact 存储接口，文件哈希和业务引用留在数据库。

能力边界：

- 需要运维、备份与访问控制；业务文件版本和引用关系不会由对象存储自动解决。

官方证据：[来源1](https://github.com/seaweedfs/seaweedfs) · [来源2](https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE) · [来源3](https://api.github.com/repos/seaweedfs/seaweedfs)

文档与源码元数据核验；未安装或运行候选项目。

### OpenTelemetry Python

**基础平台 · 按需引入**　[OpenTelemetry Python 官方仓库](https://github.com/open-telemetry/opentelemetry-python)

- 覆盖：故障诊断；链路追踪；服务指标
- 许可：Apache-2.0。[许可原文](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE)
- 维护证据：仓库 push · 2026-09-07。[记录](https://api.github.com/repos/open-telemetry/opentelemetry-python)

可用能力：标准化 Python 遥测接口与 SDK，可关联上传解析、排程、派工和回执请求。

接入判断：用 request_id/task_id/event_id 关联服务故障，生产变更审计继续写入业务数据库。 业务 ID 放 trace/log 属性，避免直接成为高基数指标标签。

能力边界：

- 遥测 SDK 还需要收集/存储后端；技术追踪不是不可缺失的生产审计账本，也不能记录密码或完整私有图纸。

官方证据：[来源1](https://github.com/open-telemetry/opentelemetry-python) · [来源2](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE) · [来源3](https://api.github.com/repos/open-telemetry/opentelemetry-python)

文档与源码元数据核验；未安装或运行候选项目。

### openpyxl

**文件与系统互联 · 优先验证**　[openpyxl 官方仓库](https://foss.heptapod.net/openpyxl/openpyxl)

- 覆盖：Excel文件互联；排程表读取；字段映射
- 许可：MIT。[许可原文](https://pypi.org/project/openpyxl/)
- 维护证据：发布 3.1.5 · 2024-06-28。[记录](https://pypi.org/project/openpyxl/3.1.5/)

可用能力：Python XLSX 工作簿读写库，适合现有后端读取多工作表、单元格、日期和公式文本。

接入判断：保留上传原件，预览工作表与字段映射后提交；分别保存公式与缓存值的来源，不用库打开后覆盖客户原文件。

能力边界：

- 不计算公式；data_only 读取的是上次 Excel 保存的缓存结果，可能缺失或陈旧。复杂形状和模板元素并非完整原样往返。
- 旧 .xls 和 .xlsb 不属于其支持范围；保留 VBA 不等于执行宏。

官方证据：[来源1](https://pypi.org/project/openpyxl/) · [来源2](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html) · [来源3](https://foss.heptapod.net/openpyxl/openpyxl) · [来源4](https://openpyxl.readthedocs.io/en/stable/tutorial.html) · [来源5](https://pypi.org/project/openpyxl/3.1.5/)

文档核验；尚未对用户工作簿进行此候选库的兼容测试。

### NVIDIA Omniverse CAD to USD skill / usd-convert-cad

**图纸与3D · 按需引入**　[NVIDIA Omniverse CAD to USD skill / usd-convert-cad 官方仓库](https://github.com/NVIDIA-Omniverse/usd-convert-cad)

- 覆盖：原生 CAD 与 STEP 转 USD；真实三维模型旋转的上游资产生成；装配可视化层级；零件名称和源元数据；多文件装配引用
- 许可：skill 文档 CC-BY-4.0、skill 源码 Apache-2.0；转换 runtime 为 NVIDIA Software License Agreement + NVIDIA AI Product Specific Terms；包含专有 HOOPS Exchange。。[许可原文](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LICENSE.md)
- 维护证据：默认分支提交 · 2026-07-30。[记录](https://github.com/NVIDIA-Omniverse/usd-convert-cad/commit/208fe2c1cd71ae2bb7bd825daf712617000ae028)

可用能力：官方 v0.2.0 skill 调用 usd-convert-cad 自包含 Python 3.12 wheel；无需 Omniverse Kit，包含 pxr 与 CAD 转换运行时。 输入支持 STEP/IGES、SolidWorks SLDPRT/SLDASM、Parasolid、CATIA、JT、NX/Creo、Inventor、IFC、AutoCAD 3D、Revit 等；支持格式不代表任意版本与缺失引用的文件均成功。 输出 USD/USDA/USDC；装配 occurrence 可映射为 Xform，重复零件可采用 references / instanceable references，外部装配可采用 references / payloads。 原始零件名保留为显示名；USD 路径名称被编码为合法唯一标识。带源局部变换、单位与选配可见性信息。 CAD B-rep 在导入时被三角化为 UsdGeomMesh；可调细分精度，支持材料和每面材料 subset。 开启 convertMetadata 后可输出源属性到自定义 USD 属性；可选物理属性是数据属性，不是自动建立仿真物理行为。

接入判断：['KANPACE Python 后端通过隔离转换作业适配器调用独立 Python 3.12 环境 CLI；Mac Web 后端可向企业自有、满足许可的 Windows/Linux 转换节点派发本地文件任务。', '按文件包保留真实 CAD 源及外部零件引用，生成 source hash、版本、参数、日志、退出码、USD 输出清单、单位/边界框与告警；工具本身不生成独立 JSON 状态报告。', '将 USD 装配 occurrence / 源零件名映射到 KANPACE 的已核验 BOM ID；由工程师核对数量、重复实例、抑制件、材料牌号和关键尺寸后才进入分工。', '常规网页查看继续 Three.js：另评估 USD 到 GLB/网格 JSON 的资产适配，显式保留 BOM ID、变换、材质、单位与拾取映射；此 adapter 不是该 skill 的现成功能。', '若后续确需大场景 RTX 材质审阅，可另用 Windows/Linux RTX Kit 服务和 Omniverse WebRTC 嵌入网页；这属于额外运行时、会话与渲染基础设施。', 'ESP32 工牌只接收任务、状态与已核验零件标识，不承载 CAD 解析或 USD 渲染。']

能力边界：

- USD 输出不保留原生 CAD B-rep 拓扑，不能一般性无损回写 CAD；完整 SolidWorks 特征树、草图、配置逻辑与 mates/constraints 不在已实现输出能力内。
- 官方明确不生成可视 PMI 几何、专门 PMI schema 或可编辑语义 PMI；可能读取部分 PMI 供元数据/视图使用不等于完整保留尺寸公差。
- 抑制的装配分支总被跳过；隐藏分支受加载及过滤参数影响；缺失外部零件与源读取器未暴露的数据无法补回。可视化节点数不能直接当完整工程 BOM 数量。
- 材料为 Preview Surface / OmniPBR 等可视化映射；当前不输出 primvars:st UV，不能保证源贴图外观完全保真，也不能把视觉颜色推断为制造材料牌号。
- 只有 USD/USDA/USDC 输出，不输出 GLB 或 USDZ；GLTF/GLB 出现在输入列表。当前 Three.js 工作流需单独的 USD 到网页资产适配或支持 USD 的查看器。
- 该技能没有图片/效果图到准确工程模型的能力；尺寸、板厚、孔位、配合、公差必须来自真实 CAD、施工图与人工确认。
- 不提供排料、制造工艺、CNC 后处理或 G-code。几何展示需与已核验 BOM、加工数据分开。
- linux-aarch64 不支持 DWG/DXF 或 RVT/RFA；Mac 不在官方支持平台内。
- 本轮只读验证官方文档、许可证、元数据和索引；未安装、未运行转换，未验证客户 SolidWorks 版本、装配引用、中文名称、实际 BOM 一致性、离线部署或网页输出。

组件许可补充：component：omniverse-cad-to-usd skill；license：Apache-2.0 AND CC-BY-4.0（代码 Apache；文档 CC-BY）；license_url：https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/LICENSE.md；note：技能说明可公开阅读/复用，不将 converter 改成全开源。 component：usd-convert-cad native runtime；license：NVIDIA proprietary agreements；license_url：https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LICENSE.md；note：根许可直接引用 NVIDIA Software License Agreement 与 AI 产品附加条款；商用、服务与再分发依具体产品权益、条款及适用费用，不能以 GitHub 可见或无需 EULA 提示认定任意商用。 component：HOOPS Exchange SDK 2026.5.0；license：Commercial / Proprietary；license_url：https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/THIRD_PARTY_NOTICES.md；note：由 NVIDIA 向 Tech Soft 3D 授权取得并用于 CAD 读取；不能称开源，也不能在未核实下断言每位用户必须另购直接 HOOPS license。 component：NVIDIA OpenUSD Exchange SDK 2.3；license：Apache-2.0；license_url：https://github.com/NVIDIA-Omniverse/usd-exchange/blob/main/LICENSE.md；note：开放的 USD authoring 层，不能单独替代专有 CAD reader。 component：OpenUSD pxr 25.11；license：Tomorrow Open Source Technology License 1.0；license_url：https://github.com/PixarAnimationStudios/OpenUSD/blob/v25.11/LICENSE.txt；note：Apache 2.0 衍生条款，商标条款有区别；不要简单写作原版 Apache-2.0。OpenUSD 开放不代表 Omniverse 全栈开放。 component：其他运行时依赖；license：按组件分别许可；license_url：https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/THIRD_PARTY_NOTICES.md；note：直接依赖有 fmt MIT（含嵌入二进制例外）与 pybind11 BSD-3；HOOPS 含 ODA 等传递依赖，分发保留随包许可证及 notices。 component：AI 模型权重；license：None；license_url：https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/SKILL.md；note：CAD 转换自身未列必需 AI 模型权重。Agent skill 是工作流程指令，不是生成模型。

官方证据：[来源1](https://github.com/NVIDIA-Omniverse/usd-convert-cad) · [来源2](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/SKILL.md) · [来源3](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/docs/concept_mapping.md) · [来源4](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LIMITATIONS.md) · [来源5](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LICENSE.md) · [来源6](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/LICENSE.md) · [来源7](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/THIRD_PARTY_NOTICES.md) · [来源8](https://pypi.nvidia.com/usd-convert-cad/) · [来源9](https://pypi.org/pypi/usd-convert-cad/json) · [来源10](https://docs.omniverse.nvidia.com/extensions/latest/ext_cad-converter/manual.html) · [来源11](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) · [来源12](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/) · [来源13](https://docs.omniverse.nvidia.com/dev-guide/latest/common/technical-requirements.html) · [来源14](https://docs.omniverse.nvidia.com/ov-web-sdk/latest/web-streaming-library/overview.html) · [来源15](https://github.com/NVIDIA-Omniverse/usd-convert-cad/commits/main.atom) · [来源16](https://github.com/NVIDIA-Omniverse/usd-convert-cad/commit/208fe2c1cd71ae2bb7bd825daf712617000ae028)

官方源码文档/技能内容/许可证/包索引只读核验；没有安装技能或 runtime，没有执行转换。

