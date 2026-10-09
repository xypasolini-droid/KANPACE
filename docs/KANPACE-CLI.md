# KANPACE 本地文件互联 CLI

`kanpace_cli.py` 使用与网页完全相同的本机 HTTP API。它不直接打开数据库、不绕过账号权限，也不替用户取消任务审核。支持订单、人员、材料和报工的 CSV/XLSX 互联。

先启动 KANPACE Web 服务。在软件目录使用 `.venv/bin/python kanpace_cli.py`；也可用已安装的 Python 3 运行，无额外依赖。

## 1. 只读取表头

```sh
.venv/bin/python kanpace_cli.py preview \
  --file '/本地路径/订单.xlsx' \
  --entity projects \
  --source-system '本厂Excel订单'
```

返回工作表、表头和前八行样本，不创建项目。可以指定 `--sheet '订单表' --header-row 3`。

## 2. 映射并生成待审核预览

```sh
.venv/bin/python kanpace_cli.py preview \
  --file '/本地路径/订单.xlsx' \
  --entity projects \
  --source-system '本厂Excel订单' \
  --mapping-json '{"external_key":"订单编号","name":"项目名称","due_date":"交期"}' \
  --defaults-json '{"factory_type":"cabinet"}'
```

输出每行的新增、更新、跳过或错误，以及更新前后差异。这里只保存待审核预览，不正式应用业务变化。`external_key` 必须为原系统的唯一订单号、员工号、需求行号或报工事件号。

长映射可以保存为 UTF-8 JSON 文件，再使用 `--mapping-json '@/本地路径/mapping.json'`；默认字段同样支持 `@文件路径`。`--entity` 支持 `projects`、`people`、`materials`、`progress`。字段目录由首读接口返回，不接受把“已完成”等状态直接映射成生产事实。

## 3. 明确应用已经核对的预览

将输出中的实际预览 ID 和 version 填入：

```sh
.venv/bin/python kanpace_cli.py apply \
  --preview-id 'exchange_实际预览编号' \
  --version 1
```

错误行会阻止应用；业务或关联工程版本已改变时，需要重新预览。相同预览重复应用会返回原回执，不重复创建订单或重复计报工。报工调用当前任务的正常报工动作：未发布、未开工、工程版本失效、缺少前置条件等都会由服务端拒绝。

## 4. 导出数据或应用回执

```sh
.venv/bin/python kanpace_cli.py export \
  --entity projects --format xlsx \
  --output '/本地路径/KANPACE订单.xlsx'
```

导出本次应用回执：

```sh
.venv/bin/python kanpace_cli.py export \
  --entity projects --format xlsx \
  --preview-id 'exchange_实际预览编号' \
  --output '/本地路径/订单导入回执.xlsx'
```

可用 `--project-id` 或 `--factory-id` 限定导出范围。默认不覆盖已有文件；如明确要替换指定输出，添加 `--overwrite`。不会改动源 Excel。

## 本机地址与登录权限

默认地址为 `http://127.0.0.1:8765`，自定义地址放在子命令之前：

```sh
.venv/bin/python kanpace_cli.py \
  --base-url 'http://127.0.0.1:8765' \
  --cookie-file '/本地路径/kanpace-cookies.txt' \
  preview --file '/本地路径/订单.xlsx' --entity projects
```

启用账号控制时，`--cookie-file` 使用已有合法登录会话的 Netscape 格式 Cookie 文件。CLI 不打印 Cookie，遇到401/403立即报告访问被拒绝，不自动切换身份或跳过权限。尚未启用账号控制的本机初始环境可以省略 Cookie 文件，访问是否允许始终由服务端决定。

CLI 仅接受 loopback 地址，拒绝外部主机和 HTTP 重定向。全局 `--timeout` 支持1至120秒。正常结束返回退出码0，连接、权限、映射、版本或文件错误返回1，便于接入客户自己的脚本。

## 验证

`tests/test_kanpace_cli.py` 共5项测试：通过临时真实 HTTP 服务完整运行首读、映射、应用、幂等重试、XLSX回执导出，源文件不变；另验证合法 Cookie、401/403阻断、不覆盖已有文件、外部地址与重定向拒绝。测试不操作正式业务数据。
