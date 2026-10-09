# R33：按项目向人员胸牌派工

本模块运行在每个工厂的独立 Store 中。队列持久保存在服务器；ESP32-C3 仍只保存一项当前任务。建立队列、串口发送、设备收件、图片接收、开始加工、完工、确认工件标签是不同事实。建立队列不会伪造设备回执或生产进度。

## 主流程

1. 在项目派工预览查看当前已发布版本的未完成任务，按负责人分组。
2. 每人绑定一块已注册胸牌。一块胸牌不能同时归属两人。设备须先通过真实握手、已有连接登记或持久设备凭证被识别，不能随意填写编号冒充在线。
3. 用户确认后建立整个项目的人员队列，也可带日期，只选该日真实排程内的任务。同一个人可拥有多个项目队列。
4. 每轮调度使用任务最新 `priority`（高优先）、`schedule_position`（小序号优先）、计划开始时间，满足工程前序与 `schedule_dependencies` 后决定下一项。正在加工的任务优先保持。队列不会自动修改任务状态。
5. 每次替换前通过 USB `get_task` 核对设备上实际任务及未确认报工。进行中、暂停、完工待贴标的任务受到保护；显式暂停切换可派发指定目标。已收件但未开工的 ready 任务，只有新固件明确声明 `safe_ready_replacement:true`、双端均 ready 且设备报工队列为 0 时，可随排程优先级被替换。旧固件保持保守等待。
6. 暂停插单后恢复原任务，需要重新发送并取得新回执与图片确认。历史 ACK 不代表原任务仍在屏幕上。
7. 前一工序完成且当前工序对应的物理工件标签确认完毕后，后续工序才能派发。标签实体可跨工序复用，但确认是逐工序的。

本版本仅有一个实际 DeviceBridge 连接，因此真实在线数量最多 1。其他已注册胸牌明确显示离线，所属人员队列等待该设备连接。项目图文派工使用 USB；无线图片批量传输不在本次已验证能力内。

## HTTP 接口

所有接口沿用现有工厂实例认证、来源检查与数据库事务；写接口需要 `device` 操作权限。当前实例角色模型的普通读取仍是实例内共享读取，跨工厂依赖独立实例存储隔离。

| 方法与路径 | 输入 | 输出/规则 |
| --- | --- | --- |
| GET `/api/projects/{id}/dispatch-preview` | 可选 `date=YYYY-MM-DD` | `project,scope,date,workers,devices,summary,blockers,warnings,active_dispatch`。草稿/改版状态仍返回原队列入口，发布问题放在 blockers 中。 |
| GET `/api/device-bindings` | 无 | `bindings,devices`；devices.connected 是实际连接状态。 |
| POST `/api/device-bindings` | `person_id,device_id,expected_version` | `binding,duplicate`；首次版本为 0；一人一牌，旧版本 409。存在活动队列时不可换绑。 |
| POST `/api/projects/{id}/dispatch` | `expected_revision,request_id,date?` | `dispatch,duplicate`；request_id 用于不确定请求的安全重试。相同编号不同内容为 409。 |
| GET `/api/project-dispatches/{id}` | 无 | `dispatch`，包含持久版本、人员队列、每项任务状态、delivery_id、transfer_id、图片数量、警告与失败原因。 |
| POST `/api/project-dispatches/{id}/retry` | `{}` | 明确重试失败项；增加 attempt，新发送不会错误恢复上一次失败记录。已停止/结束队列 409。 |
| POST `/api/project-dispatches/{id}/cancel` | `expected_version` | `dispatch,duplicate`；只停止未来派发，不改变任务进度、已收件任务、图片、标签。已停止/完成幂等返回；活动队列旧版本 409。 |

`summary` 包含 `worker_count,task_count,required_badges,connected_count,matched_connected_count,unbound_count,missing_connection_count`。

队列状态：`queued,active,partial_failure,completed,cancelled`。
任务条目状态：`queued,waiting_device,waiting_predecessors,waiting_connection,waiting_current_task,awaiting_receipt,images_pending,active,awaiting_labels,completed,failed`。

失效工程版本、归档项目、负责人变化、已撤销账号权限、换绑、设备变化均会阻止后续发送。工程改版后可先停止旧队列，复核并发布新版后另建队列。后台提交使用队列版本检查，物理发送前再次检查队列未停止、任务执行版本/负责人/工程版次/设备身份，避免并发覆盖人工处理。

## 自动图文资料

仅从当前项目资料目录选择：先取与当前任务/构件关联的施工或工程图，再取本项目效果图，其后补充其余关联图。效果图用于看整体，施工图/工程图用于当前任务作业；不会把其他项目或无任务关联的工程页自动下发。

- 旧能力：最多 2 图，各一种；遗漏数量和原因会显示。
- 六图固件：握手 `max_images_per_task:6` / `image_slots:6`，每张 `image_begin` 带 `gallery_slot:0..5`。
- 总 JPEG 字节预算最高 660000，单图仍不超过 180000；编码时按本批张数分配预算。无法满足可读性/容量时明确失败，不虚报完整送达。
- 完整字节、SHA-256 和 commit ACK 才计入 `completed_images`；任务 ACK 不等于图片 ACK。无关联图片时明确提示补充资料。
- 图像生成及传输只使用实例内文件；新模块未引入额外第三方依赖，沿用项目已有 Pillow/pyserial 等组件与原许可证说明。

## 本轮验证

隔离临时数据库、模拟串口端和图像端测试，无物理开发板写入：

- 14 项队列测试：一人一牌、离线计数、持久恢复、真实收件/图片/完工/标签分离、多项目顺序、排程动态重排、保护执行中任务、ready 替换及未确认报工/旧固件保护、暂停返回原任务、新版停止重建、前序贴标门禁。
- 1 项实际 HTTP 集成测试覆盖匿名拒绝、角色拒绝、跨来源拒绝、日期过滤、请求幂等、版本化停止和没有硬件发送。
- 与图像目录、图片传输、USB 报工回归合计 68 项通过。其中六图用实际 Pillow 编码，验证独立槽位、完整字节、总容量、关联选择和遗漏提示。

设备真实收件、屏幕可读性和实际 USB 六图显示需连接实体胸牌后验证，不能用模拟测试替代。
