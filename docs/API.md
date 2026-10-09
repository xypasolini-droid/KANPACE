# 本地 Web API

默认 http://127.0.0.1:8765，单机使用。写请求必须为JSON；同源检查不等于用户身份认证。成功返回JSON对象；失败返回 `{error, details?}` 和对应HTTP状态。网页写入成功后重新读取state。

| 方法与路径 | 参数 / 行为 |
|---|---|
| `GET /api/health` | 健康状态、版本、本地模式 |
| `GET /api/state` | projects、documents、parts、tasks、events、people、settings、capabilities |
| `POST /api/projects` | name、client、due_date、quantity；套数不重复乘入BOM |
| `POST /api/import` | project_id、filename、content_base64；原件最大20MB，同项目内容哈希幂等 |
| `POST /api/parts` | 人工新增project_id、name、material、category、length_mm、width_mm、thickness_mm、quantity、finish等 |
| `POST /api/parts/{id}/review` | approved布尔值、edits对象；来源冲突需要notes或review_note |
| `POST /api/projects/{id}/generate` | 编译当前版本，承接未受影响状态，同版本不重复生成 |
| `POST /api/projects/{id}/release` | 发布门禁、有效版本与不可变快照 |
| `GET /api/projects/{id}/releases` | 历史发布快照 |
| `POST /api/projects/{id}/auto-assign` | 技能及负载派工；返回assignments、skipped、method |
| `POST /api/tasks/{id}/assign` | person_id；null可清空，受技能和状态限制 |
| `POST /api/tasks/{id}/status` | status为in_progress/done/blocked/ready，note为说明或检验记录 |
| `POST /api/people` | name、skills数组、capacity_minutes；新增人员 |
| `POST /api/people/{id}` | 更新人员，不能移除仍有在途任务的技能 |
| `POST /api/settings` | material_rates、hourly_rates、loss_rate、overhead_rate、margin_rate、rates_confirmed |
| `POST /api/projects/{id}/costs` | outsourcing_cost，独立保存本项目费用 |
| `GET /api/projects/{id}/quote` | 成本分项、missing、complete、suggested_price与费率来源 |
| `GET /api/projects/{id}/export?format=csv` | 工种任务CSV |
| `GET /api/projects/{id}/export?format=bom_csv` | 部件BOM CSV |
| `GET /api/projects/{id}/export?format=json` | 工程数据、来源、任务、事件与估价JSON |
| `GET /api/documents/{id}/download` | 原始文件 |
| `POST /api/documents/{id}/resolve` | note；需已复核替代构件，登记原件与补录关系 |
| `GET /samples/showcase-bom.csv` | 示例整单BOM |
| `GET /samples/showcase-front-demo.dxf` | 示例DXF |

## 字段口径

构件规范字段为 length/width/thickness（毫米）；后端同时提供 length_mm/width_mm/thickness_mm。category为wood/metal/glass/electrical/hardware，quantity为整件数。source保留file、reference、revision、part_number、model_file等实际可得字段。内部ID与源料号分别保存。

任务规范字段为title/trade/hours/assignee，兼容别名为name/role/estimated_minutes/assignee_id。dependencies指向前置任务ID。archived=true为历史记录，应从当前清单排除。carried_from_task_id标明承接的未受影响旧版本工序。

任务状态：draft → ready → in_progress → done；执行可进入blocked，恢复需说明。工程修改使相关任务进入invalidated，重新编译发布前禁止继续执行旧版指令。

## 计价与来源

material_rates以材料名或类别为键，值为 `{unit_price, pricing_unit, loss_rate?}`，计价单位支持piece/m2/m3/meter/kg。hourly_rates以中文工种为键，值为人民币时薪。费率用小数，例如8%为0.08。构件单价优先于全局规则。

缺计算依据时总价null，分项可展示已知小计。complete只表示数值齐全，不代表工程或报价审批。rates_confirmed说明本厂是否核准费率；当前没有合同锁价。新项目外协费用独立初始化为0，修改其他项目不会带入。

## 后续工牌和多人接口

本版业务接口使用本机操作员身份，不能直接作为外部企业系统或多用户认证方案。已加入真实 ESP32-C3 的 USB 身份握手、任务接收回执与独立 Wi-Fi 令牌，见 `DEVICE-API.md`。多人和企业系统互联仍需增加租户/用户身份、对象授权、版本并发检查、业务幂等事件、离线队列、重传、附件证据和操作员审计。当前没有录音或视觉模型。
