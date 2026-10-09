# 国内 ERP、进销存与 MES 官方互联核验

核查日期：**2026-09-04**。范围为常见国内产品线的代表性覆盖，包含 12 条主体记录及网上管家婆 1 条补充，不声称穷尽市场，也不按市场份额排名。仅以厂商主站、官方开发者/帮助文档作为能力证据；本轮为公开资料核验，**没有连接任何客户 ERP/MES 租户，也没有执行业务写入或联调验收**。

应把KANPACE定位为展示柜的图纸拆单、工种派工和现场执行层，再按客户实际拥有的软件版本配置适配器。目前文档足以优先启动的候选是畅捷通 T+、金蝶云星空和用友 U8；黑湖小工单因用户重点关注，应优先取得自身接口合同及技术清单。以下优先级是针对KANPACE下一步集成的工程建议，不能替代现场软件盘点，也不是采购推荐。

证据分级：**A**＝已看到官方技术契约/端点/技术接口文档；**B**＝已有官方接口或集成能力证据，但目标业务对象的完整契约未全部取得；**C**＝本轮证据不足。某产品标 A，仅说明本行明确列出的已验证部分达到 A，绝不表示全部对象、动作、版本或租户都已支持。“未核验”表示证据边界，不表示厂商没有该功能。

## 已证实的接口与业务边界

| 产品/范围 | 接入方式 | 订单、BOM、工单、库存、报工的可核验边界 | 证据与官方来源 |
|---|---|---|---|
| **金蝶云星空（K3 Cloud）** | WebAPI；官方 .NET/Java/Python SDK；事件回调需按版本核验 | 已核验通用单据查询、查看、保存、修改、提交、审核、删除、下推等 WebAPI 操作。订单、BOM、生产订单、库存、生产汇报应分别核对客户环境表单及开放权限；本轮未逐一验证这些制造对象的字段契约，不能把通用保存等同于任意单据可写。 | **A**。[金蝶云星空 WebAPI 知识专题](https://vip.kingdee.com/knowledge/specialDetail/650386937144032256?category=650387024452664320&id=650357430634787328&lang=zh-CN&productLineId=1)；[金蝶云星空官方 OpenAPI SDK 接入指南](https://open.kingdee.com/K3Cloud/Open/ApiCenterReportDetail.aspx)；[金蝶云星空生产订单帮助](https://help.open.kingdee.com/dokuwiki/doku.php?id=%E7%94%9F%E4%BA%A7%E8%AE%A2%E5%8D%95) |
| **金蝶星辰（精斗云开放平台）** | 官方开放 API 平台；版本化 API 文档入口；文件导入（部分基础资料） | 已确认星辰生产产品包含 BOM、生产任务、领退料与成品入库；这些是产品业务能力。开放平台页面为动态页面，本轮未取得相应订单/BOM/工单/库存/报工接口的完整官方字段契约，因此不把这些对象标为已验证 API 读写。官方入门材料可证明部分基础资料/期初数据批量导入。 | **B**。[精斗云官方开放平台](https://open.jdy.com/)；[金蝶星辰生产制造产品能力](https://www.jdy.com/domain/manufacture/)；[金蝶星辰产品模块与版本](https://www.jdy.com/buy/new_v7pro/)；[精斗云官方入门导入说明（历史材料）](https://cdn.jdy.com/tfapp/guide/v7_guide_list.pdf?v=2.0) |
| **金蝶苍穹（平台及其业务应用）** | OpenAPI / RESTful API；Java/脚本扩展；开放事件及回调；官方 MCP 能力；文件流 API | 官方技术专题列出查询/保存/删除/提交/审核/下推、REST 资源读写、开放事件与回调契约。苍穹是平台；订单、BOM、库存、生产工单、报工取决于安装的业务应用与模型，不能把平台 API 能力等同于一套通用制造 ERP 对象契约。 | **A**。[苍穹 OpenAPI、RESTful、开放事件及 MCP 官方技术专题](https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29)；[金蝶官方开发者门户](https://dev.kingdee.com/)；[金蝶苍穹官方产品页：MCP/A2A 与开放集成](https://www.kingdee.com/products/cosmic_platform.html)；[金蝶官网：苍穹支持 MCP（2025-04-18）](https://www.kingdee.com/article/1913102603487625217.html) |
| **用友 U8 / U8+ 开放平台** | OpenAPI（云＋客户端）；EAI / U8API；官方 Java/C# SDK | 官方 API 目录已核验 BOM 单条/批量查询、现存量查询、材料出库与产成品入库的新增/查询/审核/弃审。销售领域 API 列于同一目录，但需按目标单据选取方法。BOM 写入、生产工单创建、工序报工的具体开放契约本轮未核验，不推定为支持。 | **A**。[用友 U8 官方 API 目录](https://u8open.yonyoucloud.com/apiCenter/index)；[U8 BOM 批量查询端点与版本限制](https://u8open.yonyoucloud.com/apiCenter/bom_batch_get)；[用友 U8 官方 SDK 与平台入口](https://u8open.yonyou.com/)；[用友 U8 OpenAPI 模块与授权收费说明](https://u8open.yonyou.com/documentCenter/apiPayment) |
| **用友 U9 cloud** | 官方 OpenAPI 能力；PLM/MES 集成能力 | 用友官方发布材料确认标准产品轻量接口/OpenAPI，官方案例说明 BOM 与 PLM、制造执行的数据衔接。订单/BOM/生产工单/库存/报工各对象可读可写的方法、字段与动作，本轮未取得可公开访问且归属可确认的完整技术契约。 | **B**。[用友 U9 cloud 官方产品门户](https://u9cloud.yonyou.com/)；[U9 cloud 官方 OpenAPI 能力说明](https://u9cloud.yonyou.com/news/detailes/news/157.html)；[U9 cloud 官方 PLM 与 BOM 集成说明](https://u9cloud.yonyou.com/news/detailes/news/526) |
| **用友 BIP / YonBIP（iuap 开放平台）** | 官方 OpenAPI 平台；API 调试与频控治理 | 官方门户可核验 OpenAPI、API 调试助手与销售订单部分接口限流公告，能确认销售订单 API 存在。因文档正文动态加载，本轮未完整核验 BOM/工单/库存/报工各对象方法、写入动作和事件主题；不能据此承诺所有制造对象双向同步。 | **B**。[用友 iuap / YonBIP 官方开放平台及公告](https://open.yonyoucloud.com/)；[用友 BIP 官方 API 文档入口](https://open.diwork.com/#/doc-center/docDes/api?code=yonbip) |
| **畅捷通 T+ / T+Cloud** | OpenAPI；消息订阅/回调；异步单据创建；官方机器可读 API 文档 | 已核验 BOM 创建/查询/审核/删除/更新，生产加工单创建/查询/修改等，工序汇报单新增/查询/审核/删除；官方目录另列销售订单、现存量、领料和产成品入库。新增工序汇报契约含外部唯一单号、来源加工单/派工单、工序、人员、产量与合格量，适合工种任务回传。 | **A**。[T+ 官方 OpenAPI 对接指南与版本要求](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/tplusguide)；[T+ BOM API 与逐接口版本](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+jcda/tcbom)；[T+ 生产加工单 API](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+dj/t+scjgd)；[T+ 工序汇报新增：字段与权限头](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+dj/t+gxhbd?id=32274)；[T+ 消息订阅与补丁要求](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/t+msgsub)；[T+ 全业务 API 目录](https://open.chanjet.com/docs/file/apiFile/tcloud) |
| **鼎捷 T100（含相关平台集成）** | T100 OpenAPI；XML 契约/签名与分页；设备平台 API 对接能力 | 官方 T100 技术 PDF 已核验销售订单列表查询 t100.oapi.sales.order.list.data.query.get；库存应用指南给出入库新增→确认→过账的 API 流程。官方设备平台另说明工单抓取与报工回传能力，但这不是 T100 某版本 BOM/工序报工的具体端点证明。 | **A**。[鼎捷 T100 v3 销售订单查询官方 API PDF](https://dw-t-devops.digiwin.com/ssupkm/t100v3/zh_TW/API/file/wssp00003TW02_s.pdf)；[鼎捷 T100 库存管理 OpenAPI 应用指南](https://dw-t-devops.digiwin.com/ssupkm/t100v1/zh_CN/accessguide/file/TIPTOP/OpenAPI%E6%87%89%E7%94%A8%E5%A0%B4%E6%99%AF%E8%AA%AA%E6%98%8E_%E5%BA%AB%E5%AD%98%E7%AE%A1%E7%90%86.pdf)；[鼎捷设备平台：工单抓取与报工 API 集成](https://www.digiwin.com/software/DeviceCloud/AIoT_eq) |
| **浪潮海岳 GS Cloud / inSuite（分别核验）** | iGIX 开放集成/API 治理能力；开发平台 API 与事件模型 | 官方产品页可核验 GS Cloud、inSuite 与 iGIX 的不同定位；制造产品具有 BOM、工艺、计划等业务能力，iGIX 提供 API 集成/治理。尚未公开核验两款 ERP 各自的订单/BOM/工单/库存/报工读写契约。开发平台事件模型不等于这些业务对象已提供 Webhook。 | **B**。[浪潮海岳官方产品体系](https://www.inspur.com/lcjtww/2532566/index.html)；[浪潮 iGIX 开放集成平台](https://www.inspur.com/eportal/ui?pageId=2609848)；[浪潮 inBuilder 开发平台](https://www.inspur.com/lcjtww/2315499/2318933/2743133/index.html) |
| **黑湖小工单（单独产品）** | OPENAPI 存在的官方协议证据；按客户要求开放接口（范围待核验） | 官方用户协议明确提及通过 OPENAPI 接入的数据和按要求开放相应接口，可确认有接口接入情形。订单、BOM、工单、库存、报工逐对象读取/创建/更新、事件回调及字段范围，本轮未取得小工单自身的公开官方技术契约。不能用黑湖智造 3.0 的 OAuth/API 文档证明小工单拥有同样接口。 | **B**。[黑湖小工单官方用户协议：OPENAPI、接口开放与服务范围](https://www.xiaogongdan.com/userAgreement) |
| **黑湖智造 3.0（不等于小工单）** | 官方 OpenAPI；OAuth2.0；频控与接入说明；官方机器可读文档索引 | 官方开发门户明确智造 3.0 的 API 调用、接入、频控、OAuth2.0，以及接口分类/ID 的机器可读索引。本轮该索引请求受站点访问限制，未完成订单/BOM/工单/库存/报工各对象字段和读写范围核验；因此只确认平台开放能力。 | **B**。[黑湖智造 3.0 官方开放接口平台](https://v3-hw-openapi.blacklake.cn/document/api) |
| **摩尔元数 MES/MOM / MC 平台** | MES/MOM 开发平台能力；设备数据集成（OPC 等） | 官方产品/开发平台能证明 MES/MOM、公共数据与设备采集集成能力；设备平台的 OPC 等协议仅证明设备接入。订单、BOM、工单、库存、报工的外部业务 API 读写、事件回调及字段契约本轮未公开核验。 | **B**。[摩尔元数官方公司与平台介绍](https://www.morewis.com/gsjs/)；[摩尔元数 MC 官方开发平台](https://mobile.morewiscloud.com/)；[摩尔元数设备数据采集平台](https://www.morewis.com/mdip.html) |
| **网上管家婆 NGP（补充进销存）** | NGP OpenAPI；ISV 注册与接口文档；ERP 端 Token 刷新 | 官方帮助中心的 NGP-API 接入流程明确开放平台、ISV 注册、API 文档查询与 Token 刷新。本轮未取得订单/库存具体端点契约；BOM/工单/报工更不能从进销存接入流程推定支持。 | **B**。[网上管家婆官方 NGP-API 对接流程（2025-07-21）](https://helpnew.wsgjp.com/2488/8ef8/03c3b)；[网上管家婆 NGP 官方开放平台](https://ngpopen.wsgjp.com/#/) |

## 授权、版本与落地顺序

P0＝可优先验证通用连接与样本闭环；P1＝与用户场景强相关，但先补齐目标产品/租户契约；P2＝客户已有该系统时按项目实施。优先级是本文推断。

| 产品 | 版本/授权限制 | KANPACE下一步接法 |
|---|---|---|
| **金蝶云星空（K3 Cloud）** | 需管理员配置第三方系统登录授权与允许调用用户。官方 2020 年 SDK 指南标注新 SDK 需 PT136657 [7.3.1310.2] 或更高；这是该指南的历史版本门槛，不代表所有当前部署的统一最低要求。实际版本、补丁、模块及采购许可须核实。 [金蝶云星空 WebAPI 知识专题](https://vip.kingdee.com/knowledge/specialDetail/650386937144032256?category=650387024452664320&id=650357430634787328&lang=zh-CN&productLineId=1)；[金蝶云星空官方 OpenAPI SDK 接入指南](https://open.kingdee.com/K3Cloud/Open/ApiCenterReportDetail.aspx) | P0 候选：先读销售订单、物料与库存，再按现场表单映射提交已复核 BOM/生产单草稿；保存、提交、审核分开控制，回查结果后再记同步成功。 |
| **金蝶星辰（精斗云开放平台）** | 先确认星辰产品版本、已购生产模块、开放平台应用及账套授权；区分平台中的 API 版本，不能复用星空的登录 SDK、表单编号或接口地址。当前接口费用、配额、事件订阅适用范围需由平台账号/合同核验。 [精斗云官方开放平台](https://open.jdy.com/)；[金蝶星辰生产制造产品能力](https://www.jdy.com/domain/manufacture/) | P1 候选：适合小微展示柜厂的订单与进销存衔接；先在授权账号导出目标接口清单，再决定生产 BOM/报工是否通过 API 或经确认的导入模板进入系统。 |
| **金蝶苍穹（平台及其业务应用）** | 需要第三方应用授权、身份认证及操作权限；API 1.0/2.0、V6/V7、开放事件灰度与密钥条件分别核验。标准业务服务、Agent/MCP、定制 API 的可用范围和商业授权需按客户租户确认。 [苍穹 OpenAPI、RESTful、开放事件及 MCP 官方技术专题](https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29)；[金蝶官方开发者门户](https://dev.kingdee.com/) | P2 项目型：客户已有苍穹/星瀚应用时，通过授权业务 API 与开放事件集成；可将受控的查询和草稿操作供 Agent 调用，MCP 不替代业务权限与单据状态校验。 |
| **用友 U8 / U8+ 开放平台** | BOM 批量查询接口明确 U8 V12.0 及以上；其他接口各自有版本要求。官方收费文档要求购买 OpenAPI 模块、获得企业授权，采用云＋客户端及数据源绑定。旧网页报价不应直接当成今天合同报价。 [用友 U8 官方 API 目录](https://u8open.yonyoucloud.com/apiCenter/index)；[U8 BOM 批量查询端点与版本限制](https://u8open.yonyoucloud.com/apiCenter/bom_batch_get) | P0 候选：读取订单/BOM/库存作为KANPACE拆单输入；优先验证领料和产成品入库回传。工序报工保留在KANPACE，直到获得对应 U8 接口契约及权限。 |
| **用友 U9 cloud** | 企业版/标准版、版本补丁、已购模块、定制扩展及部署地址必须核验。U9 cloud 的接口不能用 U8 OpenAPI 或 YonBIP 的 Token/字段替代；开放范围以客户环境的接口目录及厂商授权为准。 [用友 U9 cloud 官方产品门户](https://u9cloud.yonyou.com/)；[U9 cloud 官方 OpenAPI 能力说明](https://u9cloud.yonyou.com/news/detailes/news/157.html) | P2 项目型：先从客户 U9 cloud 环境取得 OpenAPI 清单，验证物料/BOM/工艺路线与生产单关系，再实施KANPACE对接；不要直接写业务数据库。 |
| **用友 BIP / YonBIP（iuap 开放平台）** | 确认 BIP 产品/版本、租户及数据中心、企业应用授权和业务模块；门户公告表明 API 存在独立频控调整。U8、U9、BIP/YonSuite 等产品身份、地址与数据模型不应合并为一个通用适配器。 [用友 iuap / YonBIP 官方开放平台及公告](https://open.yonyoucloud.com/)；[用友 BIP 官方 API 文档入口](https://open.diwork.com/#/doc-center/docDes/api?code=yonbip) | P2 项目型：让客户管理员提供租户授权和制造领域 API 文档，从订单/主数据读取建立最小闭环，再验证生产与库存写入、频控和回查。 |
| **畅捷通 T+ / T+Cloud** | 总体对接支持 T+13.0 以上，但接口逐项按补丁发布：生产加工单创建要求所列 16.0.0129+；工序汇报要求所列 17.0.0010+；BOM 更新要求 T+Cloud 自 2024-10-30 或专属云 19.0.0186+。消息订阅要求 16.0+及补丁，排障说明标 >16.000.000.0209。需应用配置、账套授权及 Token。 [T+ 官方 OpenAPI 对接指南与版本要求](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/tplusguide)；[T+ BOM API 与逐接口版本](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+jcda/tcbom) | P0 候选：最适合验证订单/BOM→加工单→工序派工→真实报工闭环。以 ExternalCode 做跨系统关联，按工种映射车间/工序/班组，订阅增量事件并定期对账。 |
| **鼎捷 T100（含相关平台集成）** | 文档路径区分 T100 v1/v3、语言和接口版本，需核对客户产品版本、企业/营运据点、服务授权与认证配置。T100、E10、E10 Cloud、雅典娜是不同产品/平台，不能统一套用此 PDF 的 XML 接口。 [鼎捷 T100 v3 销售订单查询官方 API PDF](https://dw-t-devops.digiwin.com/ssupkm/t100v3/zh_TW/API/file/wssp00003TW02_s.pdf)；[鼎捷 T100 库存管理 OpenAPI 应用指南](https://dw-t-devops.digiwin.com/ssupkm/t100v1/zh_CN/accessguide/file/TIPTOP/OpenAPI%E6%87%89%E7%94%A8%E5%A0%B4%E6%99%AF%E8%AA%AA%E6%98%8E_%E5%BA%AB%E5%AD%98%E7%AE%A1%E7%90%86.pdf) | P2 项目型：先用销售单增量查询接单，按其库存单据状态执行入库回传；BOM与工序报工须客户提供当前版本契约后再扩展。 |
| **浪潮海岳 GS Cloud / inSuite（分别核验）** | 须先区分 GS Cloud、inSuite 与 iGIX；确认客户部署、版本、授权模块、集成平台和二开服务范围。本轮未取得可据以计算费用/配额的官方现行接口授权表。 [浪潮海岳官方产品体系](https://www.inspur.com/lcjtww/2532566/index.html)；[浪潮 iGIX 开放集成平台](https://www.inspur.com/eportal/ui?pageId=2609848) | P2 项目型：在已有浪潮环境内取得目标业务 API/数据字典，先实现订单与物料只读同步；工单和报工写入按实施合同与测试环境逐项验收。 |
| **黑湖小工单（单独产品）** | 具体服务按小工单合同及附件；新核心功能/高级服务可能独立采购。应取得小工单租户的接口开通清单、权限、费用/配额、测试环境。用户协议中的终止后通用格式数据返还不等于日常自动 CSV/Excel 同步。 [黑湖小工单官方用户协议：OPENAPI、接口开放与服务范围](https://www.xiaogongdan.com/userAgreement) | P1 业务优先核验：用户特别关注该产品，应优先拿到小工单官方接口清单；随后验证下发工单、读取工序/人员、回传真实报工。没有契约前，只能评估经确认的文件交换或独立KANPACE流程。 |
| **黑湖智造 3.0（不等于小工单）** | 需确认客户使用的是智造 3.0、租户授权及 API 频控/服务范围；不同黑湖产品和旧版本不可共用鉴权假设。索引不可访问是本轮证据限制，不表示没有这些接口。 [黑湖智造 3.0 官方开放接口平台](https://v3-hw-openapi.blacklake.cn/document/api) | P1 条件候选：有该版本客户时，从开放平台取得目标 API 契约再对接工单/报工；对象映射、事件与 OAuth 令牌更新须分别测试，不复用小工单连接配置。 |
| **摩尔元数 MES/MOM / MC 平台** | 需确认具体产品、部署版本、开发平台账号、可交付源码范围及二开/接口授权。官网所称开放业务源码不能推定为开源许可证或免费 API。 [摩尔元数官方公司与平台介绍](https://www.morewis.com/gsjs/)；[摩尔元数 MC 官方开发平台](https://mobile.morewiscloud.com/) | P2 项目型：先向当前客户环境取得业务接口和开发授权；设备采集与KANPACE任务/报工 API 分层对接，避免把采集到的设备信号直接等同于完工。 |
| **网上管家婆 NGP（补充进销存）** | 该证据仅适用网上管家婆 NGP；管家婆辉煌、财贸、工贸、毕方等产品需分别核验，不能共用接口/插件授权结论。现行接口收费、ERP 套餐和可读写范围应按平台账号及合同确认。 [网上管家婆官方 NGP-API 对接流程（2025-07-21）](https://helpnew.wsgjp.com/2488/8ef8/03c3b)；[网上管家婆 NGP 官方开放平台](https://ngpopen.wsgjp.com/#/) | P1/P2 按现有客户决定：优先只接已确认的销售订单、商品、仓库与库存，制造拆单、工种任务和报工留在KANPACE；取得对应接口后再做单据回传。 |

## MCP、SDK、CLI 与文件接入不能混为一谈

- **金蝶云星空（K3 Cloud）**：本轮未核验星空各版本可直接使用的官方 MCP 服务；苍穹的官方 MCP 能力不能自动套用到星空客户实例。
- **金蝶星辰（精斗云开放平台）**：本轮未核验星辰专属官方 MCP 服务。网上第三方封装、API 调用示例不算官方 MCP。
- **金蝶苍穹（平台及其业务应用）**：已核验官方开发文档包含 MCP 服务（for 灵基）与 MCP 常见问题；金蝶官网也宣布苍穹提供标准及自定义 MCP。具体服务地址、可调用工具、租户授权与最低版本仍需现场验证。
- **用友 U8 / U8+ 开放平台**：本轮未核验 U8 官方 MCP 或独立业务 CLI；官方 SDK 与 EAI 不能视为 MCP。
- **用友 U9 cloud**：本轮未核验 U9 cloud 官方 MCP/CLI。产品宣传中的 AI Agent 或生态对接不直接证明存在可接入的 MCP 服务。
- **用友 BIP / YonBIP（iuap 开放平台）**：本轮未核验面向目标制造业务对象的官方 MCP/CLI；应另取官方服务地址与授权文档，不能以第三方 MCP 项目替代。
- **畅捷通 T+ / T+Cloud**：本轮未核验官方 MCP 服务；官方 llms.txt/Markdown 契约方便 Agent 阅读，但文档格式不是 MCP 协议端点。
- **鼎捷 T100（含相关平台集成）**：本轮未核验目标 T100 业务对象的官方 MCP/业务 CLI；不要把雅典娜或 AI 产品宣传等同于已开放标准 MCP。
- **浪潮海岳 GS Cloud / inSuite（分别核验）**：本轮未核验目标海岳 ERP 业务对象的官方 MCP/CLI；开发平台和工业物联接入不能替代 ERP 开放接口证明。
- **黑湖小工单（单独产品）**：本轮未核验黑湖小工单官方 MCP、SDK 或业务 CLI；第三方连接器与黑湖智造 SDK 均不自动适用。
- **黑湖智造 3.0（不等于小工单）**：本轮未核验官方 MCP 服务；机器可读 Markdown/API 索引不等于 MCP。官方 Java SDK 的适用产品/版本还需与智造 3.0 文档核对。
- **摩尔元数 MES/MOM / MC 平台**：本轮未核验官方业务 MCP/CLI；开发套件及设备协议不是 MCP。
- **网上管家婆 NGP（补充进销存）**：本轮未核验 NGP 官方 MCP/SDK/业务 CLI。

其中，苍穹开发者技术专题可直接核验“开放事件”和“MCP 服务（for 灵基）”目录。它证明该平台存在官方能力；具体可部署版本、服务地址和工具授权仍须从客户环境取得。金蝶官网 2025 年发布的 MCP 信息可以补充背景，不能外推为所有星空、星辰用户已自动开通。[苍穹官方技术专题](https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29)、[金蝶官网 MCP 信息](https://www.kingdee.com/article/1913102603487625217.html)

本轮未核验上述产品可直接安装使用的通用官方**业务 CLI**。文档中的 cURL 示例、Java/C# SDK、厂商开发构建工具都不能自动标成业务 CLI。即使KANPACE将来自己把某个授权 API 包装成 MCP/CLI，也必须标为“KANPACE适配器”，不冒充厂商官方服务。

文件路径也要逐对象验证。本轮只有精斗云历史入门材料能支持部分基础资料/期初数据导入这一有限结论；不代表当前星辰所有生产对象都有稳定的自动文件接口。小工单协议的终止后数据返还是退出服务的机制，不能作为常态导入导出接口证明。其余产品不能因为界面有 Excel 按钮、开发包可导入或支持文件流，就在集成清单上填写“订单/BOM/报工可自动文件交换”。[精斗云官方入门材料](https://cdn.jdy.com/tfapp/guide/v7_guide_list.pdf?v=2.0)、[小工单官方协议](https://www.xiaogongdan.com/userAgreement)

## 对KANPACE最有用的三个具体发现

1. **畅捷通 T+ 的工序汇报契约与工种任务直接相关。** 已取得官方 `POST /tplus/api/v2/ManufactureReportOpenApi/Create` 契约：需要外部唯一单号、来源单据及其工序明细、工艺路线、车间、单位，可传报工量、合格量、人员/班组。所列本地版本要求 17.0 对应补丁或以上；不是所有支持 T+ 基础 OpenAPI 的 13.0 客户都能调用。KANPACE可先把木作、五金、玻璃、灯光映射为客户既有工序/车间，再用真实报工事件创建汇报单。[工序汇报新增官方契约](https://open.chanjet.com/md/docs/file/apiFile/tcloud/t+dj/t+gxhbd?id=32274)
2. **黑湖小工单和黑湖智造必须是两个连接器。** 小工单官方协议证明存在 OPENAPI 接入及按要求开放接口的情形，但没有给出本轮可验证的对象契约；智造 3.0 有自己的 OAuth2.0、频控及文档目录。后者的 API、Token、SDK 和地址不能拿来填写前者的支持清单。[小工单官方协议](https://www.xiaogongdan.com/userAgreement)、[智造 3.0 开放平台](https://v3-hw-openapi.blacklake.cn/document/api)
3. **同厂商的产品也不能合并版本适配。** 星空是按其 WebAPI/授权/单据机制集成；星辰使用精斗云开放平台；苍穹是应用平台。用友 U8 的云＋端/OpenAPI 模块、U9 cloud 的轻量接口、YonBIP 的租户开放平台、畅捷通 T+ 的应用/账套与逐接口补丁条件均不同。连接配置至少应记录厂商、产品、版本补丁、部署地址、租户/账套、组织和启用模块。[星空官方接入](https://open.kingdee.com/K3Cloud/Open/ApiCenterReportDetail.aspx)、[U8 模块授权说明](https://u8open.yonyou.com/documentCenter/apiPayment)、[T+ 对接指南](https://open.chanjet.com/md/docs/file/apiFile/tcloud/tjrzy/tplusguide)

## 下一步需要取得的最小材料

这是一份实施输入清单，不是现在向用户重复索要许可。先复用其已有软件、账号与授权；当前未取得的材料应标为待确认。

- 客户实际产品、部署版本/补丁、生产与库存模块、API 模块/服务的开通范围。
- 官方目标接口文档：订单读取、物料/BOM 读取与变更、生产单/派工单创建、库存与领退料、报工/质检；逐个列出支持的动作和状态限制。
- 测试账套、最小权限应用、样本单据及字段字典，尤其物料编码、单位、组织、仓库、工序、人员、批次、BOM 版本。
- 鉴权续期、限流、分页/增量条件、消息签名/重试、来源唯一编号、重复提交处理、业务失败后的回查办法。
- 文件交换如需采用，应取得当前版本的真实模板、编码/单位要求、导入错误回执和去重规则。

KANPACE的工牌“已接收”只是通信回执，不能产生 ERP/MES 完工或报工。应由实际开工/报工事件与工艺、数量、人员校验形成业务记录，再调用经过授权的对应接口；ERP 保存、提交、审核、入库应是可追踪的独立动作。

## 核验限制与机器可读数据

部分官网采用动态页面：精斗云、YonBIP 的本轮公开页面不足以完整展开所有业务字段；智造 3.0 文档明确提供机器可读索引，但直接获取索引遭遇站点访问限制。本稿未绕过登录/访问限制，也未将不可访问误写成“没有接口”。未纳入只由经销商、集成商、个人博客或第三方 GitHub 项目证明的接口与 MCP 结论。

同目录 `integration-domestic.json` 提供 13 条记录，字段为 `id/name/category/interfaces/objects/access/mcp/evidence/next/sources`，用于本地 Web 筛选矩阵。这个 JSON 描述研究结论，不代表软件已经安装连接器或完成实连。文档与 JSON 的核查日期均为 2026-09-04。
