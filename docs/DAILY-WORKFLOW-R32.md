# KANPACE R32 当日流程与胸牌贴标 API

此版本使用现有 SQLite 工厂实例、排程 `plans`、生产任务 `tasks`、工牌下发 `device_deliveries` 与执行事件。没有复制一份独立的生产进度。所有新增写入由现有 HTTP 写事务统一提交，返回成功时已经落盘。

软件使用顺序：资料导入 → 按日排程 → 胸牌派工 → 现场执行 → 完工贴标 → 归还胸牌。标签可以在派工前准备、打印。实际工牌任务继续通过现有 `POST /api/tasks/{id}/send-device` 发送，新增领取登记本身不会发送任务或伪造设备回执。

## 当日工作包

`GET /api/daily-workflow?date=2026-09-14&factory_type=cabinet`

可选筛选：`date`（省略则使用服务主机本地日期）、`person_id`、`project_id`、`factory_type`（`cabinet`、`machinery`、`site`）。日期必须为完整有效的 `YYYY-MM-DD`。

返回 `date`、`tasks`、`labels`、`handovers`、`summary`、`unscheduled_count`。任务来自已保存排程当日的 `allocations`；只有没有 allocations 的旧排程才使用原有显式起止日期。项目需为已发布、未关闭；任务/排程/已发布工程版本和负责人必须一致。不把未来任务、未排程任务或演示订单伪装成当日任务。完成任务仍保留于当日工作包，供贴标与交接；正常待发任务标志 `can_dispatch` 为 false。

任务保留原字段，并附：

```json
{
  "project_name": "台湾珠宝柜",
  "part_name": "左侧板",
  "person_name": "木工甲",
  "plan_id": "plan_example",
  "plan_minutes": 60,
  "scheduled_date": "2026-09-14",
  "can_dispatch": true,
  "labels": {
    "expected": 2,
    "total": 2,
    "confirmed": 0,
    "pending": 2,
    "next_label_id": "label_example",
    "next_label_code": "KP-EXAMPLE"
  }
}
```

`pending` 包含尚未准备的标签，不能跳过生成标签而绕过归还检查。`unscheduled_count` 是缺少有效排程的未完成真实任务数。

## 标签准备、查找、确认

`POST /api/daily-workflow/labels/prepare`

```json
{"date":"2026-09-14","task_ids":["task_example"]}
```

选择 1～200 项不重复的有效当日任务，一次最多准备 500 张不同实体标签。当前只支持明确的整数件数。实体标签按“项目＋部件编号＋工程版本＋件序号”唯一识别一件部件。没有部件编号的整项任务才使用任务编号作为后备身份。开料、封边等工序引用同一部件时使用同一张标签，不因换工序、换日期、重新打印而建立第二个工件。不同工序的件数不一致时要求核对，不自动补出多余工件。

标签物理身份保存在 `daily_labels`；每一道工序的确认单独保存在 `label_confirmations`。上一工序确认不会让下一工序自动完成，也不会让下一工序的核对状态自动通过。兼容旧任务标签：原纸上编号继续可查，按实体身份选择一个主编号打印，保留原阶段确认记录和别名，不删除历史。

返回 `labels`、`created_count`、`reused_count`、`physical_label_count`。`labels` 按任务提供上下文，所以同一实体 ID 可以在两个阶段行中出现，打印时必须按 `id` 去重。每行的 `task_id`、`task_title`、`trade`、`status` 和 `confirmed_at` 属于该行当前工序；`origin_task_id` 保留最初准备任务。状态为 `prepared` 或 `confirmed`。`summary.label_count` 为不同实体标签数，而 `labels_pending` 为工序待确认件次，不能把后者解释为需要重贴的纸张数。

实体快照同时包含 `part_id`、`cabinet_name`、`part_name`、`material`、`dimensions_mm:{length,width,thickness}`、`dimension_unit:"mm"`、`unit:"件"`、`piece_count`、`revision`。没有工程依据的字段留空。部件数据中的 `unit` 是尺寸单位，不能用来把数量显示成“2 mm”。前端参考模板为工件 80 × 50 mm、货架 80 × 30 mm；打印机纸张与缩放需匹配实际标签纸。

二维码内容是 `KANPACE:LABEL:label_<随机编号>`，不含源文件路径、人员密码、设备令牌或客户图纸。前端使用随产品分发的 QR 编码器生成真实可扫描二维码；此 API 不需要额外 Python QR 依赖。

`GET /api/daily-workflow/labels/{id}?task_id=task_example` 返回 `{label}`。`task_id` 可省略，省略时使用最初准备任务；查询后续工序应明确提供当前任务。`current` 指出标签工程版本是否仍有效。历史可查不代表可继续执行。

`POST /api/daily-workflow/labels/{id}/confirm`

```json
{"task_id":"task_example","revision":1}
```

必须匹配当前任务的部件身份和整数工程版本，任务必须已经通过现有完工校验且数量全部完成。同部件后续工序可以使用原标签；其他部件、其他项目、旧版、尚未完工的工序均拒绝。首次确认建立该标签的工序确认记录并递增当前任务 `execution_version`，保留原生产状态和完成数量；同一工序重复确认返回 `duplicate:true`。Web 前端确认后需要刷新任务状态，继续使用新的执行版本。

此记录表示操作者确认已贴对应标签；系统没有通过没有扫描器的 C3 自动识别实体标签。需要操作者核对屏幕与纸上的短码。

## 货架标签与工件位置

`GET /api/daily-workflow/locations` 返回 `{locations}`。

`POST /api/daily-workflow/locations` 接受 `{"code":"01-007","name":"木工区 A架"}`，名称可省略。编号为 1～24 位字母、数字或短横线，统一转大写并在本工厂内唯一；相同名称与编号重试返回 `duplicate:true`，同编号不同名称返回冲突。返回 `{location,duplicate}`。货位包含 `id`、`code`、`name`、`active`、`version` 和 `qr_payload:"KANPACE:LOCATION:<id>"`。

`GET /api/daily-workflow/locations/{id}` 返回货位与当前绑定的实体标签。

`POST /api/daily-workflow/labels/{id}/location` 接受 `{"location_id":"location_example","expected_location_version":0}`。首次为 0，此后使用标签返回的 `location_version`；相同重试幂等，过时版本不能覆盖别人刚登记的货位。更新实体标签 `location_id`、`location_version` 和位置审计，所有后续工序看到同一 `current_location`。

货位建立和绑定需要物料管理权限。此操作表示已确认的存放位置，不自动创建领料、库存数量、财务出入库或完工事件。已关闭项目和旧版标签不能新绑定位置。

## 胸牌领取与归还

`POST /api/daily-workflow/handovers/issue`

```json
{"date":"2026-09-14","device_id":"badge_01","person_id":"person_01","task_ids":["task_example"]}
```

任务必须属于该人员与所选日期。胸牌或人员不能同时有第二条未归还记录；相同请求重试返回原记录。任务已经全部完成则不再创建新领取记录。领取编号、日期、人员、胸牌编号、任务清单、原始工程版本和时间均持久保存。

返回 `{handover,duplicate}`。`handover` 包含 `version`、`status`（`issued` / `returned`）、`unresolved_tasks` 与 `can_return`。领取状态是实物保管记录，USB 是否真正收到某项任务仍看原设备下发回执。

`POST /api/daily-workflow/handovers/{id}/return`

```json
{"expected_version":1}
```

领取任务未完成、件数异常、图纸任务版本变更或标签未全部确认时返回 409，并在 `details.unresolved_tasks` 列出具体任务及原因。通过后保存归还时间并递增版本。相同归还的重试不再写入第二个归还事件。不会为了归还而把暂停任务自动记为完工。

## C3 USB 协议的兼容扩展

原任务卡与业务 ACK 的 `task` 增加可选 `daily`：

```json
{
  "date":"2026-09-14",
  "scheduled":true,
  "position":1,
  "total":3,
  "remaining_tasks":2,
  "return_ready":false,
  "labels":{"expected":2,"total":2,"confirmed":0,"pending":2,
            "next_label_id":"label_example","next_label_code":"KP-EXAMPLE"}
}
```

新增 `execution_event.action = "label_confirm"`，必须有 `label_id`；其余事件标识、`delivery_id`、`device_id`、任务及执行版本沿用原契约。服务端检查真实接收的非测试下发记录、设备、任务、负责人和工程版本，再执行同一标签确认服务。事件唯一编号重试按原事件账本幂等处理；同一编号不同内容被拒绝。

首个确认成功递增 `execution_version`，满足固件现有严格 ACK 版本规则。`execution_allowed:false` 的完成任务只可使用专门的贴标操作，不能重新开工。任务切换继续用现有 Web 暂停/切换服务和任务下发，未添加在串口读取线程里自动下发下一任务的副作用。

`daily` 是服务端当前快照。设备重启缓存或离线时，不把旧 `return_ready` 当作当日全部完成的新证据。当前 C3 任务卡持久缓存一项任务；本改动未宣称实现整日多任务离线队列、摄像头扫描或 Wi-Fi 报工。

## 权限与验证

沿用工厂独立数据库和访问会话。启用账号后匿名 API 返回 401；工人/质检的当日列表及标签读取、确认限制为本人任务，不能准备批量标签、登记领取或替他人确认。准备标签需排程权限；领取/归还需设备管理权限。写入保留同源、锁内二次授权与事务提交保护。普通 Web 请求不能伪装 `device_id` 为硬件贴标记录。

`tests/test_daily_workflow.py` 用临时数据库和临时 HTTP 端口验证日期、工厂类型、持久化、重复准备/确认、数量不变、错误任务/版本、跨工厂编号、领取冲突、归还拦截、角色权限、同源保护和设备事件幂等。`tests/test_badge_execution.py` 使用 POSIX 伪终端回归业务 ACK；不连接物理胸牌。
