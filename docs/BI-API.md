# 生产 BI 只读接口与统计口径

`GET /api/analytics?project_id=&trade=&days=14`

项目与工种参数可省略；工种为柜序八类标准工种，`days` 为 1–366 的整数，只控制历史趋势天数。未知项目返回 404，无效工种或天数返回 400。接口以一致的数据库读事务读取已有记录，不写任务、生产事件或设备回执。日期使用服务电脑本地时间，`as_of` 是快照时间，`scope.timezone/date` 提供日期口径。

## 当前生产与历史趋势

当前指标只包含项目处于 released、released_revision 与 revision 一致、任务版本与其一致、任务未归档、状态为 ready / in_progress / blocked / done 的任务。草稿、待重审、失效和归档版本不计入当前生产工序数。

未筛选工种时，`project_total` 包含项目筛选范围内各阶段项目；`production_project_total` 是拥有上述当前生产任务的项目数。筛选工种后，项目范围限制为涉及该工种当前生产任务的项目。`in_production_projects` 要求当前范围仍有未完成工序。

项目完成比例是**筛选范围内已完成工序数 / 总工序数**，不是完成产品件数或整单交付比例。筛选工种后，项目风险也只评估这个工种；不能把木工工序全完成解释为订单已交付。

历史趋势按每个任务首次明确完工的审计事件去重，包含历史归档版本。版本承接、同任务重复 done、部分数量登记和设备 ACK 不新增完工次数。只有 done 状态却没有完工事件的任务不会补造趋势。不能解析时间的事件计入 `unknown_date_events`，不猜日期。每天的 `task_ids` 可在 `task_index` 钻取；历史项标记 `historical=true`，不因此增加当前总数。

## 响应字段

| 字段 | 内容 |
|---|---|
| as_of / filters / scope | 快照时间、筛选值、统计口径；scope.demo_tasks 明示当前演示任务数 |
| summary | project_total、production_project_total、in_production_projects、overdue_projects；task_total、done、in_progress、blocked、ready、completion_ratio；计划工时与缺项计数 |
| trade_status | 按 trade 分组的 total、各状态数、task_ids |
| pause_reasons | reason、label、count、task_ids；五类暂停加 unknown（未分类/未记录） |
| people | person_id、name、task_count、计划工时与缺项计数、task_ids；只累计未完成任务，包含人员零负载和未分派行 |
| projects | id、name、due_date、days_to_due、total、各状态数、completion_ratio、risk、risk_reasons、task_ids、demo |
| completion_trend | days 数组（date、completed_operations、task_ids）、total、includes_archived、unknown_date_events、definition |
| progress_coverage | recorded、total、ratio、definition |
| blockers | paused（task_id、reason）、dependencies（task_id、pending_task_ids）、unassigned、skill_mismatch、unique_task_count |
| task_index | 以任务 ID 为键，含标题、项目、工种、状态、负责人 assignee/assignee_name、优先级、数量、进度、暂停/交接、archived、historical、demo |

比例为 0–1，分母为零返回 null；未记录日期返回 null。任务可能同时出现在多个阻断分类中，`unique_task_count` 按任务去重。前置依赖是工艺条件，正常等待也会列出，不直接宣称发生生产异常。

## 计划工时与进度覆盖

summary 与每个人员条目提供：

- `remaining_planned_hours`：全部计入任务工时已知时返回合计，有缺项返回 null。
- `known_remaining_planned_hours`：已知部分小计，须与缺项提示一起展示。
- `unknown_estimate_tasks`：缺少有效估算的待做任务数。
- `unrecorded_progress_tasks`：人员条目统计其待做任务的未记录数；summary 统计当前全部任务的未记录数，与覆盖率一致。

有有效累计进度时，剩余计划工时 = 原计划工时 ×（原数量 − 累计完成数量）/ 原数量。暂停任务保留在负载中。旧任务未记录累计数量时采用原完整计划工时，并标记未记录计数。工时缺失不补零。这只是计划估算，没有采集实际时长，不能称作实际工时、效率或准确交期。

`progress_coverage` 是明确初始化数量或累计报工记录的覆盖率；新任务初始化为零也计入，因此不等于工人主动报工覆盖率。旧未记录任务在 task_index 的完成/剩余数量为 null，不把默认零展示为确认实绩。

## 风险枚举

| risk | 主风险含义（按此优先顺序） |
|---|---|
| completed | 当前筛选范围工序全完成 |
| overdue | 交期早于本地今天且仍有未完工序 |
| paused | 存在暂停待恢复工序 |
| needs_assignment | 存在未分派或技能不匹配工序 |
| due_soon | 距交期 0–3 天，提醒核对安排 |
| no_known_blocker | 当前规则未发现以上风险；不是按时交付预测 |
| unknown_due | 无有效交期，不能判断逾期 |

risk_reasons 保留其他已发现原因。已过交期但当前范围已完工的项目不计“逾期未完”，也不能据此推断曾准时交付。接口没有真实库存、采购到货、财务收入利润、实际工时/OEE或准交率，scope.not_available 明示这些缺失维度。

## 验证

新增 `tests/test_analytics.py` 的 6 项回归通过：空数据与未知比例；部分/暂停/旧记录工时与缺项；当前发布口径与筛选；首次完工去重及历史钻取；逾期与缺失交期；真实 HTTP 校验与只读性。使用固定时钟和隔离临时数据库，不修改现场生产记录。
