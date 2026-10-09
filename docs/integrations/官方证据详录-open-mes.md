# 展示柜工厂系统互联：官方接口证据与接入建议

核验日期：2026-09-04。范围：Odoo、ERPNext、Siemens Opcenter、SOLIDWORKS PDM Professional、Rockwell Plex、飞书多维表格、钉钉宜搭。只引用厂商、厂商官方代码仓库和标准组织资料。本文是选型与连接方式研究，**没有接入任何客户租户，也不代表KANPACE已经实现这些连接器**。

证据等级：**A**＝公开接口文档、官方 SDK/源码或规范中可核对具体对象；**B**＝官方产品资料明确声明能力，但不足以确定客户环境的端点与权限；**待核实**＝套餐、版本、租户授权或能力未被本次资料证实。“未核实官方 MCP”不等于断言不存在；第三方同名 MCP 不计为厂商官方能力。

对中小展示柜工厂的建议是：让现有软件继续承担它已经做好的工作，KANPACE负责图纸版本到工种任务的映射、跨工种依赖、异常和现场回执。先接客户已有的 ERP、PDM 或协作表格；没有 ERP 时，再评估可自托管的 ERPNext。以下“适合怎样接”属于基于证据的工程判断，不能代替实际租户联调。

| 系统 | 已核实的官方连接面 | 与展示柜有关的对象 | 关键边界 | 初步适配判断 |
|---|---|---|---|---|
| Odoo | JSON-2 API；Studio 自动化 Webhook；服务器 CLI。A | BOM、制造单、工序工单、销售订单；字段随模块和数据库而变 | 商业套餐的外部 API 为 Custom；Community 与 Enterprise 许可不同 | 客户已有 Odoo 时保留销售、采购、库存账；KANPACE处理拆单和工种执行 |
| ERPNext / Frappe | DocType REST、文档事件 Webhook、Python hooks、Bench CLI。A | BOM、Work Order、Job Card、Operation、Workstation、工时与完成数量 | ERPNext GPLv3；自托管需运维，托管限制按所选服务核对 | 公开对象最容易核对，适合做首个完整 ERP 连接试点 |
| Siemens Opcenter | Opcenter X 明确有 HTTP、Kafka、OPC UA 连接器。B；某些具体产品有 REST 文档/发布说明。A，但仅限所述产品 | 生产、质量、设备集成能力已声明；本次未取得适用于客户版本的订单/工单字段契约 | X、Execution Discrete、Semiconductor、Intelligence 不是一个通用 API 产品 | 客户已有系统时做专项适配；不据通用宣传承诺现成插即用 |
| SOLIDWORKS PDM Professional | Web API、COM/.NET API、插件事件、Webhooks 配置。A | 工程文件、版本、修订、工作流状态、文件引用、named/computed BOM、焊件切割清单 | Professional 权益与部署；PDM 的 Task 不等于生产工单 | 工程师继续在原 CAD/PDM 工作；发布版本触发拆单候选与差异审查 |
| Rockwell Plex | 官方开发门户和制造业务 API。A | BOM、零件、工艺路线、销售订单、排程、生产操作、库存、工时、质量等 | 生产操作 API 混合稳定与 Beta 端点；客户授权、费用需核对 | 已有 Plex 的工厂按其订单和车间对象映射，不另建重复生产账 |
| 飞书多维表格 | OpenAPI、官方 SDK、变更事件模型、官方开源 CLI、官方 Beta MCP。A | 表、字段、记录、附件引用；BOM/工单是自定义表结构 | 表格业务约束需自建；应用/用户权限、自动化额度与版本需核对 | 保留销售登记、进度表和审批习惯，生产状态由确定的主系统回写 |
| 钉钉宜搭 | 开放 API、页面平台 API、HTTP 服务注册与回调。A/B | 表单实例、流程实例、节点事件；BOM/工单是自定义模型 | 开放 API 为专业版/专属版；公开限流计费帮助页表述有冲突 | 继续用钉钉表单与审批，审批节点把结构化需求交给KANPACE |

表中证据的具体出处与限制如下。

## Odoo：业务 API 明确，但套餐与数据库模型必须先对齐

Odoo 19 新增 JSON-2，使用 `POST /json/2/<model>/<method>` 与 API key；官方说明实际可用模型、字段和方法取决于数据库，可由该数据库的 `/doc` 检查。商业计划中的外部 API 只列为 **Custom**，One App Free 与 Standard 不提供。API 沿用用户访问权限和记录规则。因此连接器应使用专用集成账户，并调用业务方法完成状态变化。[Odoo 19 External JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)

官方 MRP 源码可核对 `mrp.bom` 与 `mrp.workorder`，工序工单关联制造单、工作中心和数量等对象。适配可以从“KANPACE拆出的部件/工艺 → BOM 与工序工单”开始，但不能把KANPACE的一条工种任务直接等同于所有客户数据库中的一条标准工单。[BOM 模型源码](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_bom.py)、[工序工单模型源码](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_workorder.py)

Studio 文档明确支持外部事件进入 Odoo 的 Webhook，也可通过自动化动作向外部 Webhook 发数据。官方 `odoo-bin` CLI 用于运行服务器、模块和数据库开发维护；它不是已核实的通用远程“生产派工 CLI”。本次未核实 Odoo 官方 MCP，不能把应用市场/社区插件标成官方服务。[Webhook 文档](https://www.odoo.com/documentation/19.0/applications/studio/automated_actions/webhooks.html)、[官方 CLI](https://www.odoo.com/documentation/19.0/developer/reference/cli.html)

Community 为 LGPLv3，Enterprise 使用单独的 Enterprise Edition License。**自托管 Community 的技术可用性需要按实际部署核验，不能直接套用云商业套餐的购买结论，也不能把 Enterprise 功能都算进免费版。**[Odoo 19 官方许可说明](https://www.odoo.com/documentation/19.0/ro/legal/licenses.html)

建议接法：销售仍在原 Odoo 确认订单，KANPACE读取已批准订单及工程版本；拆单审核后生成关联制造任务；现场报工经数量、版本、状态校验后回写既有工单。库存与财务过账继续由原 ERP 的业务动作处理。

## ERPNext：开源业务对象与事件机制适合先做可验证连接

Frappe 为 DocType 自动提供 REST API，支持记录读写以及授权的服务端方法；Webhook 可针对某 DocType 的指定文档事件和条件触发 HTTP 请求，支持配置签名密钥。Python hooks 可以扩展服务器事件。[REST API](https://docs.frappe.io/framework/user/en/api/rest)、[Webhooks](https://docs.frappe.io/framework/user/en/guides/integration/webhooks)、[Hooks](https://docs.frappe.io/framework/user/en/python-api/hooks)

ERPNext 的 Job Card 对应工作站上的一道工序，来源于 Work Order，记录员工、时间和完成数量；Work Order 提交时可据工序生成 Job Card。这个对象比一张普通项目任务表更接近“木作开料、五金加工、玻璃验收、接线”等工种执行单。部分完工、损耗计算受版本行为影响，联调要包括部分数量场景。[Job Card 官方业务说明](https://docs.frappe.io/erpnext/job-card)、[Job Card 字段定义](https://github.com/frappe/erpnext/blob/develop/erpnext/manufacturing/doctype/job_card/job_card.json)

ERPNext 官方仓库采用 GPLv3。Bench 是官方管理 CLI，覆盖站点、应用、备份、迁移等；不应把让 Agent 进入管理员控制台作为日常报工接口。本次未核实厂商官方 ERPNext MCP。开源并不免除部署、升级与备份工作；托管服务的可安装应用、服务器脚本与资源限制需按实际套餐另查。[ERPNext 许可证](https://github.com/frappe/erpnext/blob/develop/license.txt)、[Bench 官方概览](https://docs.frappe.io/framework-copy/bench/overview)

建议接法：若客户还没有 ERP，可把 ERPNext 作为订单、物料和制造账候选；KANPACE向其已批准 BOM/Work Order/Job Card 做明确映射。提交文档、取消、修订和库存动作必须通过框架业务流程；单纯 CRUD 成功不能作为生产闭环验收。

## Siemens Opcenter：先确定产品线，再谈具体接口

Siemens 官方 Opcenter X 2501 发布说明给出了 HTTP client 连接 REST、Kafka 发布/消费、OPC UA 数据变化订阅及事件/历史数据等具体连接器能力。这是已核实的集成能力，但不提供一个能覆盖所有客户生产单据的统一字段表。[Opcenter X 2501 官方发布说明](https://blogs.sw.siemens.com/opcenter/whats-new-in-opcenter-x-2501/)

另一个官方例子是 **Execution Semiconductor 2304** 的 REST/Swagger、事件发现、OData 和 outbound REST 更新。它只能证明该产品和版本的能力，不能替代 Execution Discrete 客户的接口手册；同理，Opcenter Intelligence 的分析 API 不能冒充生产工单写入 API。[Semiconductor 2304 官方功能说明 PDF](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/7KZ5yp58eh1O7a6B7lLuhh/en-US/Siemens%20SW%20Whats%20new%20in%20Opcenter%20Execution%20Semiconductor%202304%20Fact%20Sheet.pdf)、[Intelligence API 官方页面](https://developer.siemens.com/insights-hub/docs/apis/advanced-opcenter-intelligence/api-opcenter-intelligence-api.html)

本次未核实适用于整个 Opcenter 产品族的官方派工 CLI、MCP 或统一 SDK。公开资料不足以判断客户已购买哪些连接器、哪些写入权限、是否另收集成费。建议客户已有 Opcenter 时，先取得产品全名、版本、已授权模块、API/事件目录和测试环境，再验证一条订单导入、一条工序下发、一条部分报工和一次图纸变更；不要让中小工厂仅为连接KANPACE而先采购大型 MES。

## SOLIDWORKS PDM Professional：沿工程师原有工作习惯接工程版本

官方 PDM Professional API 公开了独立应用和插件两种方式；插件可响应签入、签出、文件新增和状态变更，API 覆盖文件引用、变量、工作流、版本/修订和任务等。官方提供安装环境中的 COM/.NET 互操作程序集，适合做运行在工程 Windows 工作站/服务器上的连接服务。[PDM 2026 API Getting Started](https://help.solidworks.com/2026/English/api/epdmapi/GettingStarted-epdmapi.html?format=P&value=)

PDM Professional Web API 文档列出认证、文件/BOM和配置接口，包括 named BOM、computed BOM、焊件 cut list，以及 Webhook URL 与 add-in hook 配置。这里的 **BOM 可提取** 不意味着 API 已替我们完成几何识别、木板排版、钣金展开或展示柜工艺推理。[PDM Professional Web API 2025](https://help.solidworks.com/2025/English/api/pdmprowebapihelp/PDM%20Pro%20API_ws.html)

官方说明 API 属于 PDM Professional；应核对客户是否仅购买了 Standard、是否部署 Web API Server、具体版本支持哪些端点。PDM 的 Tasks 主要是工程系统任务，不能自动解释为车间的生产工单。本次未核实官方 MCP/通用业务 CLI。[PDM API Release Notes](https://help.solidworks.com/2025/english/api/epdmapi/ReleaseNotes-epdmapi.html?format=P&value=)

建议接法：工程师仍在 SOLIDWORKS/PDM 签入和发布，连接器只把明确发布的图纸版本、配置、部件引用与 BOM 送入KANPACE。KANPACE建立工程 BOM 到制造 BOM 的映射，显示增删件和尺寸/材料变化，再决定哪些未完工任务需要失效或重做。未使用 PDM 的客户另走文件导入/工程插件路线，不把安装 PDM 设为软件使用前提。

## Rockwell Plex：有真实制造 API，稳定性和客户权益仍需逐项核对

Plex 官方开发门户公开的 API 类别包括 BOM、Parts、Process Routings、Sales Orders、Sales Releases、Job Scheduling、Production Operations Management、Time Clock Entries、Inventory、Purchase Orders、Digital Work Instructions 和 Checksheet。这些类别覆盖了工程物料、订单、排程、现场与质量的主要接点。[Plex 官方 API 目录](https://developers.plex.com/docs)

生产操作 API 官方页面明确写明稳定端点和 Beta 端点并存，Beta 的支持期限有限且可能变化。该页面给出工作中心、源库存装载等真实操作例子；因此不能以“有 Production API”推断所有报工、撤销与重开动作都稳定可用。[Production Operations Management API](https://developers.plex.com/docs/production-operations-management-api)

Plex 官方资料说明有 API/集成层和 Custom APIs，但本次未确认客户订阅的调用额度、写入授权、计费或官方 MCP/CLI/通用 SDK。这里的 Plex 指 Rockwell 制造云，**不是 plex.tv 媒体服务器**，两者的 Token 和 SDK 完全不能混用。[Plex Platform 官方资料 PDF](https://plex.rockwellautomation.com/content/dam/plex/legacy/2022-07/10008_Plex_Platform_Brochure.pdf)、[Plex Custom APIs 官方资料 PDF](https://plex.rockwellautomation.com/content/dam/plex/legacy/2022-06/10301_Plex_Datasheet_ERP_CustomAPIs.pdf)

建议接法：保留客户 Plex 的零件编号、工作中心和订单，KANPACE提供展示柜专用拆单、图纸证据和班组执行界面。连接前获得具体端点的稳定/Beta 状态、鉴权和业务示例；不要自行把考勤 Time Clock Entries 当成工序完工数量。

## 飞书多维表格：官方 API、CLI 和 MCP 都存在，但表格模型要自己定义

飞书有多维表格记录 OpenAPI；官方 SDK 仓库还包含多维表格记录变化事件模型，字段包括 table_id、revision、operator 和 action_list。订阅所需权限和文件授权仍须在租户验证，不能只靠模型类存在就认定所有改动都会推送。另有多维表格自动化的外部 Webhook 触发功能，方向是外部请求触发表内自动化。[创建记录 API](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_create)、[官方 Python SDK 变更事件模型](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/drive/v1/model/p2_drive_file_bitable_record_changed_v1.py)、[自动化 Webhook 触发说明](https://www.feishu.cn/hc/zh-CN/articles/612376356355-%E4%BD%BF%E7%94%A8%E8%87%AA%E5%8A%A8%E5%8C%96%E6%B5%81%E7%A8%8B%E7%9A%84-webhook-%E8%A7%A6%E5%8F%91)

`larksuite/cli` 是官方开源 CLI，能操作多维表格等产品；`larksuite/lark-openapi-mcp` 是官方 OpenAPI MCP 项目，当前 README 标为 Beta。MCP 需要应用及权限，并有工具兼容范围和文件操作限制；不能当作覆盖所有 OpenAPI 的稳定承诺。中国飞书与国际 Lark 的应用和 API 域名要匹配。[官方 CLI](https://github.com/larksuite/cli/blob/main/README.zh.md)、[官方 MCP](https://github.com/larksuite/lark-openapi-mcp)

表、字段和记录是通用对象，并无本次核实到的内置展示柜 BOM/制造工单事务。应用权限还需要文档授权；高级权限与套餐有关，自动化和数据额度应核对实际版本，本次不引用易变的统一额度数字。[官方 API 接入示例及权限](https://www.feishu.cn/content/137710114294)、[高级权限官方说明](https://www.feishu.cn/hc/zh-CN/articles/892315791286-%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E9%AB%98%E7%BA%A7%E6%9D%83%E9%99%90%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)

建议接法：保留现有“订单登记表/安装排期表”，新增不可手改的外部 ID、图纸版本、系统状态和原单链接。员工在熟悉的表单提交变更/异常，KANPACE审核处理后回写结果。CLI/MCP 适合授权的查询和草稿操作；确定性接口负责生产状态校验和重复请求处理。

## 钉钉宜搭：表单与审批适合保留，接口权益要查清

宜搭官方版本对照把开放 API 列为专业版、专属版能力。页面平台 API 则使用应用域名/AppCode 等上下文，是另一个调用面，不能把页面内 API 直接当作已授权的外部服务器 API。[开发能力/版本对照](https://docs.aliwork.com/docs/developer/usage/price)、[平台 API 说明](https://docs.aliwork.com/docs/yida_support/lbtl0t/aql605)

官方服务注册支持普通企业使用 HTTP 连接外部系统；服务回调可在表单和流程节点进行校验或执行动作。这支持“审批通过后通知KANPACE”“KANPACE向既有宜搭应用回写结果”的工程方向，但准确鉴权、字段与幂等策略仍须依据所选外部接口落地。[服务注册说明](https://docs.aliwork.com/docs/yida_qalist/lmvsctyt7rxtgsrq/ld80ev)、[服务回调说明](https://docs.aliwork.com/docs/yida_qalist/lmvsctyt7rxtgsrq/kkcdu6)

官方限流帮助页同时出现“自建应用受钉钉开放平台政策影响”和“宜搭调用不计入、不受政策限制”等表述，并按接口复杂度/组织等维度解释限制。**本次不把宜搭 API 写成一律免费、不限额或统一 40 QPS**；以租户版本、准确接口和当前合同/控制台为准。本次未核实宜搭专用官方 MCP、CLI 或覆盖全部宜搭业务的 SDK；钉钉具有 AI 能力也不构成这些接口的证据。[官方限流与计费帮助页](https://docs.aliwork.com/docs/yida_support/lbtl0t/wae8oddztfq167ly)

建议接法：销售和项目经理继续用原宜搭表单及审批；将客户、交期、柜体配置、图纸版本和审批通过状态映射给KANPACE，现场异常返回原流程。宜搭中的“BOM表”和“工单表”属于客户自定义模型，必须明确字段及状态规则。

## 三类标准应放在正确层次

| 标准/接口 | 它解决什么 | 在本项目中怎样用 | 不能据此宣称什么 |
|---|---|---|---|
| ISA-95 / IEC 62264 | 企业与制造控制之间的活动层次、术语及信息交换对象 | 用来对齐人员、设备、物料、生产计划/执行绩效的共同词汇 | 采用 ISA-95 不会自动得到任何 ERP 的访问权限或 REST 端点 |
| OPC UA | 信息模型、服务、发现、安全通信、订阅和事件等工业互操作能力；不限于设备层 | 设备或既有系统已有 OPC UA Server 时，从公开节点模型采集状态/事件 | “支持 OPC UA”不等于已有工单字段，也不等于授权可写任意生产系统 |
| MQTT | 面向发布/订阅的消息传输，不规定业务 Payload 语义 | 工牌规模化后可承载任务通知、在线状态与业务回执，但主题和数据结构要自己定义 | QoS 不等于工人完成，也不替代 ERP 业务事务；收到消息仍需独立业务回执 |
| 各厂商业务 API | 指定系统中的订单、BOM、工单、库存和业务动作 | 通过适配器转换共同业务模型与厂商对象，校验真实返回状态 | HTTP 200、消息送达、写入一条记录，不自动代表生产完成或库存过账成功 |

前三行的官方依据：[ISA-95 标准组织说明](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard)、[OPC UA 官方架构概述](https://reference.opcfoundation.org/specs/OPC-10000-1/4)、[OASIS MQTT 5.0 规范](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)。最后一行及各行“怎样用/不能宣称”是本项目的工程边界判断。

## 最小接入顺序与可验收范围

优先选择**一个客户已经在用的入口系统和一个生产主系统**。例如“PDM 发布版本 → KANPACE拆单审核 → ERPNext/Odoo 工序 → 工牌派工 → 合格数量/异常 → ERP 回写 → 飞书或宜搭进度展示”。这是可选的组合，不要求客户一次购买整套系统。

第一批连接器只需证明以下闭环，避免堆满接口却没有可核对结果：

1. 读取一个真实已批准订单及其图纸/BOM版本，保留来源系统和原单 ID。
2. 把一个综合展示柜拆成木作、五金、玻璃、灯光和装配任务，保存部件数量、单位、工序依赖、责任角色及工程证据。
3. 人员确认发布后写入目标系统，并记录目标单号；重试同一请求不会多建一份任务。
4. 设备收件、人员开工、部分完工、质检通过分别记事件，不相互替代；重复和迟到回执不重复扣料或累计数量。
5. 图纸升级后能指出受影响的未完工工序；原版本历史保留，新旧任务不同时当作有效任务。
6. ERP、表格或无线网络暂时不可达时，有明确待同步/失败状态与重试记录；恢复后按目标系统真实状态对账。

建议KANPACE内部统一保存 `source_system`、`source_id`、`project_id`、`drawing_revision`、`bom_revision`、`operation_id`、`trade/role`、`quantity/unit`、`status`、`event_id` 和源记录链接。对接外部系统前先约定每个字段及状态由谁维护。MCP、CLI、Webhook、MQTT 都是连接方式；展示柜拆单准确性、版本追踪、工序依赖和报工一致性才是需要独立验证的产品能力。
