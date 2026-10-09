核验日期：2026-09-06（America/New_York）；抓取时 UTC 已到 2026-09-07。本分支共 14 项，结构化结果见 `manufacturing.json` 的 `candidates` 数组。所有接入难度、优先级与场景适配都是研究判断，没有安装或运行候选项目，也没有改生产数据。

建议先保留 KANPACE 的工序状态机、图纸来源/版本门槛、暂停换单和工牌事件链，在两个位置引入开源能力：OR-Tools 负责生成有限资源排程建议，diagram-js 或 bpmn-js 负责工艺模板图编辑。ERPNext、Tryton、InvenTree 用来完善物料、外协、检验和成本的业务模型；客户已使用 ERP 时优先做连接器。frePPLe 是独立 APS 外挂的替代路线，适合已有较完整订单/BOM/库存数据并想继续用 Excel 的工厂。以上是架构判断，不是已完成的集成结果。

必须纠正的许可证/功能边界：

- frePPLe 当前 Community 是 **MIT**，其 8.0.0 发布说明明确在 **2023-06-03 从 AGPL 改为 MIT**。不能引用旧版宣传册把现行版标成 AGPL。当前 CE 包括有限物料/有限产能计划、预测、Excel/CSV/REST、what-if、Odoo 集成；交互甘特、库存优化、交期报价、换型矩阵优化、保质期规划列入商业 Cloud/Enterprise。[当前许可](https://frepple.com/docs/current/license.php)、[版本变化](https://frepple.com/docs/current/release-notes.html)、[功能版别](https://frepple.com/editions/)。
- bpmn-js 不是纯 MIT，当前 bpmn.io license 要求水印保持完整可见且不可改去；diagram-js 为 MIT。两者是前端绘制/建模工具，不能因有流程图就声称已获得可运行的 BPMN 引擎。[bpmn-js LICENSE](https://github.com/bpmn-io/bpmn-js/blob/develop/LICENSE)、[diagram-js LICENSE](https://github.com/bpmn-io/diagram-js/blob/develop/LICENSE)、[官方定位](https://bpmn.io/toolkit/bpmn-js/)。
- Timefold Solver Community 为 Apache-2.0，企业版有多线程求解等额外能力；更容易忽略的是其 **Python Solver beta 已停止主动开发/修复**。KANPACE 若选它，应按 Java/Kotlin 外挂估算，而非承诺 Python 原生集成。[官方Python停止公告](https://github.com/TimefoldAI/timefold-solver/discussions/1698)、[企业功能边界](https://docs.timefold.ai/timefold-solver/latest/enterprise-edition/enterprise-edition)。
- ERPNext 为 GPL-3.0，而底层 Frappe 为 MIT；应分别记账。[ERPNext许可](https://github.com/frappe/erpnext/blob/develop/license.txt)、[Frappe许可](https://github.com/frappe/frappe/blob/develop/LICENSE)。
- Odoo19 CE 为 LGPLv3。已读取官方版本比较表 HTML 的图标：Inventory/MRP/Purchase 两列均勾；Barcode、Shopfloor/Control Panel/Scheduling、PLM、Quality 为 CE叉/EE勾。不能把官方统一文档里的全部制造与质量功能计入 CE。原始表格保存在 `manufacturing-extra-evidence.json` 的 `odoo-editions`。[官方比较](https://www.odoo.com/page/editions)、[许可证](https://www.odoo.com/documentation/19.0/legal/licenses.html)。
- qcadoo CE 为 AGPLv3-or-later；官方 README 把 REST API、现成 ERP/SCADA 连接器、Gantt、仓库物料流、维护计划明确列入商业版。可作为真实 MES 参考，但不能推荐成“免费开源 REST MES 外挂”。[官方仓库](https://github.com/qcadoo/mes)。
- OpenProject17.7 的新 Resource management 为 Enterprise add-on。社区版的甘特依赖日期计算不能等同于工厂人员+设备双资源有限产能 APS。[17.7官方发布说明](https://www.openproject.org/docs/release-notes/17-7-0/)。
- Camunda8.6+ 核心源码采用 Camunda License v1，编译分发是专有许可，生产需要商业版；部分SDK/建模器开源不代表整套引擎开源。Camunda7 CE最终7.24在2025-10-14后不再给社区维护/安全更新，不适合作为新商用系统逃避8许可的选择。[当前组件许可](https://docs.camunda.io/docs/reference/licenses/)、[Camunda7 EOL](https://camunda.com/platform-7/performance/)。

面向三类客户，建议采用以下先后关系（判断）：

| 场景 | 最值得补的能力 | 优先候选 | 暂不引入的完整系统 |
|---|---|---|---|
| 展柜工厂 | 瓶颈工位/班次排程，外协物料与成本，工艺版本 | OR-Tools；frePPLe CE作APS备选；ERPNext/现有Odoo连接器 | 整套ERP/MES替换 |
| 非标机械装配 | 装配前置关系，关键料批次/序列，逐件测试与验收 | OR-Tools；InvenTree；ERPNext/Tryton质量模型 | 没有明确流程引擎需求时不引入Temporal/Flowable |
| 装修现场 | 项目/WBS/工种依赖，工时与里程碑，采购/现场材料回执 | OpenProject参考；KANPACE工艺模板/事件链；ERP接口 | 以制造BOM为中心的完整MES |

质量模型中，Tryton 最值得借鉴的是 **控制点 → 检验 → 异常 → 关联单据阻断/解决或延期** 的显式结构；ERPNext有进料/过程/出货检验与单据提交门槛；InvenTree有批次/序列装配输出与测试结果，但不能把这些称为涵盖审计、CAPA、认证的完整QMS。[Tryton质量设计](https://docs.tryton.org/latest/modules-quality/design.html)、[ERPNext检验](https://docs.frappe.io/erpnext/quality-inspection)、[InvenTree Build](https://docs.inventree.org/en/stable/manufacturing/build/)。

最小接入契约建议（判断）：客户ERP/Excel保留订单、料号/BOM、库存/采购/财务成本的权威来源；KANPACE保留工序执行、图纸版本确认、人员实际工时、缺料/质量阻断、现场回执。计划求解器只接收版本化快照并输出方案。计划发布时再次检查订单/资源/图纸版本，避免求解期间现场变化被覆盖。最先验证插单、缺料、共享人员、班次结束、已开始任务冻结、部分完工和返工，而不是只比较正常情况下甘特图是否好看。

| 候选 | 已核验的近期维护证据 |
|---|---|
| OR-Tools | v9.15，2026-01-12；仓库push 2026-09-06 |
| Timefold | v2.6.0，2026-09-01；默认分支commit 2026-09-03 |
| frePPLe CE | 9.18.0，2026-08-28；commit 2026-09-03；current docs显示9.19，不应当作已发布稳定版 |
| ERPNext | v16.34.1，2026-09-02；默认分支commit 2026-09-07 UTC |
| Odoo | 19.0默认分支commit 2026-09-05；未取得GitHub latest release |
| Tryton | 8.0 LTS官方发布2026-04-21；GitHub镜像默认分支commit 2026-07-29、push2026-09-04 |
| OpenProject | v17.8.0，2026-09-02 |
| bpmn-js / diagram-js | bpmn-js v18.28.0，2026-09-04；diagram-js v15.26.0 release feed更新2026-08-28 |
| Temporal | v1.31.2，2026-07-08；仓库push2026-09-07 UTC |
| Camunda | 8.9.19，2026-09-04；活跃不等于许可适合本任务 |
| Flowable | 8.0.0，release feed更新2026-02-27；仓库REST归档字段未取得 |
| OpenBoxes | v0.9.8-hotfix1，标签页发布2026-08-14；feed在2026-08-17更新 |
| qcadoo | 3.1.19，标签页2026-08-27；仓库REST归档字段未取得 |
| InvenTree | 1.5.2，标签页2026-08-25；仓库REST归档字段未取得 |

逐项维护URL、许可证URL、能力直接官方出处都在JSON。REST抓取中共享未认证出口达到GitHub限额，缺失字段标null；后续用官方release Atom与标签HTML补证。Atom的updated不是必然的发布时间，因此OpenBoxes与InvenTree额外核对标签页的relative-time值。GitHub搜索缓存曾显示qcadoo 3.1.0、OpenBoxes较旧版本，最终以实时Atom/标签页替换，没有把旧搜索摘要作为最终版本依据。
