# 国际 ERP / MES / 供应链接口核验（KANPACE Web 接入研究）

核验日期：2026-09-04。范围：10 条产品线，仅查官方产品、开发者、API、发布及许可技术文档。尚未连接任何客户 ERP 租户，以下“已核验”指文档契约，不能等同实际账号授权、实测联通或端到端业务验证。

证据等级：**A**＝至少存在本行所列具体技术契约/端点文档；**B**＝官方能力说明，但未取得本次所需完整对象契约；**C**＝证据不足。A 是证据可追溯等级，不能推断该产品的所有对象、所有字段和所有版本已核验。SDK/CLI 指开发工具或接口客户端，不自动意味着可通过命令行任意写 ERP。

公开文档没有找到，不等于产品没有接口。MCP 的服务器、客户端、示例代码、集成层包装、有限开放和规划分别记录；MCP 本身不提供额外业务授权，不意味着具备全面写权限。凡无 GA 版本/范围证据，均不另行宣称全量 GA。

## 总览

| 产品线 | 分类 | 已确认接口路径 | 证据 | 对KANPACE的接法 |
|---|---|---|---|---|
| SAP S/4HANA | 国际ERP | OData V2/V4；SOAP A2A；Business Events；SAP Cloud SDK | A | 以确定性 API 接订单、物料和生产订单；KANPACE保存图纸版本/来源及外部单据号，报工拆为生产确认与物料过账结果两段核验。MCP 只包装已审核的查询与业务动作。 |
| SAP Business One | 国际ERP | Service Layer OData V3/V4；DI API；Webhooks（FP2602+） | A | 适合首批中小型展示柜 ERP 适配：订单→KANPACE工程 BOM/工艺审阅→ProductTrees/ProductionOrders；发料/完工入库保留 external_id 幂等。老版本先增量拉取，新版本评估 webhook。 |
| SAP Digital Manufacturing | 国际MES | REST APIs；OAuth2 service key；Cloud/Edge APIs；生产过程事件 | A | 以 ERP 保留销售订单，KANPACE承接图纸与工种任务，DM 作为执行主系统时映射 SFC/operation；明确由哪一侧触发完工收货，防止双写库存。 |
| Microsoft Dynamics 365 Business Central | 国际ERP | REST API V2.0 / OData；AL custom API；Webhooks；官方 MCP（Online） | A | 先接销售订单、物料与库存读取；用 AL 扩展明确发布展示柜 BOM/生产工单/报工动作，再把选定 API 暴露给 MCP。制造扩展和 Premium 授权作为实施前置条件。 |
| Microsoft Dynamics 365 Supply Chain Management | 国际ERP | OData data entities；Data Management package REST；MES message API；Business Events；官方动态 ERP MCP | A | 优先用专用 MES 消息接口回传工时/数量/消耗，监听结果与失败队列；单据头行分步导入并补偿。MCP 适合有审计的查询和经过白名单的动作，批量确定性同步仍走接口。 |
| Oracle Fusion Cloud SCM | 国际ERP | REST APIs；FBDI 批量导入；部分 SOAP 服务；OIC business events | A | REST 读订单/BOM，工单及报工写入分别映射角色权限；库存暂存与最终过账分开追踪。历史 SOAP 接口逐项对照退役说明。需要 MCP 时基于 OIC 或KANPACE自己的受控适配层封装。 |
| Oracle NetSuite | 国际ERP | SuiteTalk REST；SuiteQL；SuiteScript / RESTlets；SuiteCloud SDK/CLI；官方 AI Connector MCP | A | 用 REST + external IDs / 变换动作承接订单与生产工单；复杂制造记录先做 sandbox。MCP 用 Standard Tools 精选角色，批量同步用 REST。SuiteScript 负责可补偿的变更通知/扩展，避免把原始数据库查询当业务提交。 |
| Infor CloudSuite / ION（M3、CSI 分别核验） | 国际ERP | ION API Gateway / REST；M3 MI transactions；ION BOD；Infor OS MCP（按产品/发布范围） | A | 先由客户确认 M3/CSI/LN 和准确版本，再以 MI 或 BOD 接订单/BOM/生产事件；不要实现一个叫 Infor 的万能字段映射。MCP 接入列为需租户开通核实项。 |
| Epicor Kinetic | 国际ERP | REST / OData V4；Business Objects / BAQ / Functions；BPM；Cloud SDK | B | 取得客户租户 REST Help / Swagger 导出，逐一验证订单、BOM、工单、库存、工时报工 BO 的方法与业务校验，再决定适配范围。当前仅建立候选连接器，不显示“已连通”。 |
| IFS Cloud | 国际ERP | Projection OData V4；OpenAPI 2/3；MES ShopFloorConnector；IFS Connect events | A | 优先以 ShopFloorConnector 对接工序开始、工时、数量和完工收货；先读取并锁定 BOM/路线 revision，外部任务映射至 shop order/operation。销售订单/BOM 写入另开契约核验任务。 |

以下逐产品表给出每条结论旁的原始来源，避免总览中的接口名称被误读为对象全覆盖。

## 1. SAP S/4HANA（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 销售订单有 OData V4 创建接口；订单 BOM 有创建接口。API_PRODUCTION_ORDER_2_SRV 可读、创建、有限字段修改及释放/技术完成生产订单。API_PROD_ORDER_CONFIRMATION_2_SRV 可创建生产确认并带物料移动；不能把其 HTTP 成功视为全部物料过账成功，物料凭证失败可能进入 COGI。这里验证的是订单 BOM，不能自动等同所有物料 BOM 变更场景。 [销售订单创建 OData V4](https://help.sap.com/docs/SAP_S4HANA_CLOUD/03c04db2a7434731b7fe21dca77440da/9c75cb47849149ca8a5c644c98965ff1.html) [订单 BOM 创建](https://help.sap.com/docs/SAP_S4HANA_CLOUD/7489fa08cede494cbdf08fa3651598af/339b6cbbd3a54cf1b739f1707ce88de4.html?locale=en-US&state=PRODUCTION&version=2608.500) [Production Order V2](https://help.sap.com/docs/SAP_S4HANA_CLOUD/d35113ee62644d3abee1aaec148291d9/0a4262096d2e43258df27c594bdd1468.html) [生产确认和独立物料过账结果](https://help.sap.com/docs/SAP_S4HANA_CLOUD/d35113ee62644d3abee1aaec148291d9/728de485cfc843f9a76f661b1fcbd5a5.html) |
| 认证与身份 | 按通信场景选择技术用户/身份传播等方式；官方 S/4HANA Cloud 集成说明包含通信安排和 OAuth2 SAML bearer。不能把一种认证方式宣布为全部接口通用。 [S/4HANA Cloud 连接和认证配置](https://help.sap.com/docs/integration-suite/sap-integration-suite/sap-s-4hana-cloud) |
| 事件 / 消息 | 官方企业事件机制可经通信安排连接 SAP Event Mesh；事件对象及负载按事件目录确认，不能认为每个 BOM 字段变化都有现成通知。 [企业事件配置示例](https://help.sap.com/docs/CX_NG_SVC/56436b4e8fa84dc8b4408c7795a012c4/15bb1e4a86894969b26656ed857334fc.html) |
| SDK / CLI | SAP Cloud SDK 官方提供 OData/OpenAPI 客户端生成器；JS/TS OData 可用 @sap-cloud-sdk/generator 与 npx generate-odata-client。这是生成 API 客户端的 CLI，不是直接操作所有 ERP 单据的 CLI。 [SAP Cloud SDK OData generator](https://sap.github.io/cloud-sdk/docs/js/features/odata/generate-client) |
| 版本与授权边界 | Public Cloud、Private Edition、本地部署的版本、通信场景和允许操作不同；须启用匹配的 communication arrangement 并授予业务权限。不能把 Public Cloud 2608 文档套用到旧本地版本。Integration Suite / Integration Cell 的可用性另受服务计划约束。 [S/4HANA Cloud 连接和认证配置](https://help.sap.com/docs/integration-suite/sap-integration-suite/sap-s-4hana-cloud) [Integration Suite MCP artifact](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/how-model-context-protocol-mcp-enables-ai-integration-with-apis?locale=en-US&state=PRODUCTION&version=CLOUD) |
| 官方 MCP 状态 | 官方 Integration Suite 已有 MCP artifact 技术文档，可从已部署 API、HTTP/OpenAPI 或 RFC 后端构造选定工具；这是需配置和部署的集成层，不等于 S/4HANA 所有业务对象开箱写入。ABAP MCP 用于开发代码，不等于业务单据 MCP。当前查到可用技术文档，不推定每个租户都已开通。 [Integration Suite MCP artifact](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/how-model-context-protocol-mcp-enables-ai-integration-with-apis?locale=en-US&state=PRODUCTION&version=CLOUD) [ABAP agentic development / MCP](https://news.sap.com/2026/08/with-agentic-ai-abap-takes-evolution-to-the-next-level/) |

**建议接法（本研究判断）：** 以确定性 API 接订单、物料和生产订单；KANPACE保存图纸版本/来源及外部单据号，报工拆为生产确认与物料过账结果两段核验。MCP 只包装已审核的查询与业务动作。

## 2. SAP Business One（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | Service Layer API Reference 明列 Orders、ProductTrees（BOM）、ProductionOrders 的 GET/POST/PATCH；InventoryGenEntries 和 InventoryGenExits 支持生产收料/发料等库存单据。生产收发料和工单状态可对接，但本次未核验等同 MES 的逐人逐工序工时报工模型。 [Service Layer API Reference（含各实体操作）](https://help.sap.com/doc/056f69366b5345a386bb8149f1700c19/10.0/en-US/Service%20Layer%20API%20Reference.html) |
| 认证与身份 | 传统 Service Layer 使用 Login 返回 B1SESSION 会话，负载均衡可带 ROUTEID；Business One Cloud IAM 文档另有 OAuth Bearer 与 company id，不能把 Cloud IAM 认证套到所有单机部署。 [传统 Login/会话技术说明（9.3）](https://help.sap.com/doc/0d2533ad95ba4ad7a702e83570a21c32/9.3/en-US/Working_with_SAP_Business_One_Service_Layer.pdf) [Business One Cloud OAuth/IAM](https://help.sap.com/docs/SAP_BUSINESS_ONE_CLOUD/c3a2e34ed796424a8817ad872bff4a79/986dc0a7bd164d69846e8a0054fe610a.html) |
| 事件 / 消息 | 10.0 FP2602 起官方 Service Layer Webhooks；需启用功能并部署 Webhook Messenger。订阅 API 支持创建、查询、修改、删除；停机漏事件的补发/重放须按配置实现，不视为天然 exactly-once。 [FP2602 Webhooks 发布说明](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/c61c54be65b74486b8bed0ab7feab6a7.html) [Webhook 订阅 API](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/ea37739cf17f44f6bd36c2e9f7a296ff.html) |
| SDK / CLI | DI API 为官方 SDK，Service Layer 使用同一业务对象核心；可生成 OData 客户端。本次未核验跨部署通用的业务操作 CLI。 [Service Layer / DI API 架构](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/36a5b88dce7d4d3b8c1abf1ac4e9dd2d.html?locale=en-US) |
| 版本与授权边界 | 优先 OData V4 /b1s/v2；V3 /b1s/v1 为兼容路径，旧 WCF/V3 技术自 FP2108 起弃用。SQL Server 与 HANA 部署须按各自版本配置 Service Layer，不能再笼统称 HANA 专属。FP2602 webhook、FP2608 MCP 示例仅适用于对应更新级别。 [OData 协议版本](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/60c7a0b745bd486589f05a1da77041f3.html) [旧 WCF/OData V3 弃用说明](https://help.sap.com/docs/SAP_BUSINESS_ONE/e83fb6dd8db7421486e0a2bb4e326720/61e0cdf417ac4baa9fdf6296733b9145.html) [SQL Server Service Layer 安装边界](https://help.sap.com/docs/SAP_BUSINESS_ONE_ADMIN_GUIDE_SQL/f6fb230cc90949d8b66586a39189992b/9b01e69e7c714025a46fa7ad22e28f62.html) [FP2602 Webhooks 发布说明](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/c61c54be65b74486b8bed0ab7feab6a7.html) [FP2608 官方 MCP Sample Code](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/286fda530e5249bc90e2fa51fd3c10db.html?locale=en-US) |
| 官方 MCP 状态 | 官方 10.0 FP2608 发布 MCP Sample Code 及辅助 annotated metadata。状态是官方示例代码；不能当成熟托管 MCP 服务、承诺 GA SLA 或默认全业务写权限；metadata 文档也提醒响应可能变化。 [FP2608 官方 MCP Sample Code](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/286fda530e5249bc90e2fa51fd3c10db.html?locale=en-US) [MCP annotated metadata 的稳定性边界](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/bc9463949d4f4239a25792aa98633520.html?locale=en-US) |

**建议接法（本研究判断）：** 适合首批中小型展示柜 ERP 适配：订单→KANPACE工程 BOM/工艺审阅→ProductTrees/ProductionOrders；发料/完工入库保留 external_id 幂等。老版本先增量拉取，新版本评估 webhook。

## 3. SAP Digital Manufacturing（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 官方 Edge 支持清单确认 GET /bom/v1/boms、/order/v1/orders、/material/v1/materials、/inventory/v1/batches 等读取。2608 更新列明 Order V2 release、BOM 组件 customValues 更新，以及 Edge SFC start/complete/scrap、quantityConfirmation/confirm。Inventory V2 可查收发料并 POST EWM goods receipt；这不等于在 DM 中建立 ERP 销售订单。 [Edge 可用 API 清单](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/b17dfa5bc22743ffba66facce41ed510.html) [2608 APIs 更新](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/d466f10f1cf34c10828689e35e73db80.html) [Inventory V2 / EWM 收货限制](https://help.sap.com/docs/sap-digital-manufacturing/apis/inventory-v2) |
| 认证与身份 | 官方 API 集成文档提供 public-api-endpoint、client id/secret、token URL 的 service key，采用 OAuth2 客户端认证；也有证书配置选项。 [API 集成准备 / 服务密钥](https://help.sap.com/docs/sap-digital-manufacturing/operations-guide/prepare-for-api-integration?ai=true) |
| 事件 / 消息 | 生产过程提供自动触发/事件能力，2608 文档列出 SFC 相关事件版本变化；按当前租户事件目录订阅，不能把每个 REST 操作当作已存在 webhook。 [2608 APIs 更新](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/d466f10f1cf34c10828689e35e73db80.html) |
| SDK / CLI | 可从 API 契约生成 REST 客户端；本次未确认一个专用、统一的 DM 业务操作 CLI。SAP Cloud SDK OpenAPI generator 可作为通用生成工具。 [SAP Cloud SDK OpenAPI generator](https://sap.github.io/cloud-sdk/docs/js/features/openapi/generate-client) |
| 版本与授权边界 | 必须有相应 DM 服务实例/权限及 integration service key；Cloud 与 Edge 支持集不同。2608 新增 Edge 能力不可套到旧 Edge。EWM 收货依赖对应集成配置，不能与 SFC complete 的自动收货重复使用。 [API 集成准备 / 服务密钥](https://help.sap.com/docs/sap-digital-manufacturing/operations-guide/prepare-for-api-integration?ai=true) [Edge 可用 API 清单](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/b17dfa5bc22743ffba66facce41ed510.html) [2608 APIs 更新](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/d466f10f1cf34c10828689e35e73db80.html) [Inventory V2 / EWM 收货限制](https://help.sap.com/docs/sap-digital-manufacturing/apis/inventory-v2) |
| 官方 MCP 状态 | 本次未在官方产品文档核验 DM 独立对外 MCP server。可利用 SAP Integration Suite 的官方 OpenAPI→MCP 能力构建适配，但这是实施工作；社区自建 DM MCP 不能标为官方产品。 [Integration Suite MCP 集成能力](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/how-model-context-protocol-mcp-enables-ai-integration-with-apis?locale=en-US&state=PRODUCTION&version=CLOUD) |

**建议接法（本研究判断）：** 以 ERP 保留销售订单，KANPACE承接图纸与工种任务，DM 作为执行主系统时映射 SFC/operation；明确由哪一侧触发完工收货，防止双写库存。

## 4. Microsoft Dynamics 365 Business Central（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 标准 salesOrder API 提供读写及 shipAndInvoice bound action；item 提供物料读写及库存数量读取。不能直接 PATCH item.inventory 当库存过账。此次没有核验生产 BOM、生产工单、消耗/产出报工全部都存在标准 v2.0 API；需要导出租户 metadata 并用 AL API pages/actions 补齐。 [Sales order API / shipAndInvoice](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_salesorder) [Item API](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_item) [AL custom API 开发](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api) |
| 认证与身份 | Entra OAuth2；后台同步可用 S2S client credentials，应用映射到 Business Central 权限集，S2S 应用不能被授予 SUPER。MCP 则按文档使用用户委托认证。 [S2S OAuth 和权限](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/administration/automation-apis-using-s2s-authentication) [官方 MCP / 默认只读 / Online 边界](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview) |
| 事件 / 消息 | 官方 subscriptions/webhook 有验证握手；订阅有效期 3 天，需续期 PATCH。须保存订阅到期时间并安排续订与补拉。 [Webhook subscriptions](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/dynamics-subscriptions) |
| SDK / CLI | AL custom API page/action 为官方扩展机制；可用通用 OAuth/MSAL 与 HTTP/OData 客户端。未核验开箱的制造业务 CRUD CLI。 [AL custom API 开发](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api) |
| 版本与授权边界 | 生产制造功能受 Premium 体验/许可证约束；S2S 支持版本、Online/On-premises 配置不同。官方 MCP 当前只适用 Business Central Online。没有 API 页面或没有实体写权限的对象，不会因接上 MCP 自动变得可写。 [Premium 制造体验](https://learn.microsoft.com/en-us/dynamics365/business-central/ui-experiences) [S2S OAuth 和权限](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/administration/automation-apis-using-s2s-authentication) [官方 MCP / 默认只读 / Online 边界](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview) |
| 官方 MCP 状态 | 官方 MCP 端点 https://mcp.businesscentral.dynamics.com；默认只读，管理员需逐 API 开启 create/modify/delete/bound actions。OAuth2 Authorization Code + PKCE / Entra delegated identity。当前已有正式配置技术文档，未以某份预览计划推断所有客户可用或默认可写。 [官方 MCP / 默认只读 / Online 边界](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview) |

**建议接法（本研究判断）：** 先接销售订单、物料与库存读取；用 AL 扩展明确发布展示柜 BOM/生产工单/报工动作，再把选定 API 暴露给 MCP。制造扩展和 Premium 授权作为实施前置条件。

## 5. Microsoft Dynamics 365 Supply Chain Management（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | SalesOrderHeadersV2 支持导入/更新订单头，订单行独立实体，更新要求订单处于开放状态。官方 MES 集成明确支持生产订单 start、report finished、material consumption、operation time、end，通过 SysMessageService/SendMessage 排队处理。生产订单已释放/状态改变有业务事件；BOM 主数据写入及独立库存调整仍须按租户实体目录进一步核验。 [Sales order headers V2 实体](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/entity-sales-order-headers-v2-salesorderheaderv2) [MES 集成消息、工时报工、许可前置](https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/mes-integration) |
| 认证与身份 | 后台 OData/Data Management 使用 Entra 应用认证并映射应用权限；MCP 每次使用认证身份，可为委托用户或独立 agent identity，管理员限制允许客户端；不绕过财务/生产业务校验。 [OData / Data Management integration APIs](https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/contract-lifecycle-management/developer/clm-data-integration-apis) [MCP 身份和权限](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/mcp/mcp-security) |
| 事件 / 消息 | 生产订单 release/status change 可经 Business Events 触发下游；MES inbound 消息由批处理异步、按同一订单顺序执行，需读取处理状态及错误，HTTP 收到不等于已完成报工。 [MES 集成消息、工时报工、许可前置](https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/mes-integration) |
| SDK / CLI | 官方支持 X++ 自定义服务/业务逻辑扩展和数据实体；HTTP/OData 客户端可使用普通编程 SDK，MCP action 可通过 ICustomAPI 扩展。没有据此声称一个 CLI 就覆盖全部供应链操作。 [动态 ERP MCP 版本、工具和计费](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/copilot-mcp) [入站集成架构与 X++ 服务](https://learn.microsoft.com/en-us/dynamics365/guidance/reference-architectures/finance-operations-resilient-inbound-integration-external-system) |
| 版本与授权边界 | MES 集成功能要求 Time and attendance license key。动态 MCP 要求至少 10.0.47、10.0.46 PQU-2 或 10.0.45 PQU-7；Tier 2+ 或 Unified Developer Environment，CHE 不支持；需要 Allowed MCP Clients。MCP 工具调用存在依客户端及许可证而异的计费，不能当免费无限调用。 [MES 集成消息、工时报工、许可前置](https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/mes-integration) [动态 ERP MCP 版本、工具和计费](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/copilot-mcp) |
| 官方 MCP 状态 | 官方当前动态 ERP MCP 有 data CRUD、form、action 三类工具，权限仍由应用执行，data create 不支持 deep insert。旧 Dataverse 静态 13 工具服务计划 2026-10-01 退役；不要新接旧版。当前技术文档已提供可用版本与配置，不把早期静态 MCP 的 GA 日期自动等同新动态版本的发布时间。 [动态 ERP MCP 版本、工具和计费](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/copilot-mcp) [MCP 身份和权限](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/mcp/mcp-security) |

**建议接法（本研究判断）：** 优先用专用 MES 消息接口回传工时/数量/消耗，监听结果与失败队列；单据头行分步导入并补偿。MCP 适合有审计的查询和经过白名单的动作，批量确定性同步仍走接口。

## 6. Oracle Fusion Cloud SCM（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | Sales Orders for Order Hub 支持读、创建/更新订单，官方已用 REST/FBDI 替代多项旧 SOAP 操作。itemStructures（BOM）有 GET/POST/PATCH；workOrders 有 POST。operationTransactions 可 POST 报工，但不支持 GET，不能承诺此生产交易接口完整 CRUD。inventoryStagedTransactions 可创建暂存库存交易，后续处理结果仍需确认。 [Order Management 26B SOAP→REST/FBDI 替换边界](https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/order26b/26B-order-mgmt-wn-t72535.htm) [Item Structures REST 操作](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/fasrp/api-product-lifecycle-management-item-structures.html) [创建 workOrders](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/op-workorders-post.html) [Operation Transactions 仅支持的操作](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/api-manufacturing-work-order-operation-transactions.html) [创建 Inventory Staged Transactions](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/fasrp/op-inventorystagedtransactions-post.html) |
| 认证与身份 | Fusion REST 文档列出 HTTPS Basic/SAML/JWT 等；当前 Fusion 公共服务指南亦支持 OAuth2，并提供 IAM client credentials 配置。应优先按目标租户与资源版本配置 OAuth，不能拿 OCI API 签名密钥替代 Fusion 业务认证。 [Fusion OAuth 配置](https://docs.oracle.com/en/cloud/saas/applications-common/26b/oaext/configure-oauth.html) [SCM REST Quick Start 认证](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/fasrp/Quick_Start.html) |
| 事件 / 消息 | OIC Oracle ERP Cloud Adapter 官方事件目录包含 SCM/采购、库存、制造、订单管理、PLM；各事件有自己的负载和回调。不能将 adapter 覆盖范围理解成每个字段变化都能 webhook。 [Oracle ERP Cloud Adapter 支持 SCM 事件](https://docs.oracle.com/en/cloud/paas/application-integration/erp-adapter/oracle-erp-cloud-adapter-capabilities.html) |
| SDK / CLI | 官方 REST 文档有 cURL 示例，批量场景有 FBDI，集成可用 OIC adapter。本次未核验一个专门操作 Fusion SCM 所有业务对象的 SDK/CLI；OCI CLI 管基础设施不等于 SCM CRUD。 [Order Management 26B SOAP→REST/FBDI 替换边界](https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/order26b/26B-order-mgmt-wn-t72535.htm) [SCM REST 26B 官方索引](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/index.html) |
| 版本与授权边界 | 按季度版本（此处主要 26A/26B，BOM 引用 25C）、已购买 SCM 模块和 REST privileges 核验；PLM、Manufacturing、Inventory、Order Management 并非一个权限。销售数据访问规则可能进一步限制 REST 可见订单。OIC 适配/agentic integration 是额外服务和部署边界。 [Order Management 26B SOAP→REST/FBDI 替换边界](https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/order26b/26B-order-mgmt-wn-t72535.htm) [REST roles and privileges](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/Roles_and_Privileges.html) [Oracle Integration 3 项目 MCP](https://docs.oracle.com/cd/G41715_01/paas/application-integration/aiagents/using-agentic-ai-oracle-integration-3.pdf) |
| 官方 MCP 状态 | 未核验 Fusion SCM 自身独立对外 MCP server。Fusion AI Agent Studio 的 MCP tool 文档描述连接外部 MCP，是客户端能力。Oracle Integration 3 官方支持把项目中的已选 integration tools 作为 MCP 暴露；不能据此声称所有 SCM 单据自动可写。 [AI Agent Studio 外部 MCP tools](https://docs.oracle.com/en/cloud/saas/fusion-ai/aiaas/how-do-i-use-ai-agent-studio.pdf) [Oracle Integration 3 项目 MCP](https://docs.oracle.com/cd/G41715_01/paas/application-integration/aiagents/using-agentic-ai-oracle-integration-3.pdf) |

**建议接法（本研究判断）：** REST 读订单/BOM，工单及报工写入分别映射角色权限；库存暂存与最终过账分开追踪。历史 SOAP 接口逐项对照退役说明。需要 MCP 时基于 OIC 或KANPACE自己的受控适配层封装。

## 7. Oracle NetSuite（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 官方 REST record 清单包括 Sales Order、BOM/BOM Revision、Inventory Adjustment/Transfer、Work Order/Issue/Completion/Close。workOrder 具体文档给出 GET/POST/PATCH 及 transform 为发料、完工、关闭等例子。其他对象不能仅因列在清单就推定任意字段都可改，需继续读取每个 record schema 和 transformation 约束。 [REST 支持的 Records](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1558962745.html) [Work Order REST 和转换操作](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_47212826771.html) |
| 认证与身份 | 后台可配置 OAuth2 M2M client credentials 的证书/实体/角色映射；每个账户单独配置，sandbox refresh 会清除该 M2M 设置。MCP 是交互授权码+PKCE，不能与 M2M 流程混为一种。 [OAuth2 M2M setup / sandbox 边界](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_162686838198.html) [MCP AI Connector Service 接入](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_4160616848.html) |
| 事件 / 消息 | SuiteScript User Event 支持 afterSubmit，包含 web services 场景的触发上下文；可据此实施推送/队列。未核验一个覆盖所有记录且保证送达的通用原生 webhook 服务，需设计重试和补拉。 [User Event best practices](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_N3361453.html) |
| SDK / CLI | 官方 SuiteCloud SDK / Node.js CLI 支持项目管理、validate、deploy；这是部署 SuiteScript/元数据的开发工具，不是任意生产单据 CRUD CLI。官方已停止 Java CLI 新功能/修复，优先 Node.js。 [SuiteCloud Node.js CLI](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_155931263126.html) [SuiteCloud SDK / Java CLI 状态](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1558730192.html) |
| 版本与授权边界 | Work Orders、Advanced Bill of Materials、WIP 等特性需按所用对象启用并具备权限。MCP 需 Server SuiteScript、OAuth2、Standard Tools 所需 REST Web Services 等；连接角色不能是 Administrator。SOAP 2025.2 为最后计划 WSDL，2028.2 停用是未来计划，并非今天已不可用。 [BOM / Advanced Bill of Materials 前置](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1517399759.html) [Work Order Completion / WIP](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N3701691.html) [MCP AI Connector Service 接入](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_4160616848.html) [SOAP 退役计划](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N3413913.html) |
| 官方 MCP 状态 | 官方 AI Connector Service 是远程 MCP，Streamable HTTP、OAuth2 Authorization Code + PKCE。Standard Tools SuiteApp 提供 create/get/update 等记录工具及 SuiteQL/报告，按用户角色和 REST record 支持范围授权；不是默认全库写权限。已查到产品技术接入文档和工具清单，不是社区示例。 [MCP AI Connector Service 接入](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_4160616848.html) [Standard Tools SuiteApp](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_143403258.html) |

**建议接法（本研究判断）：** 用 REST + external IDs / 变换动作承接订单与生产工单；复杂制造记录先做 sandbox。MCP 用 Standard Tools 精选角色，批量同步用 REST。SuiteScript 负责可补偿的变更通知/扩展，避免把原始数据库查询当业务提交。

## 8. Infor CloudSuite / ION（M3、CSI 分别核验）（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | M3 已核验 PMS100MI 查询生产订单/材料/工序，MMS200MI/GetItmWhsBal 查库存；PMS050MI/RptReceipt、PMS060MI/RptIssue、PMS070MI/RptOperation 写入收料、发料、报工。BOM 读取有 PDS001MI/PDS002MI；旧 15.1.4 文档列 PDS001MI/Add。CSI 9.00 的官方 ION 指南列 ProcessSalesOrder、ProcessBillofMaterials、ProcessProductionOrder 等入站 BOD，但不能把这个旧版契约直接等同当前 M3/LN/CSI 全系列。 [M3 生产收发料和报工 APIs](https://docs.infor.com/m3udi/latest/en-us/m3beud/expdeshs/ujy1757047689416.html) [M3 生产订单和库存接口](https://docs.infor.com/m3udi/16.x/en-us/m3beud/expdeshs/nze1679556743952.html) [M3 产品结构读取](https://docs.infor.com/m3udi/16.x/en-us/m3beud/scexechs/jxa1760983766975.html) [M3 15.1.4 PDS001MI/Add 边界](https://docs.infor.com/m3be/15.1.4/en-us/m3bern/kgg1580999438832.html) [CSI 9.00 ION BOD 配置指南（旧版证据）](https://docs.infor.com/csi/9.00.x/en-us/useradminlist/csi_Configuration%20Guide%20for%20Infor%20ION_90030_42967.pdf) |
| 认证与身份 | ION API Gateway 使用 OAuth2 Authorized Apps，.ionapi 含客户端和网关配置信息；ERP 内层还需相应业务权限。不能在 Web 前端保存 .ionapi secret。 [Infor API Gateway 管理指南](https://docs.infor.com/inforos/2025.x/en-us/useradminlib_cloud/apigatewayag_cloud/ionapi_2025.x_apigatewayag_cloud_en-us.pdf) [M3 OAuth authorized app 配置](https://docs.infor.com/m3pwb/2025.x/en-us/m3pwbolh/pages/1091_help.html) |
| 事件 / 消息 | ION 可使用 BOD 文档流；Process/Sync 等动词有入站/出站语义。要按产品 BOD 清单确认方向与版本，并用消息标识做重放去重，不能简单视为同一个 REST webhook。 [CSI 9.00 ION BOD 配置指南（旧版证据）](https://docs.infor.com/csi/9.00.x/en-us/useradminlist/csi_Configuration%20Guide%20for%20Infor%20ION_90030_42967.pdf) |
| SDK / CLI | API Gateway 提供接口说明/交互式契约，M3 采用 MI 交易接口。本次未核验覆盖 CloudSuite 家族的统一官方 SDK/业务 CLI；应从所选 ERP 的 API 契约生成客户端。 [Infor API Gateway 管理指南](https://docs.infor.com/inforos/2025.x/en-us/useradminlib_cloud/apigatewayag_cloud/ionapi_2025.x_apigatewayag_cloud_en-us.pdf) |
| 版本与授权边界 | CloudSuite 是产品家族，M3、LN、CSI/工业版等对象与交易名不同；需 API Gateway authorized app、ERP 业务功能和具体 API transaction 权限。此行 A 仅表示已有 M3 等具体技术契约；并不表示每个 CloudSuite 已完成同等覆盖。 [M3 生产收发料和报工 APIs](https://docs.infor.com/m3udi/latest/en-us/m3beud/expdeshs/ujy1757047689416.html) [Infor API Gateway 管理指南](https://docs.infor.com/inforos/2025.x/en-us/useradminlib_cloud/apigatewayag_cloud/ionapi_2025.x_apigatewayag_cloud_en-us.pdf) [M3 OAuth authorized app 配置](https://docs.infor.com/m3pwb/2025.x/en-us/m3pwbolh/pages/1091_help.html) |
| 官方 MCP 状态 | Infor OS 2026 官方文档已有 API Gateway 中 MCP 类型端点、工具和 supported CloudSuite 配置。2026-04 的官方 Agentic Orchestrator 发布说明称相关增强 limited availability；截至本次文档未能证明所有 CloudSuite 都 GA 对外开放。未来 SCP 2026.10 文档不作为 2026-09-04 已上线证据。 [Infor OS 2026 MCP 配置](https://docs.infor.com/inforos/2026.x/en-us/useradminlib_cloud/genaiug/ssm1759825468545.html) [2026-04 Agentic Orchestrator / limited availability](https://www.infor.com/en-ca/blog/infor-agentic-orchestrator-ai-value-drivers) |

**建议接法（本研究判断）：** 先由客户确认 M3/CSI/LN 和准确版本，再以 MI 或 BOD 接订单/BOM/生产事件；不要实现一个叫 Infor 的万能字段映射。MCP 接入列为需租户开通核实项。

## 9. Epicor Kinetic（证据 B）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 官方 Open REST 页面明确支持 Kinetic business objects、processes、reports、BAQ、Functions 的读取/修改/业务逻辑执行。但本次公开访问的 v2 技术指南跳转 EpicWeb 登录，未取得订单/BOM/Job/库存/Labor 各对象的完整方法契约；因此不能写成这五类已逐一完成端点核验，也不凭记忆填写 service 名称。 [Kinetic Open REST 能力、API key、scope](https://www.epicor.com/en-us/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/open-rest-api/) [REST Services v2 指南（本次跳转登录）](https://epicweb.epicor.com/doc/Docs/Epicor10_RESTServices_v2_102700.pdf) |
| 认证与身份 | 官方 REST 能力页确认 API keys、access scopes 和标准身份验证叠加 ERP 权限；开发框架说明包含 Epicor Token / Azure AD / Epicor IdP。具体站点采用何种 OAuth/token 流程仍需租户配置。 [Kinetic Open REST 能力、API key、scope](https://www.epicor.com/en-us/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/open-rest-api/) [Kinetic 开发框架认证说明](https://kinetic.developer.epicor.com/framework/assets/Kinetic-Engagement-Deck.pdf) |
| 事件 / 消息 | BPM、应用事件或 REST 可调用 Epicor Functions；官方 Cloud Platform 还描述 Data Fabric 事件数据能力。未核验全部业务对象通用 webhook 的投递保证与负载契约。 [Functions / BPM / 业务事件调用](https://www.epicor.com/en/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/epicor-functions/) [Cloud SDK / Data Fabric / Service Designer](https://www.epicor.com/zh-hant-tw/products/enterprise-resource-planning-erp/epicor-kinetic/cloud-business-platform/) |
| SDK / CLI | 官方 Cloud SDK / Service Designer 和 Functions 支持扩展服务；公开技术资源不等于一个通用单据 CLI，需使用租户契约生成客户端。 [Cloud SDK / Data Fabric / Service Designer](https://www.epicor.com/zh-hant-tw/products/enterprise-resource-planning-erp/epicor-kinetic/cloud-business-platform/) |
| 版本与授权边界 | 部署版本、REST v2 配置、API key、access scopes 与 ERP 角色共同限制访问。详细 API 文档可能需客户/伙伴 EpicWeb 登录或租户 REST Help。SDK/集成产品的商业授权以客户合同核实，不从宣传页推定免费。 [Kinetic Open REST 能力、API key、scope](https://www.epicor.com/en-us/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/open-rest-api/) [REST Services v2 指南（本次跳转登录）](https://epicweb.epicor.com/doc/Docs/Epicor10_RESTServices_v2_102700.pdf) [Cloud SDK / Data Fabric / Service Designer](https://www.epicor.com/zh-hant-tw/products/enterprise-resource-planning-erp/epicor-kinetic/cloud-business-platform/) |
| 官方 MCP 状态 | 2026-05 官方 Agentic AI Stack / Prism Agent Foundry 新闻提到 MCP 互操作，但本次未核验公开服务器端点、认证流程、工具清单和每个 Kinetic 版本 GA 边界。归类为官方方向/能力说明，不能冒充可立即接入的已验证 MCP 服务。 [2026-05 Agentic AI Stack 官方发布](https://www.epicor.com/en-us/newsroom/news-releases/epicor-introduces-agentic-ai-stack/) |

**建议接法（本研究判断）：** 取得客户租户 REST Help / Swagger 导出，逐一验证订单、BOM、工单、库存、工时报工 BO 的方法与业务校验，再决定适配范围。当前仅建立候选连接器，不显示“已连通”。

## 10. IFS Cloud（证据 A）

| 核验项 | 结论与直接证据 |
|---|---|
| 订单 / BOM / 工单 / 库存 / 报工 | 官方 MES 集成说明确认 ManufacturingPartService/InventoryPartService 读取制造主数据、BOM/路线版本。ShopFloorConnector 可启动准备/生产、记录停机/时间/数量、将 Shop Order 收入库存；ScheduleConnector 报数量/废品。Shop Floor Information 契约读取工单/工序/材料，部分 POST 实际只读。销售订单 CRUD 和 BOM 写入未在本次逐对象核验，不应由平台 OData 能力直接推断。 [IFS Manufacturing Execution System Integration](https://docs.ifs.com/ifsclouddocs/25r2/Manufacturing/AboutManufacturingExecutionSystemIntegration.htm) [Shop floor information 方法契约](https://docs.ifs.com/techdocs/25R2/040_tailoring/300_extensibility/060_use_cases_across_industries/010_mes/040_shop_floor_connector/011_get_shop_floor_information/) |
| 认证与身份 | API Explorer 默认 OAuth2；服务调用服从 permission set / projection / action 与数据授权。避免因看到 OData endpoint 就赋予整个 projection 全写权限。 [API Explorer 默认 OAuth2](https://docs.ifs.com/techdocs/24r2/040_tailoring/300_extensibility/020_api_explorer/010_navigate/) [Projection permission sets](https://docs.ifs.com/techdocs/24r2/030_administration/010_security/020_permission_sets/004_permission_set_overview/010_projections/) |
| 事件 / 消息 | 官方 MES 场景通过 IFS Connect 路由 outbound 消息，例如工位配置允许的机器开始/停止；具体事件按场景启用，不能默认向KANPACE开放设备控制。 [IFS Manufacturing Execution System Integration](https://docs.ifs.com/ifsclouddocs/25r2/Manufacturing/AboutManufacturingExecutionSystemIntegration.htm) [IFS API Usage Policy](https://docs.ifs.com/policy/APIUsageCloud.pdf) |
| SDK / CLI | API Explorer 提供当前租户 OpenAPI 2/3（$openapi）和交互式文档，可生成 HTTP 客户端。未核验一个覆盖全部制造业务的独立 SDK/CLI。 [API Explorer / OpenAPI](https://docs.ifs.com/techdocs/25r2/040_tailoring/300_extensibility/020_api_explorer/) |
| 版本与授权边界 | 按实际 25R1/25R2/26R1 租户 projection 及 permission sets 取契约；部分 projection 天生只读，写入需 action/entity 权限。Premium API 是官方接口分类名称，本次没有足够商业证据断定其必然单独收费。 [API Explorer / OpenAPI](https://docs.ifs.com/techdocs/25r2/040_tailoring/300_extensibility/020_api_explorer/) [Projection permission sets](https://docs.ifs.com/techdocs/24r2/030_administration/010_security/020_permission_sets/004_permission_set_overview/010_projections/) [Premium API 技术分类](https://docs.ifs.com/techdocs/26r1/040_tailoring/300_extensibility/020_api_explorer/030_premium_apis/) |
| 官方 MCP 状态 | 本次官方开发文档未确认 IFS Cloud 独立对外 MCP server 的端点/认证/工具目录。社区或第三方 IFS MCP 不等于官方产品；未查到不代表没有接口，可基于已公开 OData/OpenAPI 自建受控工具。 [API Explorer / OpenAPI](https://docs.ifs.com/techdocs/25r2/040_tailoring/300_extensibility/020_api_explorer/) [IFS API Usage Policy](https://docs.ifs.com/policy/APIUsageCloud.pdf) |

**建议接法（本研究判断）：** 优先以 ShopFloorConnector 对接工序开始、工时、数量和完工收货；先读取并锁定 BOM/路线 revision，外部任务映射至 shop order/operation。销售订单/BOM 写入另开契约核验任务。

## 对KANPACE适配层的直接约束（研究判断）

1. 保留“外部产品 + 部署/版本 + 公司/工厂 + 对象类型 + 外部 ID + revision + 操作权限”的能力记录，界面只开放当前连接器已经核验且已授权的动作。没有生产 BOM API 的标准套件不能伪装为全自动拆单回写。
2. 分清接收、业务校验、单据创建、释放、物料过账、报工、结单。HTTP 2xx、队列 accepted 或硬件 ACK 都不能合并为“任务完成”；SAP 独立物料过账、Dynamics MES 队列和 Oracle 库存暂存都需要后续状态核验。
3. 下发工种任务应来自已审核工程 BOM / 工艺路由，回传必须带工单/工序/版本、人员、数量、工时、报废/返工、原始事件 ID；外部系统不可改写字段须在适配层显式拒绝。
4. Web 应使用本地后端保管 OAuth/证书/API key，前端只调用KANPACE受控业务 API。为每个 ERP 连接设置只读测试、沙箱写入、生产动作授权、幂等、限流、审计和补偿。此为实施建议，不是对所有厂家文档的共同功能声明。
5. SDK/CLI 用于部署或生成客户端；MCP 用于让 agent 调用已定义业务动作。确定性批量同步不必绕一层大模型；工程识别不确定项先留证据/待确认，再形成正式 ERP/MES 操作。

机器可读文件：`work/integration-global.json`。字段含 id/name/category/interfaces/objects/access/mcp/evidence/next/sources，另保留 auth/events/sdk 便于 Web 展示明细。
