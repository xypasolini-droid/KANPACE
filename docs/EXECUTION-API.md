# 部分进度、暂停恢复与插单执行 API

本契约适用于本机 Web 服务。更新日期：2026-09-04。所有写接口沿用本站 JSON、同源检查和 SQLite `BEGIN IMMEDIATE` 事务。测试仅使用临时数据库，不修改现有生产或演示记录。

## 数量与状态

任务 `quantity` 是原任务总整件数，保持不变。当前生产任务只允许整件数量；材料报价中的米、平方米、千克等计价单位不改变任务的件数单位。`completed_quantity` 是累计实际完成、可交接的整件数，须为 JSON 数值、有限非负整数，不能减少或大于原数量。完成半件时登记 `0` 并在交接说明中写明做到哪道步骤；不能用 `0.5` 表示完工。

`remaining_quantity = quantity - completed_quantity`。登记数量达到总数仍保留 `in_progress`，必须显式完成整项任务才成为 `done`，前置工序也只有 `done` 才放行。未完成所有件数的工序不允许下游分批开工；分批流转需另行建模批次。

原有部件复核、生成、发布检查已经拒绝 `1.5` 等非整件数量；历史 `2.0` 这样的数学整数保持兼容。若外部修改数据库产生真正的小数任务数量，报工会返回明确 409，要求核对部件数量后重新生成并发布任务，不会猜测计量单位或将半件算完成。原始小数可以作为待核对导入数据留存，但不能发布执行。

旧存储任务没有进度字段时，API 提供兼容默认数值，同时 `progress_recorded=false`，界面/工牌应显示“未记录”，不可当成已核实的 0 件。旧 `done` 的兼容数值等于总数量，仍不是新的逐件报工。新任务初始化 `0/true`；主动进度登记或整项完工变成 `true`。默认补齐不添加生产事件。

## 任务字段

| 字段 | 类型与含义 |
|---|---|
| completed_quantity / remaining_quantity | 累计完成、剩余整件数；上述 `progress_recorded` 为可信标识 |
| progress_recorded | 布尔，是否存在明确的初始化/报工数量 |
| priority | 整数 0 普通、1 优先、2 加急、3 特急 |
| pause_reason | `null` 或 `material / quality / equipment / urgent / other` |
| pause_note | 当前暂停原因说明，字符串，最多 1000 字符 |
| handover_note | 最新现场交接/进度说明，字符串，最多 2000 字符 |
| paused_at / resumed_at | ISO 时间或 null；保留最近一次暂停/恢复时间 |
| interrupted_by_task_id | 本次原子切换目标任务 ID 或 null |
| execution_version | 0..2147483647，执行/派工/优先级变动递增；不是图纸版本 |
| carried_from_task_id / carried_from_revision | 未受影响工序继承到新版时的前版来源 |

完整历史在 `events` 中按 `details.task_id` 关联，记录前后数量、原因、交接、切换双方和执行版本。恢复时清空当前暂停分类/原因与当前插队目标，但原说明保留在历史事件中，进度和交接内容不清零。新版未受影响工序继承进度、暂停和优先级，并可沿 `carried_from_task_id` 追溯历史；受影响任务归档保留原进度，新任务从 0 开始，禁止自动继承未经审核的旧版半成品。

## 写接口

下列接口默认返回 `{ "task": { ... } }`。所有新 UI 请求应携带 `expected_execution_version`。旧客户端可省略，属于兼容模式，不具备乐观并发保护。类型或范围错误为 400；状态、前置条件或版本冲突为 409，沿用 `{error,details}`。

| POST 路径 | JSON 请求 | 行为 |
|---|---|---|
| `/api/tasks/{id}/progress` | `completed_quantity, note, expected_execution_version?` | 仅执行中；必填进度/交接说明，累计登记，不自动完工 |
| `/api/tasks/{id}/pause` | `reason, note, handover_note, completed_quantity?, expected_execution_version?` | 待执行/执行中变为 blocked；三项文字/分类必填。待执行不能增加完成数 |
| `/api/tasks/{id}/resume` | `note, handover_note?, expected_execution_version?` | blocked 变为 in_progress，必填解除依据；交接省略即保留 |
| `/api/tasks/{id}/priority` | `priority, reason, expected_execution_version?` | 当前已发布任务调整优先级，必填依据；不自动开工、不自动暂停任何任务 |
| `/api/tasks/{id}/switch` | `target_task_id, reason, note, handover_note, completed_quantity?, target_note?, expected_execution_version?, target_expected_execution_version?` | 同事务暂停当前并开工目标；目标 paused 时 target_note 必填 |

原子切换返回 `{task: 暂停后的原任务, target_task: 开工后的目标任务}`。原任务须正在执行，目标须为另一项待执行/暂停任务，双方同一负责人。先检查双方执行版本、有效已发布图纸版本、目标前置工序和负责人技能，再写两个任务和审计事件；任一失败整体回滚，原进度也不保存。每个工人只允许一项任务处于执行中；切换检查忽略即将暂停的原任务，但不会忽略第三项在制任务。跨项目、多技能跨工种切换可用，条件相同。

直接开工和恢复也检查当前已发布版本、前置工序全部完成、负责人存在且具备技能，以及该人没有其他进行中任务。不能仅凭 `ready`、优先级、下发成功或设备收到任务判断可以开工。暂停/优先级不启动设备生产动作。设备 ACK 仍只表示收件，不写生产完成事件。

## 兼容状态与分派

原 `/api/tasks/{id}/status` 接口保留：

- `in_progress` 开工；从 blocked 恢复必须填写 `note` 作为解除依据。
- `blocked` 必须有 `note`。旧请求未提供新字段时分类为 `other`，交接说明使用 `note`，不改数量。
- `ready` 仅从 blocked 恢复，必须有解除依据，并重新核查有效版本、前置工序、技能；尚有其他在制任务时可回到队列，但不能同时开工。
- `done` 仅从 in_progress。省略 `completed_quantity` 表示原有“确认整项全部完工”，将累计数量设为原数量；显式提供时必须恰好等于原数量。质检/整柜电气检验仍要求独立填写检验结果。重复 done 不新增事件，不递增版本。

`assign` 新增可选 `expected_execution_version`，更换负责人递增执行版本；进行中任务仍须先暂停。审核中的草稿可做规划分派，但不能执行。自动分派按优先级降序处理未分派任务，再用技能和剩余预计工时/人员容量选择负责人；不会开工或越过工艺依赖，不把暂停任务的剩余工作丢出在途负载。

## 队列

`GET /api/tasks/queue?person_id=&project_id=&from_task_id=` 返回 `{tasks:[...],sort:"priority_desc_then_created"}`。前两项过滤可省略，from_task_id 用于预览一次原子切换。稳定排序为优先级降序、创建时间升序，同时间保持保存顺序。

每项附加：

- `can_start`、`start_blockers`：直接开工资格及原因。暂停任务一律提示须填写解除依据；当前进行中任务不重复显示可开工。
- `resolution_required`：目标是否暂停，需要恢复/切换解除说明。
- `can_switch`、`switch_blockers`：指定原任务后，忽略该原任务占用，完整检查目标硬条件。暂停目标可能 `can_switch=true`，但仍须提交 `target_note`；没有原任务则不可切换。

队列保留未归档、状态 ready/blocked/in_progress 的任务；旧版本或待重新发布的承接任务会带明确阻断原因，不伪称可以执行。队列只作预览，写入时再次检查，版本冲突须刷新后由用户重试，不能静默覆盖。

导出任务 CSV 追加原数量、已完成/剩余数量、进度已记录、优先级、暂停类别/原因及交接说明；旧未记录数量留空。JSON 导出保留完整任务和事件。
