# KANPACE USB 工牌 API（v1）

## 图片查看扩展

- `GET /api/projects/{id}/badge-media?task_id={task_id}`：本项目去重后的施工图、效果图目录与来源。可选任务必须属于该项目。
- `GET /api/documents/{id}/badge-image`：已登记图片的同源 inline 预览，使用实际图片 MIME，不接受外部路径。
- `POST /api/device/images`：`{project_id,asset_ids:[id],mode:"preview",task_id?:id}`。每次施工图与效果图各最多一张，USB 连接且固件 `image_support:true` 时创建后台传输。启用账号后仅管理员、主管可发送。
- `GET /api/device/images`：`{transfer}`，状态为 `preparing/sending/received/error/empty`；`progress` 是传输比例，`completed_images` 是已经收到完整校验回执的张数。`empty` 仅表示自动附图未找到可用来源。
- `GET /api/device/image-status`：读取实际工牌 `image_ack/action=status`，返回可用图册、显示图种、解码缩放比例及存储状态。它与本地传输记录分开。

`mode:"task"` 还要求有效已发布任务，以及工牌当前任务、项目和版本一致。手工预览不发布任务、不报工。错误偏移、来源更新、版本变化、设备变化或错误摘要均不产生成功收图状态。详细 USB 帧及原子存储约定见 [IMAGE-PROTOCOL.md](../firmware/goldenmorning-display/IMAGE-PROTOCOL.md)。

## 连接与任务接口

GET `/api/device` → `{device:{state,connected,port,baudrate,device_id,chip,firmware,protocol,last_seen,last_error,dependency_available},ports:[{port,description,manufacturer,vid,pid,serial_number}]}`。
`state`：`disconnected` / `connecting` / `ready` / `incompatible` / `error`。只有 `ready` 才能发任务；`connected` 也只有完成本协议 hello 时为 true。GET 不自动打开串口。

POST `/api/device/connect` `{port,baudrate?:115200}` → 上述形状。仅允许当前枚举的 USB 串口，发现与握手共最多 4 秒。打开后先只读；收到无 `request_id`、`protocol=1`、`firmware=cabinet-badge-1`、`chip=ESP32-C3` 且设备编号有效的主动公告后，才发送请求式 hello 验证同一设备。未知/旧固件到期标记 incompatible，期间串口写入为 0 字节；失败返回 HTTP 409/503，`{error,details:{device,ports}}`。
POST `/api/device/disconnect` `{}` → 上述形状。

POST `/api/tasks/{task_id}/send-device` `{test_mode:true|false}` → `{delivery,device}`，不修改生产任务状态。不传默认 false；演示项目强制 test_mode=true。
任务必须项目 released、task.revision===project.revision===released_revision，且任务未 archived/status 非 done、invalidated。连接已验证才发。

GET `/api/device/deliveries` → `{deliveries:[delivery]}`，按最近优先，最多 100 条。
`delivery` 字段：`id`, `request_id`, `task_id`, `project_id`, `project_name`, `task_title`, `trade`, `revision`, `device_id`, `port`, `test_mode`, `status`, `created_at`, `sent_at`, `received_at`, `error`, `payload`。
状态：`queued`（已登记）、`sent`（串口写出，未确认接收）、`received`（收到并匹配设备回执）、`timeout`（8 秒未等到确认）、`failed`（断开/写入失败等）。只有 `received` 可显示“设备已接收”；任何状态都不是开工或完工。

USB NDJSON 115200：
- device 主动公告 `{type:'hello',protocol:1,device_id,chip:'ESP32-C3',firmware:'cabinet-badge-1'}`（无 request_id，兼容固件周期广播）
- host 在有效公告后才写入 `{type:'hello',protocol:1,request_id}`
- device `{type:'hello',protocol:1,device_id,chip:'ESP32-C3',firmware:'cabinet-badge-1',request_id}`
- host `{type:'task',protocol:1,delivery_id,request_id,test_mode,task:{id,project_id,project_name,revision,title,trade,quantity,hours,assignee,acceptance,source,status}}`
- device `{type:'ack',protocol:1,delivery_id,request_id,task_id,revision,device_id,received:true}`
`assignee`为姓名，`source`原始来源对象。正常载荷不截断，超出 8192 字节拒绝发送。连接只发本协议 hello，绝不发送串口任意命令。回执身份和 delivery/request/task/revision 全匹配才计接收。

## WiFi 扩展
`device` 追加 `transport:'usb'|'wifi'`, `host`, `wifi`（下述无线状态，无密码/token）。
POST connect 支持 `{transport:'wifi',host:'192.168.x.x'}`；只允许 USB 已验证状态记录的 RFC1918 IPv4，固定 TCP 80。Bearer token 必须此前由本机 USB 配置下发。完成同一设备身份握手才 ready。
POST `/api/device/wifi-scan` `{}` → `{wifi,device}`；`wifi.networks:[{ssid,rssi,secure}]`, `scan_pending`。首次可返回 pending，几秒后再次请求读完成结果；固件缓存 30 秒。
POST `/api/device/wifi-config` `{ssid,password}` → `{wifi,device}`；异步开始连接；`wifi.configured`只说明配置被工牌接受，需刷新状态看到 connected 与 ip。
GET `/api/device/wifi-status` → `{wifi,device}`；USB就走USB命令，WiFi则走认证HTTP `/cabinet/wifi_status`。未连接时返回缓存且 `cached:true`。
`wifi`字段：`connected,configured,ssid,ip,rssi,device_id,networks,scan_pending,cached,observed_at`。缓存非实时在线证明。
WiFi SSID/password只在USB配置请求出现；电脑不保存WiFi密码。每设备随机 token 只保存 `data/device-secrets.json`（权限600），绝不进入状态、任务payload、事件、回执。
WiFi发任务可直接返回`delivery.status='received'`（同步HTTP真实ACK）；无有效ACK仍只表示sent/timeout/failed。delivery新增`transport,host`。

## 连接失败与能力边界
- USB由本地Python服务持有串口，不依赖浏览器Web Serial权限；一次连接一个工牌。
- WiFi状态或发送请求失败后，`device.state=error`、`connected=false`、`wifi.connected=false`、`wifi.cached=true`，不会继续显示已在线。可重新连接重做身份握手。
- `device.last_seen`、`wifi.observed_at`仅是最近一次验证回复的时间，不代表持续在线。
- 工牌接收回执不是开工或完工；本版本不从设备回执触发生产报工。
- 旧 SparkLink 固件会把单个字符解释成互动命令，因此 USB 连接先执行无写入的被动发现。未收到兼容固件主动公告时，不会写入 JSON 或其他串口命令，并提示先升级固件；兼容公告本身也不等于握手完成。
- WiFi HTTP 用于同一可信工厂局域网。设备配对Token存储在本地私有文件，未实现TLS或互联网远程工牌接入。

## 自动化验证
`python3 -m unittest discover -s tests -p 'test_device*.py' -v`

测试使用标准库 POSIX pseudo-terminal 和本地 HTTP 模拟工牌，无须打开物理USB端口。覆盖旧 ASCII 固件零写入、错误公告不启用写入、协议握手、版本与发布校验、串口写出/匹配接收/超时/断线、错误和重复回执、超长及损坏帧、同源API限制、WiFi配置秘密隔离、令牌权限、LAN地址限制、HTTP身份校验与拒绝重定向、状态故障后清除在线标记、任务状态不被回执改动、服务重启恢复。实板验证由单独硬件联调记录说明。

## 固件 v1.3 进度、暂停与插单字段（protocol 仍为 1）

`task` 增加以下可选字段。旧任务仍可接收；v1.3 固件才能按新布局显示。派送前使用服务的任务别名/兼容处理取得真实记录，设备回执只更新投递记录，不推进生产状态。

| 字段 | 类型与约束 | 含义 |
|---|---|---|
| `progress_recorded` | boolean，旧记录默认为 false | 是否有实际进度记录；不是是否收到任务 |
| `completed_quantity` | integer 0…1,000,000,000 或 null | 累计完成且可交接的整件数 |
| `remaining_quantity` | integer 0…1,000,000,000 或 null | 从总数量减累计完成数派生 |
| `priority` | integer 0…3 或 null | 0普通、1优先、2加急、3特急；缺失为未标记 |
| `pause_reason` | null 或 `material`/`quality`/`equipment`/`urgent`/`other` | 缺料、质量、设备、急单插队或其他原因 |
| `pause_note` | UTF-8 string ≤4096字节或null | 暂停说明；业务API另限制1000字符 |
| `handover_note` | UTF-8 string ≤8192字节或null | 交接说明；业务API另限制2000字符 |
| `paused_at`、`resumed_at` | string ≤64 UTF-8字节或null | 服务生成的ISO时间；设备只保留/显示 |
| `interrupted_by_task_id` | string ≤128 UTF-8字节或null | 导致换单的任务ID |
| `execution_version` | integer 0…2147483647 或null | Web执行记录版本，与工程revision分开 |

当`progress_recorded=true`时，`quantity`必须为有限非负整数，两个进度值必须为整数、`completed_quantity≤quantity`且两者合计严格等于总数。整数值的旧JSON浮点表示会规范为整数，不取整截断。当`progress_recorded=false`时，桥接器发送两个进度值为null，工牌显示“未记录”，同时保留原总数量；这样历史默认0不会被当作已核实产量。所有新字段整体可省略以兼容旧protocol1任务。

已做达到总数仍不表示已完工；暂停使用现有`status:'blocked'`。工牌主屏显示已做/剩余、优先级和原因，完整暂停与交接说明自动续页。例：

```json
{
  "quantity": 10,
  "progress_recorded": true,
  "completed_quantity": 3,
  "remaining_quantity": 7,
  "priority": 3,
  "status": "blocked",
  "pause_reason": "material",
  "pause_note": "缺少侧板，待仓库补料",
  "handover_note": "已做3件已标记，余下7件保留原工位",
  "paused_at": "2026-09-04T12:00:00+00:00",
  "resumed_at": null,
  "interrupted_by_task_id": null,
  "execution_version": 2
}
```

示例是嵌入完整`task`对象的扩展字段，不是独立可投递帧。整个NDJSON帧含换行上限仍为8192字节，JSON编码产生的转义也计入；单字段合规但总帧超限时仍拒绝发送，绝不静默截断。USB与HTTP采用相同校验、字段与回执契约。

本次31项设备自动化测试通过，包含真实部分进度/暂停/交接传输、历史未记录、范围与合计拒绝、超长载荷拒绝且原记录不截断、USB/HTTP ACK不改生产状态。测试基于本地模拟串口/HTTP；实板验证另记。

### v1.3.1显示兼容说明

v1.3.1不改变上述协议和业务字段，只精简工人页面并将网络入口移至右上Wi-Fi图标。数量合卡；空项、内部编号与raw来源隐藏但原始payload仍完整保存。`display_page`/`display_pages`反映新分页，不能使用旧版本固定页码导航。
