# Web CPU 运行时安装与验收

本入口安装已经接入业务代码的 OR-Tools、PDFium、Web 图片依赖 Pillow 与 LangGraph，使排程、原生 PDF 文字/坐标与图片预览、可继续分析有真实 CPU 运行时。它不会打开业务 Store、发布生产版本、采用排程、开工或下载 OCR/LLM 模型，也不构建 PackingSolver。Web 的权限、版本校验与审批仍由原有业务服务执行。

`requirements-web.in` 固定应用顶层版本：OR-Tools 9.15.6755、pypdfium2 4.30.0、Pillow 12.3.0、LangGraph 1.2.11、langgraph-checkpoint-sqlite 3.1.1。安装仅从官方 PyPI 取 wheel，缺少对应平台的 wheel 就报错，不悄悄切到源码编译。官方版本来源：[OR-Tools](https://pypi.org/project/ortools/9.15.6755/)、[PDFium binding](https://pypi.org/project/pypdfium2/4.30.0/)、[Pillow](https://pypi.org/project/pillow/12.3.0/)、[LangGraph](https://pypi.org/project/langgraph/1.2.11/)、[SQLite checkpoint](https://pypi.org/project/langgraph-checkpoint-sqlite/3.1.1/)。

## 环境布局与 Linux 安装

建议 Linux x86-64 / ARM64 的常规 glibc 系统，CPython 3.12，已装系统 Python、venv 和可信 CA。3.13 允许安装，但仍以探针结果判定；3.14 不属于本批验收基线。当前 LangGraph worker 使用 `fcntl`，本批运行入口支持 Linux/macOS，不能据导入成功就宣布 Windows 恢复能力可用。云端镜像需在目标架构重新安装，不能复制 macOS 的 venv。

在受控的 KANPACE 源码根目录运行：

```sh
python3.12 tools/setup_web_runtime.py --install --python python3.12
python3.12 tools/setup_web_runtime.py --check
```

本次已归档完整解析版本后，目标 Linux 镜像优先使用以下命令复现版本，再在目标机器做相同真实探针：

```sh
python3.12 tools/setup_web_runtime.py --install --locked --python python3.12
```

`--locked` 使用 `docs/upgrade/runtime-locks/optimization.txt` 与 `agent.txt`，不会另行解析到更新的传递依赖；如目标架构缺少锁定版本 wheel 会明确失败。这是完整版本锁，artifact SHA-256 另存 pip report；它尚不是 pip 的 `--require-hashes` 跨平台哈希锁。

脚本创建两个已经被应用发现的独立环境：

| 目录 | 安装内容 | 应用入口 |
| --- | --- | --- |
| `.venv-optimization` | OR-Tools、pypdfium2 与 Pillow、各自依赖 | 默认 OR-Tools subprocess；作为 Web 主解释器，让统一识别与资料/图片预览使用 PDFium、Pillow |
| `.venv-agent` | LangGraph 与 SQLite checkpoint、各自依赖 | `langgraph_agent.run()` 固定的独立分析 worker |

两个目录已被 `.gitignore` 忽略。LangGraph 入口目前没有任意解释器覆盖变量，因此只创建共享 `.venv-web` 不能让应用自动发现它。启动 Web 主进程时使用 `.venv-optimization/bin/python`，并按现有 Web 启动参数设置服务模式、监听与身份验证；具体端口和生产入口由 Web 部署说明定义。本脚本不会改变监听、开放端口或替代服务认证。OR-Tools 可用 `KANPACE_OPTIMIZATION_PYTHON` 覆盖默认 worker 路径；如有覆盖，需对同一解释器重新验收。

首个独立业务目录的管理员初始化按 README 在回环模式完成：

```sh
.venv-optimization/bin/python app.py --no-demo --listen 127.0.0.1 \
  --port 8765 --data-dir /srv/kanpace/data
```

在服务器本机或经 SSH 转发使用既有账号初始化页面完成 `/api/access/setup` 后停止该进程；配置好 HTTPS 反向代理，再使用已实现的 Web 模式启动同一数据目录：

```sh
.venv-optimization/bin/python app.py --no-demo --listen 127.0.0.1 \
  --port 8765 --public-origin https://kanpace.example.com \
  --data-dir /srv/kanpace/data
```

示例域名须替换成实际 HTTPS origin，反向代理保留精确 Host；业务服务仍绑定回环。初始化、域名/TLS、备份以及进程托管属于正式部署操作，本次未在实际服务器执行。已有数据目录应使用现有有效管理员，不重新初始化。

安装前先检查 `python3.12 --version`。Ubuntu 的 venv 缺失、TLS/CA 故障、PyPI 不可达或无匹配 wheel都会记录为组件不可用，退出码非零。安装没有关闭 TLS 校验或使用 `--trusted-host`。可修复网络/系统证书后原命令重试，已有环境会继续安装而不会删除业务数据。可用 `--component optimization` 或 `--component agent` 只修复其中一组。

## 可复核的验收输出

默认结果在 `work/web-runtime-check.json`，包含 UTC 时间、目标平台、实际包版本、组件的 `available` 和真实失败原因。安装时的 pip JSON report 在 `work/web-runtime-install/`，验收后与解析版本一起归档到 `docs/upgrade/runtime-locks/`，保留下载 URL 与包 artifact SHA-256；分组件许可证清单在 `docs/upgrade/runtime-licenses/`。`--check` 不下载包或模型，不触碰业务资料，只在临时目录做分析恢复并写指定报告。

只有以下检查全部成功，组件才标 `available:true`：

1. 每个环境 `pip check` 无依赖冲突，实际顶层版本与固定输入一致。
2. OR-Tools 真实 CP-SAT 解三个包含共享设备与前置汇合关系的工序，结果为 `OPTIMAL` 或 `FEASIBLE`，全部覆盖；现有独立 `validate_schedule` 验证时间窗口、资源不重叠、加工时长、任务覆盖与前置约束。禁用启发式回退。
3. PDFium 打开一次性 PDF，提取真实文字与字符边界坐标，并通过 Pillow 生成真实页面预览；Pillow 分别编码并重新解码 PNG/JPEG。此检查不能证明扫描图 OCR、版面理解或中文工程字段准确率。
4. LangGraph 在一次性私有目录运行实际业务分析图，首次停在复核 interrupt；另一个进程读取 SQLite checkpoint 继续至方案阶段；第三个进程重复继续时输出和 checkpoint 数量不变。无通用模型调用，无生产 Store。

更完整的业务集成验收可以独立运行，测试只创建临时 Store：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests KANPACE_TEST_REAL_ENGINES=1 \
  .venv-optimization/bin/python -m unittest test_optimization_engines.RealScheduleTests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests \
  .venv-optimization/bin/python -m unittest test_langgraph_agent -v
```

只选择 `RealScheduleTests`，避免把尚未构建的 PackingSolver 实例测试误算成 CPU Web 安装失败。测试中 `allow_fallback:false` 的排程才证明真实 CP-SAT 跑通。生产前需要再用真实脱敏工单做约束/时间语义验收；这些微型探针不能承诺吞吐、真实排程收益或所有工单最优。

## 固定版本、许可证与持久化边界

顶层输入已经固定，传递依赖由首次安装解析；安装时保存实际版本清单、下载 artifact hash 与包含的 LICENSE/NOTICE/COPYING。它不是跨平台完整哈希锁。发布 Linux 镜像应以目标平台的已验收解析清单冻结传递依赖，保存 pip report/许可证并固定镜像 digest，再在 CI 重跑同一探针。不要直接覆盖已有 `requirements-agent.lock.txt` 或 `requirements-optimization.lock.txt`。

OR-Tools 为 Apache-2.0、LangGraph/SQLite checkpoint 为 MIT，允许商用；PDFium binding 和底层 PDFium 及依赖有各自许可义务。部署镜像、交付包和软件许可入口应保留项目现有 `THIRD_PARTY_NOTICES.md`、原许可证归档以及本次新增运行时 LICENSE/NOTICE，不把某一个主包许可等同于所有依赖许可。以上说明不授权额外模型权重、商用求解器或云服务；本批没有安装它们。以实际 wheel 中的许可证文本为准。

本次 pypdfium2 wheel 声明 `(Apache-2.0 OR BSD-3-Clause) AND LicenseRef-PdfiumThirdParty`。归档包括实际 Apache/BSD 文本、文档的 CC-BY-4.0、内嵌 PDFium 第三方完整许可 `LicenseRef-PdfiumThirdParty.txt`，以及明确二进制版权/许可的 `dep5-wheel`；这些文件使用 SPDX 名称，安装脚本同时按 wheel 的 `License-File` 列表识别，避免只按 LICENSE 文件名扫描时遗漏。内嵌 PDFium 版本为 126.0.6462.0（pdfium-binaries），实际版本与全部归档 SHA-256 见验证报告。

当前分析 checkpoint 仍是每个工厂私有目录中的 SQLite，并用进程文件锁串行保护。Web/API 主数据也仍采用现有 Store。这一入口证明已接入算法和分析恢复可运行，没有实现 PostgreSQL 迁移、跨主机事务、分布式任务池或 Temporal 生命周期。上线多副本前需按云方案实施这些部分，避免多主机并发共用 SQLite 文件。备份和升级应同时保留业务数据库、原件及每个工厂的 checkpoint；复核和正式采用继续经过业务权限、资料版本与独立验证。

## 本次实测记录

本次使用独立创建的 CPython 3.12.14 环境，OR-Tools 9.15.6755、pypdfium2 4.30.0、Pillow 12.3.0、LangGraph 1.2.11 与 SQLite checkpoint 3.1.1 的真实探针全部通过。6 项真实排程业务集成测试和 20 项 LangGraph 集成测试全部通过，无跳过；后者覆盖 HTTP 预览/采用、资料变化失效、重复继续、账号/工厂范围与私有 checkpoint。已归档优化环境 12 个、分析环境 42 个安装分发包的实际版本及所含许可文件。Pillow 属于 Web 图片功能的正式依赖；未把 USB/串口依赖加入本批环境。

完整 Web 回归发现缺少 Pillow 的导入/图片功能依赖后，补入固定版本并刷新全部锁、artifact 与许可记录；图片、资料流与工厂实例隔离三个相关测试模块共 32 项通过，无跳过。Pillow wheel 的 MIT-CMU 合订许可证含其嵌入原生库通知，已经逐字节及 SHA-256 校验，不只保存许可名称。最终全量 Web 回归结果由项目总体验收记录维护，不将修复前的失败报告改称通过。

第一次 OR-Tools 下载完成后的 macOS 原生加载超过 30 秒，初次结果真实记为超时；提高首次原生加载等待至 180 秒后一次重验成功，随后完整检查通过。此等待用于系统加载验证，不扩大 CP-SAT 自身的求解时限。最终记录在 `web-runtime-verification.json`，明确区分 macOS 本次实测和 Linux 待目标机验收。Linux 服务器尚未部署，OCR/LLM 大模型和 PackingSolver 原生二进制未安装。
