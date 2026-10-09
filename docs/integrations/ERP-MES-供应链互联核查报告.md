# ERP、MES 与供应链系统互联核查报告

核查日期：2026-09-04。已覆盖 35 个产品线/平台条目，包含国内 ERP、国际 ERP、MES、PDM、WMS/供应链及协同工具。各行按产品与版本解释；例如浪潮条目中分别说明 GS Cloud/inSuite，不能将平台条目数当作独立厂商数。范围为主流代表性覆盖，不声称穷尽所有厂商或完成每个对象的现场联调。

**结论：以官方业务 API/事件和客户既有集成平台为基础，为KANPACE建立按产品版本适配的连接器是可行方向。** 客户保留原订单、审批、库存、财务和已有 MES；KANPACE补充展示柜图纸来源、构件与工艺拆分、工种任务和硬件触达。CLI/MCP 是使用接口的方式，不能替代真实业务字段映射与权限。

本报告没有使用客户账号，没有安装这些厂商插件，也没有向任何 ERP/MES 写单。厂商有接口≠当前KANPACE已实现连接器。A 表示存在公开技术契约/官方源码或端点资料，B 表示有官方能力说明但对象契约不完整，C 表示本次证据不足。评级不是产品排名；未核验不是没有。

## 优先级建议（基于本项目需求的判断）

1. **先服务已有客户入口**：以客户真实使用的产品/版本及授权为第一优先级，不要求换 ERP/MES。没有客户版本资料时，文件导入导出先行；用 ERPNext 测试标准模型。
2. **国内首批候选**：金蝶云星空、用友 U8，以及对象级接口较明确的畅捷通 T+；最终选择有可用测试环境的一家。黑湖小工单先核对自己的 OPENAPI 合同与文档，不能借用智造接口。
3. **工程设计入口**：客户有 SOLIDWORKS PDM Professional 时，读取已发布版本、BOM与变更事件；无 PDM 则沿用已有文件导出。
4. **保留协作习惯**：飞书/宜搭做订单入口、审批与进度显示，生产数量和版本仍由指定系统校验。
5. **海外与集团客户**：按已购 SAP、Dynamics、Oracle、Infor、Epicor、IFS 等平台的接口和中间件做专项适配；WMS/SCM 重点接库存、出库与交付，不承诺其承担拆单。

## 技术入口与业务能力的区别

| 方式 | 用途 | 核验重点 |
|---|---|---|
| REST / OData / SOAP / GraphQL | 业务读取、写入与动作 | 对象、动作、版本、权限及调用限制 |
| Webhook / 业务事件 | 数据变更通知 | 事件范围、签名、重试、顺序及补漏 |
| SDK | 官方语言接口与模型 | 产品版本、可用业务方法、运行环境 |
| CLI | 脚本、开发或运维 | 是否真能做业务动作，不能把管理员运维命令当报工API |
| MCP | 助手发现并调用工具 | 原厂或第三方、GA/Beta/示例、读写权限、工具范围 |
| CSV / XML / Excel | 遗留系统和受控批量交换 | 模板、主键、套数单位、错误行和审核过程 |
| MQTT / OPC UA | 消息与工业互操作 | 主题/节点及业务语义；不是ERP接口权限的替代 |

## 总矩阵

点选与过滤请打开同包 `static/integrations/index.html`；完整 CSV、JSON 在本目录，均包含官方原文链接。

### 金蝶云星空（K3 Cloud）

- 类别：国内ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：WebAPI；官方 .NET/Java/Python SDK；事件回调需按版本核验。
- 业务对象：已核验通用单据查询、查看、保存、修改、提交、审核、删除、下推等 WebAPI 操作。订单、BOM、生产订单、库存、生产汇报应分别核对客户环境表单及开放权限；本轮未逐一验证这些制造对象的字段契约，不能把通用保存等同于任意单据可写。
- 版本/授权：需管理员配置第三方系统登录授权与允许调用用户。官方 2020 年 SDK 指南标注新 SDK 需 PT136657 [7.3.1310.2] 或更高；这是该指南的历史版本门槛，不代表所有当前部署的统一最低要求。实际版本、补丁、模块及采购许可须核实。
- MCP/CLI：本轮未核验星空各版本可直接使用的官方 MCP 服务；苍穹的官方 MCP 能力不能自动套用到星空客户实例。
- 建议接法：P0 候选：先读销售订单、物料与库存，再按现场表单映射提交已复核 BOM/生产单草稿；保存、提交、审核分开控制，回查结果后再记同步成功。

官方证据：[金蝶云星空 WebAPI 知识专题](https://vip.kingdee.com/knowledge/specialDetail/650386937144032256?category=650387024452664320&id=650357430634787328&lang=zh-CN&productLineId=1)；[金蝶云星空官方 OpenAPI SDK 接入指南](https://open.kingdee.com/K3Cloud/Open/ApiCenterReportDetail.aspx)；[金蝶云星空生产订单帮助](https://help.open.kingdee.com/dokuwiki/doku.php?id=%E7%94%9F%E4%BA%A7%E8%AE%A2%E5%8D%95)。

### 金蝶星辰（精斗云开放平台）

- 类别：国内ERP；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：官方开放 API 平台；版本化 API 文档入口；文件导入（部分基础资料）。
- 业务对象：已确认星辰生产产品包含 BOM、生产任务、领退料与成品入库；这些是产品业务能力。开放平台页面为动态页面，本轮未取得相应订单/BOM/工单/库存/报工接口的完整官方字段契约，因此不把这些对象标为已验证 API 读写。官方入门材料可证明部分基础资料/期初数据批量导入。
- 版本/授权：先确认星辰产品版本、已购生产模块、开放平台应用及账套授权；区分平台中的 API 版本，不能复用星空的登录 SDK、表单编号或接口地址。当前接口费用、配额、事件订阅适用范围需由平台账号/合同核验。
- MCP/CLI：本轮未核验星辰专属官方 MCP 服务。网上第三方封装、API 调用示例不算官方 MCP。
- 建议接法：P1 候选：适合小微展示柜厂的订单与进销存衔接；先在授权账号导出目标接口清单，再决定生产 BOM/报工是否通过 API 或经确认的导入模板进入系统。

官方证据：[精斗云官方开放平台](https://open.jdy.com/)；[金蝶星辰生产制造产品能力](https://www.jdy.com/domain/manufacture/)；[金蝶星辰产品模块与版本](https://www.jdy.com/buy/new_v7pro/)；[精斗云官方入门导入说明（历史材料）](https://cdn.jdy.com/tfapp/guide/v7_guide_list.pdf?v=2.0)。

### 金蝶苍穹（平台及其业务应用）

- 类别：国内ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OpenAPI / RESTful API；Java/脚本扩展；开放事件及回调；官方 MCP 能力；文件流 API。
- 业务对象：官方技术专题列出查询/保存/删除/提交/审核/下推、REST 资源读写、开放事件与回调契约。苍穹是平台；订单、BOM、库存、生产工单、报工取决于安装的业务应用与模型，不能把平台 API 能力等同于一套通用制造 ERP 对象契约。
- 版本/授权：需要第三方应用授权、身份认证及操作权限；API 1.0/2.0、V6/V7、开放事件灰度与密钥条件分别核验。标准业务服务、Agent/MCP、定制 API 的可用范围和商业授权需按客户租户确认。
- MCP/CLI：已核验官方开发文档包含 MCP 服务（for 灵基）与 MCP 常见问题；金蝶官网也宣布苍穹提供标准及自定义 MCP。具体服务地址、可调用工具、租户授权与最低版本仍需现场验证。
- 建议接法：P2 项目型：客户已有苍穹/星瀚应用时，通过授权业务 API 与开放事件集成；可将受控的查询和草稿操作供 Agent 调用，MCP 不替代业务权限与单据状态校验。

官方证据：[苍穹 OpenAPI、RESTful、开放事件及 MCP 官方技术专题](https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29)；[金蝶官方开发者门户](https://dev.kingdee.com/)；[金蝶苍穹官方产品页：MCP/A2A 与开放集成](https://www.kingdee.com/products/cosmic_platform.html)；[金蝶官网：苍穹支持 MCP（2025-04-18）](https://www.kingdee.com/article/1913102603487625217.html)。

### 用友 U8 / U8+ 开放平台

- 类别：国内ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OpenAPI（云＋客户端）；EAI / U8API；官方 Java/C# SDK。
- 业务对象：官方 API 目录已核验 BOM 单条/批量查询、现存量查询、材料出库与产成品入库的新增/查询/审核/弃审。销售领域 API 列于同一目录，但需按目标单据选取方法。BOM 写入、生产工单创建、工序报工的具体开放契约本轮未核验，不推定为支持。
- 版本/授权：BOM 批量查询接口明确 U8 V12.0 及以上；其他接口各自有版本要求。官方收费文档要求购买 OpenAPI 模块、获得企业授权，采用云＋客户端及数据源绑定。旧网页报价不应直接当成今天合同报价。
- MCP/CLI：本轮未核验 U8 官方 MCP 或独立业务 CLI；官方 SDK 与 EAI 不能视为 MCP。
- 建议接法：P0 候选：读取订单/BOM/库存作为KANPACE拆单输入；优先验证领料和产成品入库回传。工序报工保留在KANPACE，直到获得对应 U8 接口契约及权限。

官方证据：[用友 U8 官方 API 目录](https://u8open.yonyoucloud.com/apiCenter/index)；[U8 BOM 批量查询端点与版本限制](https://u8open.yonyoucloud.com/apiCenter/bom_batch_get)；[用友 U8 官方 SDK 与平台入口](https://u8open.yonyou.com/)；[用友 U8 OpenAPI 模块与授权收费说明](https://u8open.yonyou.com/documentCenter/apiPayment)。

### 用友 U9 cloud

- 类别：国内ERP；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：官方 OpenAPI 能力；PLM/MES 集成能力。
- 业务对象：用友官方发布材料确认标准产品轻量接口/OpenAPI，官方案例说明 BOM 与 PLM、制造执行的数据衔接。订单/BOM/生产工单/库存/报工各对象可读可写的方法、字段与动作，本轮未取得可公开访问且归属可确认的完整技术契约。
- 版本/授权：企业版/标准版、版本补丁、已购模块、定制扩展及部署地址必须核验。U9 cloud 的接口不能用 U8 OpenAPI 或 YonBIP 的 Token/字段替代；开放范围以客户环境的接口目录及厂商授权为准。
- MCP/CLI：本轮未核验 U9 cloud 官方 MCP/CLI。产品宣传中的 AI Agent 或生态对接不直接证明存在可接入的 MCP 服务。
- 建议接法：P2 项目型：先从客户 U9 cloud 环境取得 OpenAPI 清单，验证物料/BOM/工艺路线与生产单关系，再实施KANPACE对接；不要直接写业务数据库。

官方证据：[用友 U9 cloud 官方产品门户](https://u9cloud.yonyou.com/)；[U9 cloud 官方 OpenAPI 能力说明](https://u9cloud.yonyou.com/news/detailes/news/157.html)；[U9 cloud 官方 PLM 与 BOM 集成说明](https://u9cloud.yonyou.com/news/detailes/news/526)。

### 用友 BIP / YonBIP（iuap 开放平台）

- 类别：国内ERP；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：官方 OpenAPI 平台；API 调试与频控治理。
- 业务对象：官方门户可核验 OpenAPI、API 调试助手与销售订单部分接口限流公告，能确认销售订单 API 存在。因文档正文动态加载，本轮未完整核验 BOM/工单/库存/报工各对象方法、写入动作和事件主题；不能据此承诺所有制造对象双向同步。
- 版本/授权：确认 BIP 产品/版本、租户及数据中心、企业应用授权和业务模块；门户公告表明 API 存在独立频控调整。U8、U9、BIP/YonSuite 等产品身份、地址与数据模型不应合并为一个通用适配器。
- MCP/CLI：本轮未核验面向目标制造业务对象的官方 MCP/CLI；应另取官方服务地址与授权文档，不能以第三方 MCP 项目替代。
- 建议接法：P2 项目型：让客户管理员提供租户授权和制造领域 API 文档，从订单/主数据读取建立最小闭环，再验证生产与库存写入、频控和回查。

官方证据：[用友 iuap / YonBIP 官方开放平台及公告](https://open.yonyoucloud.com/)；[用友 BIP 官方 API 文档入口](https://open.diwork.com/#/doc-center/docDes/api?code=yonbip)。

### 畅捷通 T+ / T+Cloud

- 类别：国内ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OpenAPI；消息订阅/回调；异步单据创建；官方机器可读 API 文档。
- 业务对象：已核验 BOM 创建/查询/审核/删除/更新，生产加工单创建/查询/修改等，工序汇报单新增/查询/审核/删除；官方目录另列销售订单、现存量、领料和产成品入库。新增工序汇报契约含外部唯一单号、来源加工单/派工单、工序、人员、产量与合格量，适合工种任务回传。
- 版本/授权：总体对接支持 T+13.0 以上，但接口逐项按补丁发布：生产加工单创建要求所列 16.0.0129+；工序汇报要求所列 17.0.0010+；BOM 更新要求 T+Cloud 自 2024-10-30 或专属云 19.0.0186+。消息订阅要求 16.0+及补丁，排障说明标 >16.000.000.0209。需应用配置、账套授权及 Token。
- MCP/CLI：本轮未核验官方 MCP 服务；官方 llms.txt/Markdown 契约方便 Agent 阅读，但文档格式不是 MCP 协议端点。
- 建议接法：P0 候选：最适合验证订单/BOM→加工单→工序派工→真实报工闭环。以 ExternalCode 做跨系统关联，按工种映射车间/工序/班组，订阅增量事件并定期对账。

官方证据：[T+ 官方 OpenAPI 对接指南与版本要求](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/tplusguide)；[T+ BOM API 与逐接口版本](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+jcda/tcbom)；[T+ 生产加工单 API](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+dj/t+scjgd)；[T+ 工序汇报新增：字段与权限头](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+dj/t+gxhbd?id=32274)；[T+ 消息订阅与补丁要求](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/t+msgsub)；[T+ 全业务 API 目录](https://open.chanjet.com/docs/file/apiFile/tcloud)。

### 鼎捷 T100（含相关平台集成）

- 类别：国内ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：T100 OpenAPI；XML 契约/签名与分页；设备平台 API 对接能力。
- 业务对象：官方 T100 技术 PDF 已核验销售订单列表查询 t100.oapi.sales.order.list.data.query.get；库存应用指南给出入库新增→确认→过账的 API 流程。官方设备平台另说明工单抓取与报工回传能力，但这不是 T100 某版本 BOM/工序报工的具体端点证明。
- 版本/授权：文档路径区分 T100 v1/v3、语言和接口版本，需核对客户产品版本、企业/营运据点、服务授权与认证配置。T100、E10、E10 Cloud、雅典娜是不同产品/平台，不能统一套用此 PDF 的 XML 接口。
- MCP/CLI：本轮未核验目标 T100 业务对象的官方 MCP/业务 CLI；不要把雅典娜或 AI 产品宣传等同于已开放标准 MCP。
- 建议接法：P2 项目型：先用销售单增量查询接单，按其库存单据状态执行入库回传；BOM与工序报工须客户提供当前版本契约后再扩展。

官方证据：[鼎捷 T100 v3 销售订单查询官方 API PDF](https://dw-t-devops.digiwin.com/ssupkm/t100v3/zh_TW/API/file/wssp00003TW02_s.pdf)；[鼎捷 T100 库存管理 OpenAPI 应用指南](https://dw-t-devops.digiwin.com/ssupkm/t100v1/zh_CN/accessguide/file/TIPTOP/OpenAPI%E6%87%89%E7%94%A8%E5%A0%B4%E6%99%AF%E8%AA%AA%E6%98%8E_%E5%BA%AB%E5%AD%98%E7%AE%A1%E7%90%86.pdf)；[鼎捷设备平台：工单抓取与报工 API 集成](https://www.digiwin.com/software/DeviceCloud/AIoT_eq)。

### 浪潮海岳 GS Cloud / inSuite（分别核验）

- 类别：国内ERP；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：iGIX 开放集成/API 治理能力；开发平台 API 与事件模型。
- 业务对象：官方产品页可核验 GS Cloud、inSuite 与 iGIX 的不同定位；制造产品具有 BOM、工艺、计划等业务能力，iGIX 提供 API 集成/治理。尚未公开核验两款 ERP 各自的订单/BOM/工单/库存/报工读写契约。开发平台事件模型不等于这些业务对象已提供 Webhook。
- 版本/授权：须先区分 GS Cloud、inSuite 与 iGIX；确认客户部署、版本、授权模块、集成平台和二开服务范围。本轮未取得可据以计算费用/配额的官方现行接口授权表。
- MCP/CLI：本轮未核验目标海岳 ERP 业务对象的官方 MCP/CLI；开发平台和工业物联接入不能替代 ERP 开放接口证明。
- 建议接法：P2 项目型：在已有浪潮环境内取得目标业务 API/数据字典，先实现订单与物料只读同步；工单和报工写入按实施合同与测试环境逐项验收。

官方证据：[浪潮海岳官方产品体系](https://www.inspur.com/lcjtww/2532566/index.html)；[浪潮 iGIX 开放集成平台](https://www.inspur.com/eportal/ui?pageId=2609848)；[浪潮 inBuilder 开发平台](https://www.inspur.com/lcjtww/2315499/2318933/2743133/index.html)。

### 黑湖小工单（单独产品）

- 类别：国内MES；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：OPENAPI 存在的官方协议证据；按客户要求开放接口（范围待核验）。
- 业务对象：官方用户协议明确提及通过 OPENAPI 接入的数据和按要求开放相应接口，可确认有接口接入情形。订单、BOM、工单、库存、报工逐对象读取/创建/更新、事件回调及字段范围，本轮未取得小工单自身的公开官方技术契约。不能用黑湖智造 3.0 的 OAuth/API 文档证明小工单拥有同样接口。
- 版本/授权：具体服务按小工单合同及附件；新核心功能/高级服务可能独立采购。应取得小工单租户的接口开通清单、权限、费用/配额、测试环境。用户协议中的终止后通用格式数据返还不等于日常自动 CSV/Excel 同步。
- MCP/CLI：本轮未核验黑湖小工单官方 MCP、SDK 或业务 CLI；第三方连接器与黑湖智造 SDK 均不自动适用。
- 建议接法：P1 业务优先核验：用户特别关注该产品，应优先拿到小工单官方接口清单；随后验证下发工单、读取工序/人员、回传真实报工。没有契约前，只能评估经确认的文件交换或独立KANPACE流程。

官方证据：[黑湖小工单官方用户协议：OPENAPI、接口开放与服务范围](https://www.xiaogongdan.com/userAgreement)。

### 黑湖智造 3.0（不等于小工单）

- 类别：国内MES；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：官方 OpenAPI；OAuth2.0；频控与接入说明；官方机器可读文档索引。
- 业务对象：官方开发门户明确智造 3.0 的 API 调用、接入、频控、OAuth2.0，以及接口分类/ID 的机器可读索引。本轮该索引请求受站点访问限制，未完成订单/BOM/工单/库存/报工各对象字段和读写范围核验；因此只确认平台开放能力。
- 版本/授权：需确认客户使用的是智造 3.0、租户授权及 API 频控/服务范围；不同黑湖产品和旧版本不可共用鉴权假设。索引不可访问是本轮证据限制，不表示没有这些接口。
- MCP/CLI：本轮未核验官方 MCP 服务；机器可读 Markdown/API 索引不等于 MCP。官方 Java SDK 的适用产品/版本还需与智造 3.0 文档核对。
- 建议接法：P1 条件候选：有该版本客户时，从开放平台取得目标 API 契约再对接工单/报工；对象映射、事件与 OAuth 令牌更新须分别测试，不复用小工单连接配置。

官方证据：[黑湖智造 3.0 官方开放接口平台](https://v3-hw-openapi.blacklake.cn/document/api)。

### 摩尔元数 MES/MOM / MC 平台

- 类别：国内MES；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：MES/MOM 开发平台能力；设备数据集成（OPC 等）。
- 业务对象：官方产品/开发平台能证明 MES/MOM、公共数据与设备采集集成能力；设备平台的 OPC 等协议仅证明设备接入。订单、BOM、工单、库存、报工的外部业务 API 读写、事件回调及字段契约本轮未公开核验。
- 版本/授权：需确认具体产品、部署版本、开发平台账号、可交付源码范围及二开/接口授权。官网所称开放业务源码不能推定为开源许可证或免费 API。
- MCP/CLI：本轮未核验官方业务 MCP/CLI；开发套件及设备协议不是 MCP。
- 建议接法：P2 项目型：先向当前客户环境取得业务接口和开发授权；设备采集与KANPACE任务/报工 API 分层对接，避免把采集到的设备信号直接等同于完工。

官方证据：[摩尔元数官方公司与平台介绍](https://www.morewis.com/gsjs/)；[摩尔元数 MC 官方开发平台](https://mobile.morewiscloud.com/)；[摩尔元数设备数据采集平台](https://www.morewis.com/mdip.html)。

### 网上管家婆 NGP（补充进销存）

- 类别：进销存；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：NGP OpenAPI；ISV 注册与接口文档；ERP 端 Token 刷新。
- 业务对象：官方帮助中心的 NGP-API 接入流程明确开放平台、ISV 注册、API 文档查询与 Token 刷新。本轮未取得订单/库存具体端点契约；BOM/工单/报工更不能从进销存接入流程推定支持。
- 版本/授权：该证据仅适用网上管家婆 NGP；管家婆辉煌、财贸、工贸、毕方等产品需分别核验，不能共用接口/插件授权结论。现行接口收费、ERP 套餐和可读写范围应按平台账号及合同确认。
- MCP/CLI：本轮未核验 NGP 官方 MCP/SDK/业务 CLI。
- 建议接法：P1/P2 按现有客户决定：优先只接已确认的销售订单、商品、仓库与库存，制造拆单、工种任务和报工留在KANPACE；取得对应接口后再做单据回传。

官方证据：[网上管家婆官方 NGP-API 对接流程（2025-07-21）](https://helpnew.wsgjp.com/2488/8ef8/03c3b)；[网上管家婆 NGP 官方开放平台](https://ngpopen.wsgjp.com/#/)。

### SAP S/4HANA

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OData V2/V4；SOAP A2A；Business Events；SAP Cloud SDK。
- 业务对象：销售订单有 OData V4 创建接口；订单 BOM 有创建接口。API_PRODUCTION_ORDER_2_SRV 可读、创建、有限字段修改及释放/技术完成生产订单。API_PROD_ORDER_CONFIRMATION_2_SRV 可创建生产确认并带物料移动；不能把其 HTTP 成功视为全部物料过账成功，物料凭证失败可能进入 COGI。这里验证的是订单 BOM，不能自动等同所有物料 BOM 变更场景。
- 版本/授权：Public Cloud、Private Edition、本地部署的版本、通信场景和允许操作不同；须启用匹配的 communication arrangement 并授予业务权限。不能把 Public Cloud 2608 文档套用到旧本地版本。Integration Suite / Integration Cell 的可用性另受服务计划约束。
- MCP/CLI：官方 Integration Suite 已有 MCP artifact 技术文档，可从已部署 API、HTTP/OpenAPI 或 RFC 后端构造选定工具；这是需配置和部署的集成层，不等于 S/4HANA 所有业务对象开箱写入。ABAP MCP 用于开发代码，不等于业务单据 MCP。当前查到可用技术文档，不推定每个租户都已开通。
- 建议接法：以确定性 API 接订单、物料和生产订单；KANPACE保存图纸版本/来源及外部单据号，报工拆为生产确认与物料过账结果两段核验。MCP 只包装已审核的查询与业务动作。

官方证据：[销售订单创建 OData V4](https://help.sap.com/docs/SAP_S4HANA_CLOUD/03c04db2a7434731b7fe21dca77440da/9c75cb47849149ca8a5c644c98965ff1.html)；[订单 BOM 创建](https://help.sap.com/docs/SAP_S4HANA_CLOUD/7489fa08cede494cbdf08fa3651598af/339b6cbbd3a54cf1b739f1707ce88de4.html?locale=en-US&state=PRODUCTION&version=2608.500)；[Production Order V2](https://help.sap.com/docs/SAP_S4HANA_CLOUD/d35113ee62644d3abee1aaec148291d9/0a4262096d2e43258df27c594bdd1468.html)；[生产确认和独立物料过账结果](https://help.sap.com/docs/SAP_S4HANA_CLOUD/d35113ee62644d3abee1aaec148291d9/728de485cfc843f9a76f661b1fcbd5a5.html)；[S/4HANA Cloud 连接和认证配置](https://help.sap.com/docs/integration-suite/sap-integration-suite/sap-s-4hana-cloud)；[企业事件配置示例](https://help.sap.com/docs/CX_NG_SVC/56436b4e8fa84dc8b4408c7795a012c4/15bb1e4a86894969b26656ed857334fc.html)；[SAP Cloud SDK OData generator](https://sap.github.io/cloud-sdk/docs/js/features/odata/generate-client)；[Integration Suite MCP artifact](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/how-model-context-protocol-mcp-enables-ai-integration-with-apis?locale=en-US&state=PRODUCTION&version=CLOUD)；[ABAP agentic development / MCP](https://news.sap.com/2026/08/with-agentic-ai-abap-takes-evolution-to-the-next-level/)。

### SAP Business One

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：Service Layer OData V3/V4；DI API；Webhooks（FP2602+）。
- 业务对象：Service Layer API Reference 明列 Orders、ProductTrees（BOM）、ProductionOrders 的 GET/POST/PATCH；InventoryGenEntries 和 InventoryGenExits 支持生产收料/发料等库存单据。生产收发料和工单状态可对接，但本次未核验等同 MES 的逐人逐工序工时报工模型。
- 版本/授权：优先 OData V4 /b1s/v2；V3 /b1s/v1 为兼容路径，旧 WCF/V3 技术自 FP2108 起弃用。SQL Server 与 HANA 部署须按各自版本配置 Service Layer，不能再笼统称 HANA 专属。FP2602 webhook、FP2608 MCP 示例仅适用于对应更新级别。
- MCP/CLI：官方 10.0 FP2608 发布 MCP Sample Code 及辅助 annotated metadata。状态是官方示例代码；不能当成熟托管 MCP 服务、承诺 GA SLA 或默认全业务写权限；metadata 文档也提醒响应可能变化。
- 建议接法：适合首批中小型展示柜 ERP 适配：订单→KANPACE工程 BOM/工艺审阅→ProductTrees/ProductionOrders；发料/完工入库保留 external_id 幂等。老版本先增量拉取，新版本评估 webhook。

官方证据：[Service Layer API Reference（含各实体操作）](https://help.sap.com/doc/056f69366b5345a386bb8149f1700c19/10.0/en-US/Service%20Layer%20API%20Reference.html)；[OData 协议版本](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/60c7a0b745bd486589f05a1da77041f3.html)；[旧 WCF/OData V3 弃用说明](https://help.sap.com/docs/SAP_BUSINESS_ONE/e83fb6dd8db7421486e0a2bb4e326720/61e0cdf417ac4baa9fdf6296733b9145.html)；[SQL Server Service Layer 安装边界](https://help.sap.com/docs/SAP_BUSINESS_ONE_ADMIN_GUIDE_SQL/f6fb230cc90949d8b66586a39189992b/9b01e69e7c714025a46fa7ad22e28f62.html)；[传统 Login/会话技术说明（9.3）](https://help.sap.com/doc/0d2533ad95ba4ad7a702e83570a21c32/9.3/en-US/Working_with_SAP_Business_One_Service_Layer.pdf)；[Business One Cloud OAuth/IAM](https://help.sap.com/docs/SAP_BUSINESS_ONE_CLOUD/c3a2e34ed796424a8817ad872bff4a79/986dc0a7bd164d69846e8a0054fe610a.html)；[FP2602 Webhooks 发布说明](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/c61c54be65b74486b8bed0ab7feab6a7.html)；[Webhook 订阅 API](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/ea37739cf17f44f6bd36c2e9f7a296ff.html)；[Service Layer / DI API 架构](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/36a5b88dce7d4d3b8c1abf1ac4e9dd2d.html?locale=en-US)；[FP2608 官方 MCP Sample Code](https://help.sap.com/docs/SAP_BUSINESS_ONE_WEB_CLIENT/e6ac71d18c7543828bd4463f77d67ff7/286fda530e5249bc90e2fa51fd3c10db.html?locale=en-US)；[MCP annotated metadata 的稳定性边界](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/bc9463949d4f4239a25792aa98633520.html?locale=en-US)。

### SAP Digital Manufacturing

- 类别：国际MES；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST APIs；OAuth2 service key；Cloud/Edge APIs；生产过程事件。
- 业务对象：官方 Edge 支持清单确认 GET /bom/v1/boms、/order/v1/orders、/material/v1/materials、/inventory/v1/batches 等读取。2608 更新列明 Order V2 release、BOM 组件 customValues 更新，以及 Edge SFC start/complete/scrap、quantityConfirmation/confirm。Inventory V2 可查收发料并 POST EWM goods receipt；这不等于在 DM 中建立 ERP 销售订单。
- 版本/授权：必须有相应 DM 服务实例/权限及 integration service key；Cloud 与 Edge 支持集不同。2608 新增 Edge 能力不可套到旧 Edge。EWM 收货依赖对应集成配置，不能与 SFC complete 的自动收货重复使用。
- MCP/CLI：本次未在官方产品文档核验 DM 独立对外 MCP server。可利用 SAP Integration Suite 的官方 OpenAPI→MCP 能力构建适配，但这是实施工作；社区自建 DM MCP 不能标为官方产品。
- 建议接法：以 ERP 保留销售订单，KANPACE承接图纸与工种任务，DM 作为执行主系统时映射 SFC/operation；明确由哪一侧触发完工收货，防止双写库存。

官方证据：[API 集成准备 / 服务密钥](https://help.sap.com/docs/sap-digital-manufacturing/operations-guide/prepare-for-api-integration?ai=true)；[Edge 可用 API 清单](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/b17dfa5bc22743ffba66facce41ed510.html)；[2608 APIs 更新](https://help.sap.com/docs/sap-digital-manufacturing/aa23dac9b58b48c6abda61fc704fb180/d466f10f1cf34c10828689e35e73db80.html)；[Inventory V2 / EWM 收货限制](https://help.sap.com/docs/sap-digital-manufacturing/apis/inventory-v2)；[SAP Cloud SDK OpenAPI generator](https://sap.github.io/cloud-sdk/docs/js/features/openapi/generate-client)；[Integration Suite MCP 集成能力](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/how-model-context-protocol-mcp-enables-ai-integration-with-apis?locale=en-US&state=PRODUCTION&version=CLOUD)。

### Microsoft Dynamics 365 Business Central

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST API V2.0 / OData；AL custom API；Webhooks；官方 MCP（Online）。
- 业务对象：标准 salesOrder API 提供读写及 shipAndInvoice bound action；item 提供物料读写及库存数量读取。不能直接 PATCH item.inventory 当库存过账。此次没有核验生产 BOM、生产工单、消耗/产出报工全部都存在标准 v2.0 API；需要导出租户 metadata 并用 AL API pages/actions 补齐。
- 版本/授权：生产制造功能受 Premium 体验/许可证约束；S2S 支持版本、Online/On-premises 配置不同。官方 MCP 当前只适用 Business Central Online。没有 API 页面或没有实体写权限的对象，不会因接上 MCP 自动变得可写。
- MCP/CLI：官方 MCP 端点 https://mcp.businesscentral.dynamics.com；默认只读，管理员需逐 API 开启 create/modify/delete/bound actions。OAuth2 Authorization Code + PKCE / Entra delegated identity。当前已有正式配置技术文档，未以某份预览计划推断所有客户可用或默认可写。
- 建议接法：先接销售订单、物料与库存读取；用 AL 扩展明确发布展示柜 BOM/生产工单/报工动作，再把选定 API 暴露给 MCP。制造扩展和 Premium 授权作为实施前置条件。

官方证据：[Sales order API / shipAndInvoice](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_salesorder)；[Item API](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_item)；[AL custom API 开发](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api)；[Premium 制造体验](https://learn.microsoft.com/en-us/dynamics365/business-central/ui-experiences)；[S2S OAuth 和权限](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/administration/automation-apis-using-s2s-authentication)；[Webhook subscriptions](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/dynamics-subscriptions)；[官方 MCP / 默认只读 / Online 边界](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview)。

### Microsoft Dynamics 365 Supply Chain Management

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OData data entities；Data Management package REST；MES message API；Business Events；官方动态 ERP MCP。
- 业务对象：SalesOrderHeadersV2 支持导入/更新订单头，订单行独立实体，更新要求订单处于开放状态。官方 MES 集成明确支持生产订单 start、report finished、material consumption、operation time、end，通过 SysMessageService/SendMessage 排队处理。生产订单已释放/状态改变有业务事件；BOM 主数据写入及独立库存调整仍须按租户实体目录进一步核验。
- 版本/授权：MES 集成功能要求 Time and attendance license key。动态 MCP 要求至少 10.0.47、10.0.46 PQU-2 或 10.0.45 PQU-7；Tier 2+ 或 Unified Developer Environment，CHE 不支持；需要 Allowed MCP Clients。MCP 工具调用存在依客户端及许可证而异的计费，不能当免费无限调用。
- MCP/CLI：官方当前动态 ERP MCP 有 data CRUD、form、action 三类工具，权限仍由应用执行，data create 不支持 deep insert。旧 Dataverse 静态 13 工具服务计划 2026-10-01 退役；不要新接旧版。当前技术文档已提供可用版本与配置，不把早期静态 MCP 的 GA 日期自动等同新动态版本的发布时间。
- 建议接法：优先用专用 MES 消息接口回传工时/数量/消耗，监听结果与失败队列；单据头行分步导入并补偿。MCP 适合有审计的查询和经过白名单的动作，批量确定性同步仍走接口。

官方证据：[Sales order headers V2 实体](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/entity-sales-order-headers-v2-salesorderheaderv2)；[MES 集成消息、工时报工、许可前置](https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/mes-integration)；[OData / Data Management integration APIs](https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/contract-lifecycle-management/developer/clm-data-integration-apis)；[动态 ERP MCP 版本、工具和计费](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/copilot-mcp)；[MCP 身份和权限](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/copilot/mcp/mcp-security)；[入站集成架构与 X++ 服务](https://learn.microsoft.com/en-us/dynamics365/guidance/reference-architectures/finance-operations-resilient-inbound-integration-external-system)。

### Oracle Fusion Cloud SCM

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST APIs；FBDI 批量导入；部分 SOAP 服务；OIC business events。
- 业务对象：Sales Orders for Order Hub 支持读、创建/更新订单，官方已用 REST/FBDI 替代多项旧 SOAP 操作。itemStructures（BOM）有 GET/POST/PATCH；workOrders 有 POST。operationTransactions 可 POST 报工，但不支持 GET，不能承诺此生产交易接口完整 CRUD。inventoryStagedTransactions 可创建暂存库存交易，后续处理结果仍需确认。
- 版本/授权：按季度版本（此处主要 26A/26B，BOM 引用 25C）、已购买 SCM 模块和 REST privileges 核验；PLM、Manufacturing、Inventory、Order Management 并非一个权限。销售数据访问规则可能进一步限制 REST 可见订单。OIC 适配/agentic integration 是额外服务和部署边界。
- MCP/CLI：未核验 Fusion SCM 自身独立对外 MCP server。Fusion AI Agent Studio 的 MCP tool 文档描述连接外部 MCP，是客户端能力。Oracle Integration 3 官方支持把项目中的已选 integration tools 作为 MCP 暴露；不能据此声称所有 SCM 单据自动可写。
- 建议接法：REST 读订单/BOM，工单及报工写入分别映射角色权限；库存暂存与最终过账分开追踪。历史 SOAP 接口逐项对照退役说明。需要 MCP 时基于 OIC 或KANPACE自己的受控适配层封装。

官方证据：[Order Management 26B SOAP→REST/FBDI 替换边界](https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/order26b/26B-order-mgmt-wn-t72535.htm)；[Item Structures REST 操作](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/fasrp/api-product-lifecycle-management-item-structures.html)；[创建 workOrders](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/op-workorders-post.html)；[Operation Transactions 仅支持的操作](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/api-manufacturing-work-order-operation-transactions.html)；[创建 Inventory Staged Transactions](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/fasrp/op-inventorystagedtransactions-post.html)；[REST roles and privileges](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/Roles_and_Privileges.html)；[Fusion OAuth 配置](https://docs.oracle.com/en/cloud/saas/applications-common/26b/oaext/configure-oauth.html)；[SCM REST Quick Start 认证](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/fasrp/Quick_Start.html)；[Oracle ERP Cloud Adapter 支持 SCM 事件](https://docs.oracle.com/en/cloud/paas/application-integration/erp-adapter/oracle-erp-cloud-adapter-capabilities.html)；[AI Agent Studio 外部 MCP tools](https://docs.oracle.com/en/cloud/saas/fusion-ai/aiaas/how-do-i-use-ai-agent-studio.pdf)；[Oracle Integration 3 项目 MCP](https://docs.oracle.com/cd/G41715_01/paas/application-integration/aiagents/using-agentic-ai-oracle-integration-3.pdf)；[SCM REST 26B 官方索引](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fasrp/index.html)。

### Oracle NetSuite

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：SuiteTalk REST；SuiteQL；SuiteScript / RESTlets；SuiteCloud SDK/CLI；官方 AI Connector MCP。
- 业务对象：官方 REST record 清单包括 Sales Order、BOM/BOM Revision、Inventory Adjustment/Transfer、Work Order/Issue/Completion/Close。workOrder 具体文档给出 GET/POST/PATCH 及 transform 为发料、完工、关闭等例子。其他对象不能仅因列在清单就推定任意字段都可改，需继续读取每个 record schema 和 transformation 约束。
- 版本/授权：Work Orders、Advanced Bill of Materials、WIP 等特性需按所用对象启用并具备权限。MCP 需 Server SuiteScript、OAuth2、Standard Tools 所需 REST Web Services 等；连接角色不能是 Administrator。SOAP 2025.2 为最后计划 WSDL，2028.2 停用是未来计划，并非今天已不可用。
- MCP/CLI：官方 AI Connector Service 是远程 MCP，Streamable HTTP、OAuth2 Authorization Code + PKCE。Standard Tools SuiteApp 提供 create/get/update 等记录工具及 SuiteQL/报告，按用户角色和 REST record 支持范围授权；不是默认全库写权限。已查到产品技术接入文档和工具清单，不是社区示例。
- 建议接法：用 REST + external IDs / 变换动作承接订单与生产工单；复杂制造记录先做 sandbox。MCP 用 Standard Tools 精选角色，批量同步用 REST。SuiteScript 负责可补偿的变更通知/扩展，避免把原始数据库查询当业务提交。

官方证据：[REST 支持的 Records](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1558962745.html)；[Work Order REST 和转换操作](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_47212826771.html)；[BOM / Advanced Bill of Materials 前置](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1517399759.html)；[Work Order Completion / WIP](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N3701691.html)；[MCP AI Connector Service 接入](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_4160616848.html)；[Standard Tools SuiteApp](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_143403258.html)；[OAuth2 M2M setup / sandbox 边界](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_162686838198.html)；[User Event best practices](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_N3361453.html)；[SuiteCloud Node.js CLI](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_155931263126.html)；[SuiteCloud SDK / Java CLI 状态](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1558730192.html)；[SOAP 退役计划](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N3413913.html)。

### Infor CloudSuite / ION（M3、CSI 分别核验）

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：ION API Gateway / REST；M3 MI transactions；ION BOD；Infor OS MCP（按产品/发布范围）。
- 业务对象：M3 已核验 PMS100MI 查询生产订单/材料/工序，MMS200MI/GetItmWhsBal 查库存；PMS050MI/RptReceipt、PMS060MI/RptIssue、PMS070MI/RptOperation 写入收料、发料、报工。BOM 读取有 PDS001MI/PDS002MI；旧 15.1.4 文档列 PDS001MI/Add。CSI 9.00 的官方 ION 指南列 ProcessSalesOrder、ProcessBillofMaterials、ProcessProductionOrder 等入站 BOD，但不能把这个旧版契约直接等同当前 M3/LN/CSI 全系列。
- 版本/授权：CloudSuite 是产品家族，M3、LN、CSI/工业版等对象与交易名不同；需 API Gateway authorized app、ERP 业务功能和具体 API transaction 权限。此行 A 仅表示已有 M3 等具体技术契约；并不表示每个 CloudSuite 已完成同等覆盖。
- MCP/CLI：Infor OS 2026 官方文档已有 API Gateway 中 MCP 类型端点、工具和 supported CloudSuite 配置。2026-04 的官方 Agentic Orchestrator 发布说明称相关增强 limited availability；截至本次文档未能证明所有 CloudSuite 都 GA 对外开放。未来 SCP 2026.10 文档不作为 2026-09-04 已上线证据。
- 建议接法：先由客户确认 M3/CSI/LN 和准确版本，再以 MI 或 BOD 接订单/BOM/生产事件；不要实现一个叫 Infor 的万能字段映射。MCP 接入列为需租户开通核实项。

官方证据：[M3 生产收发料和报工 APIs](https://docs.infor.com/m3udi/latest/en-us/m3beud/expdeshs/ujy1757047689416.html)；[M3 生产订单和库存接口](https://docs.infor.com/m3udi/16.x/en-us/m3beud/expdeshs/nze1679556743952.html)；[M3 产品结构读取](https://docs.infor.com/m3udi/16.x/en-us/m3beud/scexechs/jxa1760983766975.html)；[M3 15.1.4 PDS001MI/Add 边界](https://docs.infor.com/m3be/15.1.4/en-us/m3bern/kgg1580999438832.html)；[CSI 9.00 ION BOD 配置指南（旧版证据）](https://docs.infor.com/csi/9.00.x/en-us/useradminlist/csi_Configuration%20Guide%20for%20Infor%20ION_90030_42967.pdf)；[Infor API Gateway 管理指南](https://docs.infor.com/inforos/2025.x/en-us/useradminlib_cloud/apigatewayag_cloud/ionapi_2025.x_apigatewayag_cloud_en-us.pdf)；[M3 OAuth authorized app 配置](https://docs.infor.com/m3pwb/2025.x/en-us/m3pwbolh/pages/1091_help.html)；[Infor OS 2026 MCP 配置](https://docs.infor.com/inforos/2026.x/en-us/useradminlib_cloud/genaiug/ssm1759825468545.html)；[2026-04 Agentic Orchestrator / limited availability](https://www.infor.com/en-ca/blog/infor-agentic-orchestrator-ai-value-drivers)。

### Epicor Kinetic

- 类别：国际ERP；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：REST / OData V4；Business Objects / BAQ / Functions；BPM；Cloud SDK。
- 业务对象：官方 Open REST 页面明确支持 Kinetic business objects、processes、reports、BAQ、Functions 的读取/修改/业务逻辑执行。但本次公开访问的 v2 技术指南跳转 EpicWeb 登录，未取得订单/BOM/Job/库存/Labor 各对象的完整方法契约；因此不能写成这五类已逐一完成端点核验，也不凭记忆填写 service 名称。
- 版本/授权：部署版本、REST v2 配置、API key、access scopes 与 ERP 角色共同限制访问。详细 API 文档可能需客户/伙伴 EpicWeb 登录或租户 REST Help。SDK/集成产品的商业授权以客户合同核实，不从宣传页推定免费。
- MCP/CLI：2026-05 官方 Agentic AI Stack / Prism Agent Foundry 新闻提到 MCP 互操作，但本次未核验公开服务器端点、认证流程、工具清单和每个 Kinetic 版本 GA 边界。归类为官方方向/能力说明，不能冒充可立即接入的已验证 MCP 服务。
- 建议接法：取得客户租户 REST Help / Swagger 导出，逐一验证订单、BOM、工单、库存、工时报工 BO 的方法与业务校验，再决定适配范围。当前仅建立候选连接器，不显示“已连通”。

官方证据：[Kinetic Open REST 能力、API key、scope](https://www.epicor.com/en-us/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/open-rest-api/)；[REST Services v2 指南（本次跳转登录）](https://epicweb.epicor.com/doc/Docs/Epicor10_RESTServices_v2_102700.pdf)；[Kinetic 开发框架认证说明](https://kinetic.developer.epicor.com/framework/assets/Kinetic-Engagement-Deck.pdf)；[Functions / BPM / 业务事件调用](https://www.epicor.com/en/products/enterprise-resource-planning-erp/kinetic/tools-and-technology/epicor-functions/)；[Cloud SDK / Data Fabric / Service Designer](https://www.epicor.com/zh-hant-tw/products/enterprise-resource-planning-erp/epicor-kinetic/cloud-business-platform/)；[2026-05 Agentic AI Stack 官方发布](https://www.epicor.com/en-us/newsroom/news-releases/epicor-introduces-agentic-ai-stack/)。

### IFS Cloud

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：Projection OData V4；OpenAPI 2/3；MES ShopFloorConnector；IFS Connect events。
- 业务对象：官方 MES 集成说明确认 ManufacturingPartService/InventoryPartService 读取制造主数据、BOM/路线版本。ShopFloorConnector 可启动准备/生产、记录停机/时间/数量、将 Shop Order 收入库存；ScheduleConnector 报数量/废品。Shop Floor Information 契约读取工单/工序/材料，部分 POST 实际只读。销售订单 CRUD 和 BOM 写入未在本次逐对象核验，不应由平台 OData 能力直接推断。
- 版本/授权：按实际 25R1/25R2/26R1 租户 projection 及 permission sets 取契约；部分 projection 天生只读，写入需 action/entity 权限。Premium API 是官方接口分类名称，本次没有足够商业证据断定其必然单独收费。
- MCP/CLI：本次官方开发文档未确认 IFS Cloud 独立对外 MCP server 的端点/认证/工具目录。社区或第三方 IFS MCP 不等于官方产品；未查到不代表没有接口，可基于已公开 OData/OpenAPI 自建受控工具。
- 建议接法：优先以 ShopFloorConnector 对接工序开始、工时、数量和完工收货；先读取并锁定 BOM/路线 revision，外部任务映射至 shop order/operation。销售订单/BOM 写入另开契约核验任务。

官方证据：[IFS Manufacturing Execution System Integration](https://docs.ifs.com/ifsclouddocs/25r2/Manufacturing/AboutManufacturingExecutionSystemIntegration.htm)；[Shop floor information 方法契约](https://docs.ifs.com/techdocs/25R2/040_tailoring/300_extensibility/060_use_cases_across_industries/010_mes/040_shop_floor_connector/011_get_shop_floor_information/)；[API Explorer / OpenAPI](https://docs.ifs.com/techdocs/25r2/040_tailoring/300_extensibility/020_api_explorer/)；[API Explorer 默认 OAuth2](https://docs.ifs.com/techdocs/24r2/040_tailoring/300_extensibility/020_api_explorer/010_navigate/)；[Projection permission sets](https://docs.ifs.com/techdocs/24r2/030_administration/010_security/020_permission_sets/004_permission_set_overview/010_projections/)；[IFS API Usage Policy](https://docs.ifs.com/policy/APIUsageCloud.pdf)；[Premium API 技术分类](https://docs.ifs.com/techdocs/26r1/040_tailoring/300_extensibility/020_api_explorer/030_premium_apis/)。

### Odoo

- 类别：开源ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：JSON-2 API（19版起）；自动化 Webhook；Python 模块扩展；odoo-bin 运维 CLI。
- 业务对象：官方 MRP 源码可核对 BOM、制造单关联、工序工单、工作中心和数量；外部 API 可调用数据库开放的模型方法。实际字段、方法、读写权限取决于已安装模块和数据库 /doc，不能保证所有对象都可直接写入或提交。
- 版本/授权：Odoo 19 官方外部 API 文档把商业计划权限列为 Custom，One App Free/Standard 不提供；Community 为 LGPLv3，Enterprise 使用单独许可证。自托管 Community 应另核对部署能力，不直接套用云套餐结论。
- MCP/CLI：本次未核实 Odoo 厂商官方 MCP；应用市场或社区 MCP 不能标为官方。odoo-bin 是服务器、模块和数据库开发运维 CLI，不是已核实的远程派工 CLI。
- 建议接法：保留客户 Odoo 的销售、采购和库存账；KANPACE读取已批准订单、输出经审核的 BOM/工序映射，再经业务方法回写报工。先在客户副本验证创建、部分完工、取消与版本变化。

官方证据：[Odoo 19 External JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)；[Odoo 官方 BOM 模型源码](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_bom.py)；[Odoo 官方工序工单源码](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_workorder.py)；[Odoo Studio Webhooks](https://www.odoo.com/documentation/19.0/applications/studio/automated_actions/webhooks.html)；[Odoo 官方 CLI](https://www.odoo.com/documentation/19.0/developer/reference/cli.html)；[Odoo 19 官方许可说明](https://www.odoo.com/documentation/19.0/ro/legal/licenses.html)。

### ERPNext / Frappe

- 类别：开源ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：DocType REST API；文档事件 Webhook；Python hooks；Bench 运维 CLI。
- 业务对象：DocType 原生提供记录 REST 读写。制造对象包含 BOM、Work Order、Job Card、Operation、Workstation；Job Card 记录员工、时间、完成数量。CRUD 成功不等于已通过文档提交、库存或完工业务校验。
- 版本/授权：ERPNext 官方源码为 GPLv3；自托管需承担部署和升级维护。托管服务的自定义应用、脚本和资源限制按所选套餐核验，本次未认定所有托管计划功能相同。
- MCP/CLI：本次未核实厂商官方 ERPNext MCP。Bench 是官方站点、应用、备份与迁移 CLI；日常派工应走受控业务 API，不让 Agent 依赖管理员控制台。
- 建议接法：适合作为首个完整 ERP 连接试点；将KANPACE部件/工序与已批准 BOM、Work Order、Job Card 建映射，验收部分报工、重复事件和图纸升版后的旧任务处置。

官方证据：[Frappe REST API](https://docs.frappe.io/framework/user/en/api/rest)；[ERPNext Job Card](https://docs.frappe.io/erpnext/job-card)；[Frappe Webhooks](https://docs.frappe.io/framework/user/en/guides/integration/webhooks)；[Frappe Python Hooks](https://docs.frappe.io/framework/user/en/python-api/hooks)；[ERPNext 官方许可证](https://github.com/frappe/erpnext/blob/develop/license.txt)；[Bench 官方概览](https://docs.frappe.io/framework-copy/bench/overview)。

### Siemens Opcenter

- 类别：国际MES；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：Opcenter X HTTP 连接器；Kafka 连接器；OPC UA 连接器；具体产品/版本的 REST 集成。
- 业务对象：Opcenter X 官方资料明确 REST 对接、消息发布/消费、OPC UA 数据变化订阅、事件及历史数据能力；本次未取得适用于客户 Execution Discrete 版本的订单/BOM/工单读写字段契约。Semiconductor 的 REST 证据不能泛化到全系列。
- 版本/授权：需先确认 X、Execution Discrete、Semiconductor 或 Intelligence 等具体产品、版本及已授权连接器。客户 SDK/API 目录、写入权限和费用未由公开资料核实。
- MCP/CLI：本次未核实覆盖整个 Opcenter 产品族的官方生产派工 MCP、CLI 或统一 SDK。Intelligence 分析 API 不等于制造执行事务 API。
- 建议接法：已有 Opcenter 客户按产品版本专项适配；先取得测试环境和接口目录，验证一条订单、一条工序下发、一条部分报工、一次工程变更，再扩展范围。

官方证据：[Siemens Opcenter X 2501 官方发布说明](https://blogs.sw.siemens.com/opcenter/whats-new-in-opcenter-x-2501/)；[Execution Semiconductor 2304 官方功能说明](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/7KZ5yp58eh1O7a6B7lLuhh/en-US/Siemens%20SW%20Whats%20new%20in%20Opcenter%20Execution%20Semiconductor%202304%20Fact%20Sheet.pdf)；[Opcenter Intelligence API（分析产品）](https://developer.siemens.com/insights-hub/docs/apis/advanced-opcenter-intelligence/api-opcenter-intelligence-api.html)。

### SOLIDWORKS PDM Professional

- 类别：设计与协同；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：PDM Professional Web API；COM/.NET API；签入与工作流插件事件；Webhook 配置。
- 业务对象：官方 API 涵盖工程文件、引用、变量、工作流、版本/修订；Web API 列出 named/computed BOM 和焊件 cut list 读取，以及文件/配置相关读写端点。BOM 提取不等于完成几何识别、排版或展示柜拆单。PDM Tasks 也不是 MES 生产工单。
- 版本/授权：API 能力属于 PDM Professional；需核验客户是否仅有 Standard、Web API Server 是否部署以及目标版本支持的端点和权限。 Webhooks 官方从 PDM Pro 2025 Web API 提供，需对应 2025+ 版本与 Web API Server 部署。
- MCP/CLI：已核实官方 COM/.NET API 与插件机制；本次未核实官方 MCP 或通用业务 CLI。适合在工程 Windows 工作站/服务器运行连接服务。
- 建议接法：工程师继续用原 CAD/PDM 签入发布；KANPACE读取明确发布的配置、BOM 和版本，生成拆单候选与变更影响，保留工程 BOM 到制造 BOM 的可追踪映射。

官方证据：[PDM 2026 API Getting Started](https://help.solidworks.com/2026/English/api/epdmapi/GettingStarted-epdmapi.html?format=P&value=)；[PDM Professional Web API 2025](https://help.solidworks.com/2025/English/api/pdmprowebapihelp/PDM%20Pro%20API_ws.html)；[PDM API Release Notes](https://help.solidworks.com/2025/english/api/epdmapi/ReleaseNotes-epdmapi.html?format=P&value=)；[PDM Pro Webhooks 官方编程指南（2025起）](https://help.solidworks.com/2026/english/api/pdmprowebapihelp/PDMProWebAPI_Webhooks_Programming_Guide.html?format=P&value=)。

### Rockwell Plex

- 类别：国际MES；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：官方制造业务 API；Custom APIs；集成层/EDI。
- 业务对象：官方目录列有 BOM、Parts、Process Routings、Sales Orders、Job Scheduling、Production Operations、Inventory、Time Clock 和 Checksheet；生产 API 给出工作中心源库存装载等操作。类别公开不意味着每个对象全部读写、撤销和报工端点均已核实。
- 版本/授权：生产操作 API 混有稳定与 Beta 端点，Beta 支持期限有限且可变化。客户订阅、鉴权、配额、写入权益和价格需逐项核对。这里是 Rockwell 制造 Plex，与 plex.tv 无关。
- MCP/CLI：本次未核实 Rockwell Plex 官方 MCP、通用业务 CLI 或统一 SDK；不得混用 Plex 媒体服务器的 Token 或 SDK。
- 建议接法：保留既有 Plex 零件、订单、工作中心和库存账，KANPACE处理展示柜图纸证据与工种执行；在客户测试环境确认具体稳定端点，再回写部分数量和质量结果。

官方证据：[Plex 官方 API 目录](https://developers.plex.com/docs)；[Production Operations Management API](https://developers.plex.com/docs/production-operations-management-api)；[Plex Platform 官方资料](https://plex.rockwellautomation.com/content/dam/plex/legacy/2022-07/10008_Plex_Platform_Brochure.pdf)；[Plex Custom APIs 官方资料](https://plex.rockwellautomation.com/content/dam/plex/legacy/2022-06/10301_Plex_Datasheet_ERP_CustomAPIs.pdf)。

### 飞书多维表格

- 类别：设计与协同；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：OpenAPI；官方 Python SDK；记录变化事件；自动化 Webhook；官方开源 CLI；官方 Beta MCP。
- 业务对象：已核实表/字段/记录 API 与创建记录能力；官方 SDK 包含记录变化事件模型。BOM、订单和工单是客户自定义表结构，不是已验证的内置制造事务；事件订阅权限和覆盖范围需在租户联调。
- 版本/授权：应用权限与文档授权均需满足；高级权限、自动化与数据额度按实际版本核验。中国飞书与国际 Lark 使用匹配的应用及域名，不能交换使用凭据。
- MCP/CLI：larksuite/cli 和 larksuite/lark-openapi-mcp 均为官方项目；MCP README 标注 Beta，工具兼容范围与文件操作有限制，不代表稳定覆盖所有 OpenAPI。
- 建议接法：保留现有销售登记、安装排期和审批习惯；表格加来源 ID、工程版本和原单链接，KANPACE处理有效工序状态后回写。CLI/MCP 用于授权查询或草稿，生产提交由受控 API 校验。

官方证据：[飞书创建记录 API](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_create)；[官方 SDK 记录变化事件模型](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/drive/v1/model/p2_drive_file_bitable_record_changed_v1.py)；[飞书官方 CLI](https://github.com/larksuite/cli/blob/main/README.zh.md)；[飞书官方 OpenAPI MCP](https://github.com/larksuite/lark-openapi-mcp)；[官方 API 接入示例及权限](https://www.feishu.cn/content/137710114294)；[高级权限官方说明](https://www.feishu.cn/hc/zh-CN/articles/892315791286-%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E9%AB%98%E7%BA%A7%E6%9D%83%E9%99%90%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)。

### 钉钉宜搭

- 类别：设计与协同；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：开放 API；页面平台 API；HTTP 服务注册；表单/审批节点回调。
- 业务对象：官方文档可核对表单/流程类 API 和流程发起，以及节点触发外部 HTTP 服务。页面内平台 API 与外部开放 API 的鉴权上下文不同；本次没有把所有表单读写都认定为同一外部契约。BOM/工单属于客户自定义应用模型。
- 版本/授权：开放 API 为专业版/专属版能力。官方限流/计费帮助页存在前后表述不一致，不能宣称统一免费、不限额或固定 40 QPS；以租户版本、准确端点和合同/控制台为准。
- MCP/CLI：本次未核实宜搭专用官方 MCP、CLI 或覆盖全部宜搭业务的统一 SDK；钉钉 AI 功能宣传不构成上述接口证据。
- 建议接法：销售和项目经理继续原表单、审批；审批通过后将客户、交期、柜体配置和图纸版本传KANPACE，处理完成后返回原流程。先明确字段和状态维护归属。

官方证据：[宜搭开发能力/版本对照](https://docs.aliwork.com/docs/developer/usage/price)；[宜搭平台 API 说明](https://docs.aliwork.com/docs/yida_support/lbtl0t/aql605)；[宜搭服务注册](https://docs.aliwork.com/docs/yida_qalist/lmvsctyt7rxtgsrq/ld80ev)；[宜搭服务回调](https://docs.aliwork.com/docs/yida_qalist/lmvsctyt7rxtgsrq/kkcdu6)；[宜搭限流与计费帮助](https://docs.aliwork.com/docs/yida_support/lbtl0t/wae8oddztfq167ly)。

### Manhattan Active

- 类别：供应链与仓储；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST/JSON；OAuth；Data Stream。
- 业务对象：REST 技术入口已核验；官方 Hub 覆盖订单、仓储、库存与运输方案。具体收货/出库/库存调整的端点及动作，需客户订阅文档逐项核对；本轮不推定制造 BOM/报工能力。
- 版本/授权：需相应 Active 订阅、租户 API 权限和开发者资料。Data Stream 是受支持目标的数据复制能力，不是任意 ERP 双向写回通道。
- MCP/CLI：本轮未核验到公开官方业务 MCP 或业务 CLI；不能因此判定不存在。
- 建议接法：客户已有该 WMS 时，从 ERP/MES 关联包装、出库和发运状态；不把 WMS 当拆单系统。

官方证据：[官方 REST 与 OAuth 入口](https://developer.manh.com/docs/how-to/rest-api/)；[Developer Hub 与 API 订阅文档](https://www.manh.com/solutions/manhattan-active-platform/developer-tools-api/developer-hub)；[Data Stream 技术说明](https://developer.manh.com/docs/concept-guides/data-stream/)。

### Blue Yonder Platform / WMS

- 类别：供应链与仓储；证据：B；KANPACE实现：未接通客户系统。
- 官方连接面：Connect 集成平台；API；预置连接器。
- 业务对象：官方 Connect 描述采购订单、库存调整、发运通知等互联场景；Link API 管理门户需要登录。本轮未取得每个 WMS 版本的对象级读写契约。
- 版本/授权：旧版 JDA、现有 WMS 与新平台不能共用能力结论；需核对已购产品、Connect/Link 服务、合作方权限及接口合同。
- MCP/CLI：本轮未核验到公开官方业务 MCP/CLI 契约。AI 产品介绍不等于可调用的外部 MCP。
- 建议接法：大客户已有该平台时复用其集成通道，先接库存与交付节点，依据客户文档确定写回。

官方证据：[Blue Yonder Connect 官方说明](https://info.blueyonder.com/blue-yonder-platform/what-is-blue-yonder-connect)；[官方 Link 开发者门户](https://developer-link.blueyonder.com/signin?returnUrl=%2F)；[WMS 集成与许可边界](https://blueyonder.com/resources/blue-yonder-ai-powered-wms-unified-faq)。

### QAD Enterprise Applications / QXtend

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：SOAP/XML QDoc；事件订阅；文件交换。
- 业务对象：QXtend Inbound 按原业务菜单校验接收 XML QDoc；Outbound 发布业务对象变化，可传 Web Service 或文件。官方资料举有物料、客户、供应商、BOM；具体生产工单/报工写入须查该版 QDoc 模板。
- 版本/授权：引用的是 QXtend / Enterprise Applications 文档，部分资料较旧；不能直接覆盖最新 QAD Adaptive ERP。需核对部署版本、QXtend 模块、菜单权限和模板。
- MCP/CLI：本轮未核验到对应产品公开官方业务 MCP/CLI。新平台 REST 能力不能直接套到存量 QXtend。
- 建议接法：客户已有 QXtend 时沿用 QDoc 与订阅机制，保留原业务校验；优先料号/BOM交换。

官方证据：[QXtend Inbound 官方技术文档](https://www.qad.com/documentation/Qxtend/QXtend_UG_v0185/13_QXI_Overview.16.02.html)；[QXtend Outbound 订阅与文件传递](https://www.qad.com/documentation/Qxtend/QXtend_TG_v0184/01Overview_tg.03.5.html)。

### Acumatica ERP / Manufacturing

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST；OData；C# SDK。
- 业务对象：官方 REST 文档和示例支持订单读取、记录新建更新及动作；制造示例涉及 Material Issues、Move Entry、Labor Entry，含保存和 Release。Default 与 Manufacturing 是不同端点，BOM 字段及版本须按客户契约补核。
- 版本/授权：REST 契约和 Endpoint 版本需绑定；本轮制造示例基于 2022 R2，当前客户的 Manufacturing 模块、扩展字段、API 用户及许可需重验。官方帮助页有浏览器限制，另以官方博客和 SDK 交叉核验。
- MCP/CLI：官方 C# REST SDK 已核验；业务 MCP/通用业务 CLI 本轮未核验。SDK 示例控制台程序不等于产品 CLI。
- 建议接法：海外制造客户候选：工单与报工走 Manufacturing endpoint，库存/订单按对应契约映射。

官方证据：[制造模块 REST 写入与报工示例](https://www.acumatica.com/blog/integration-rest-api-client-manufacturing/)；[REST/OData 官方说明与订单例子](https://www.acumatica.com/blog/acumatica-web-services-rest-api-odata-and-integration-best-practices/)；[官方 C# REST Client](https://github.com/Acumatica/AcumaticaRESTAPIClientForCSharp)。

### Sage X3

- 类别：国际ERP；证据：A；KANPACE实现：未接通客户系统。
- 官方连接面：REST；SOAP；GraphQL；文件交换。
- 业务对象：X3 V12 平台文档定义查询/详情/新建/更新/删除和 SOAP 文件导入导出；能力指南列 GraphQL 子集含订单、库存、工单与生产跟踪查询。具体 BOM 和报工 mutation 需客户版本 schema 核验，不能假定全对象可写。
- 版本/授权：本轮确认平台技术接口；不同 V12 补丁、部署与 GraphQL package 提供的业务节点不同。部分能力指南为 2022 版，当前范围须看客户开发者 schema 与许可。
- MCP/CLI：本轮未核验到 X3 的公开官方业务 MCP/通用 CLI；Sage 其他产品能力不能套用。
- 建议接法：保留原 X3 业务入口；先按实际 schema 接订单/物料，再试点制造跟踪的具体写入。

官方证据：[X3 V12 官方 API 参考](https://online-help.sagex3.com/erp/12/en-us/Content/V7DEV/api-guide_api-reference-guide.html)；[Sage X3 开发者入口](https://developer.sage.com/x3)；[Sage X3 能力指南（2022版）](https://www.sage.com/en-za/-/media/files/sagedotcom/master/gated-assets/ame/sage-x3/sage-x3-solution-capabilities-guide.pdf)。

## 当前成果与下一阶段

本轮交付官方资料矩阵与可筛选的本地 Web 研究页，以及《系统互联架构与实施路线》。真实连接器按订单读取→BOM/工单草稿回写→现场执行回写的顺序实施；每一步都需客户环境和真实对象验证。当前硬件已实现任务接收，问题上报和生产报工不能仅凭参考 UI 判定已实现。
