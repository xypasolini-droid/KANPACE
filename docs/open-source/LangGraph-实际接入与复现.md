**LangGraph 生产分析已接入**

运行时固定 LangGraph 1.2.11、langgraph-checkpoint-sqlite 3.1.1，本次实际使用 Python 3.14.6 的独立 `.venv-agent`。主应用无需导入这套环境的依赖。完整安装版本见 `requirements-agent.lock.txt`，实际依赖许可、版权文本及 SHA-256 见 `docs/open-source/licenses/langgraph-runtime/manifest.json`；该清单只覆盖运行时，未安装模型权重。LangSmith SDK 是上游依赖，当前没有接入其云服务或企业平台。

在应用目录执行：

```sh
python3 tools/setup_agent.py
python3 -m unittest discover -s tests -p test_langgraph_agent.py -v
node tests/test_agent_workflow_frontend.cjs
```

安装器使用当前 Python 创建 `.venv-agent` 并按锁文件安装。当前工厂实例和 checkpoint 使用 macOS/Linux 文件锁；Windows 需要适配进程锁后再验证，不能宣称本次已完成 Windows 部署。安装过程不修改订单、不烧录开发板。项目移交应重建环境，不能复制本机虚拟环境当作跨电脑安装包。

在 Web 助手点击或输入“分析延期原因并比较排程”。真实 LangGraph 节点依次为 `overdue → causes → review(interrupt) → compare → proposal`，不是把一条正则回复套入空图。首次展示合同交期和任务风险依据；明确继续后，主进程读取同一业务快照，分别调用现有启发式与 `optimization_engines.schedule_advice` 的 OR-Tools，结果传入工作流比较。优化失败明确显示不可用，不伪装成优化成功；求解后的正式发布仍使用现有 API。

**接口与事务**

仍使用 `POST /api/agent/message`，请求保留 `message/project_id/factory_type`，继续操作可加：

```json
{"message":"继续延期分析","project_id":"prj_example","factory_type":"cabinet","workflow":{"id":"wf_0123456789abcdef0123456789abcdef","decision":"compare"}}
```

`decision` 支持 `compare/refresh/cancel`。响应保留 `mode:local_commands`、`message/results/actions`，新增 `workflow:{id,status,engine,engine_version,reasoning,steps,sources,causes,candidates,fingerprint}`。状态为 `review/proposed/cancelled/stale`。新动作只有 `workflow_continue` 和 `schedule_preview`；客户端不能指定任意工具、URL、角色或模型地址。

主服务可将 `langgraph_agent.status()` 纳入状态接口。它在独立环境中真实导入 LangGraph 与 SQLite checkpoint 组件，最长等待 8 秒，成功缓存 60 秒、失败仅缓存 3 秒，返回 `available/name/version/checkpoint_version/reasoning/local_model_configured/model_verified`。机器繁忙导致检测超时会明确提示稍后刷新。健康检查不打开工厂数据库、不创建分析记录；模型配置存在不代表模型已连通，所以 `model_verified` 为 `false`，不暴露地址或模型名称。

主业务 SQLite 连接使用只读事务；经过权限过滤的最小事实快照通过标准输入传给子进程，不包含报价、密钥、图纸原文或任意历史提示。检查点写入当前 `store.data_dir/agent-workflows/checkpoints.sqlite`，目录 0700、文件 0600，不共用另一工厂的目录。记录绑定账号、岗位、人员及页面范围；即使知道编号，另一个账号或工厂也不能继续读取。生产资料变化后先返回过期，不再次求解或显示旧来源。

每个事实快照和账号范围产生稳定工作流编号。重复首问恢复已有分析，进程退出后从持久 checkpoint 继续，完成后重复继续不重新运行求解器；文件锁串行化同时到达的图执行。预览通过 `/api/scheduling/preview`，采用通过 `/api/scheduling/{id}/apply`，保留原接口的权限、版本和幂等行为。工作流不自动开工、解除暂停、改数量或发送工牌任务。

选择“保留诊断，暂不排程”后仍可明确点击“重新分析”。该操作开启稳定的新记录；同一个重新分析请求重复到达会恢复新记录，不重复生成。已过期的分析可按新生产资料重新分析。

当前诊断依据为已过项目交期、暂停登记、已登记物料缺口、未完成前序、负责人和工时是否已填。它展示风险线索，未证明这些线索就是延期的因果根因；未来交期预测和现场实绩分析需继续扩展。工序表数量超过显示上限会明确提示，不隐藏未排工序的存在。

**可选本机模型**

默认不调用任何语言模型，也不读取真实模型密钥。子进程环境按白名单传递，关闭 LangSmith/LangChain tracing，不继承云密钥或代理设置。现阶段称“本地规则分析”，不能称任意自然语言的通用模型助手。

管理者可在自己的启动环境中显式设置以下三个变量，接入本机 OpenAI 兼容接口：

```sh
export KANPACE_AGENT_LOCAL_MODEL_ENABLE=1
export KANPACE_AGENT_MODEL_ENDPOINT=http://127.0.0.1:11434/v1
export KANPACE_AGENT_MODEL_NAME=your-installed-model
```

只允许回环 IP 的 HTTP 地址，拒绝用户信息、查询密钥及重定向，不支持由浏览器请求配置。只发送已经计算出的方案汇总数，不发送原图、物料名称、人员资料和原始对话；模型只整理一句说明，不能改事实、选工具或执行动作。模型不可用仍保留确定性结果。模型权重、资源需求和许可需由选用方单独确认，当前没有安装或假称验证了某个本机大模型。

检查点及可选模型整理均属相应工厂私有衍生数据，备份、删除、迁移应随该客户空间整体处理，不进入公共知识库。本机操作系统管理员仍可管理本机文件；这不是操作系统沙箱。

**本次实际验证**

2026-09-07 最终检查：新增 LangGraph 后端 20/20（28.14 秒）、已有助手后端 29/29、新增工作流前端 9/9、已有导航与助手前端 18/18；另通过 Python 编译检查、JavaScript 语法检查及按锁文件重复安装检查。早先机器繁忙时出现一次 8 秒健康检查超时，已区分超时提示并缩短失败缓存；最终整组 20 项复跑通过。

新增后端集成在临时、无种子业务库上运行真正 LangGraph 子进程与 SQLite 检查点，核对跨进程继续、重复请求、跨账号与工厂隔离、资料变化失效、模型仅回环统计整理、重定向拦截、运行时健康检查。OR-Tools 成功用例直接运行本机 CP-SAT，没有 mock 求解成功；另有明确模拟故障用例检验不可用提示，不将故障伪装成优化方案。

真实临时 HTTP 服务完成了“分析 → 继续比较 → OR-Tools 预览 → 确认采用 → 重复确认”全流程，全部响应成功。诊断和比较前后制造业务实体保持一致；生成预览没有生产计划；确认采用后有计划，任务实际状态与负责人仍保持原值；重复确认没有新增计划。原有指令助手与导航回归、新增前端步骤和确认行为测试共同覆盖固定端点、输入白名单、数据版本、重复点击、过期和注销后的迟到响应。可选模型测试使用本机假 HTTP 服务，只验证协议与数据范围，未验证真实大模型效果。这些是隔离样例验收，不能宣称已在客户订单上证明排程收益或识别准确率。
