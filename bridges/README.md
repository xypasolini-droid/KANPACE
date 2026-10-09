# SOLIDWORKS 与 CAD 导入桥接

这份桥接把 Windows 设计电脑上已打开的 SOLIDWORKS 装配导出为本地拆单软件可导入的 CSV。它读取真实零件实例和自定义属性；不需要大模型密钥，也不向网络发送图纸。

**验证状态：当前开发环境是 macOS，没有安装 SOLIDWORKS。本脚本尚未完成 Windows + SOLIDWORKS 实机导出验证。正式使用前必须按下面的小装配检查表验证。** 脚本的存在不表示本地网页已经能直接解析 `.sldasm`、`.sldprt` 或 DWG 二进制文件。

2026-09-04 已用 PowerShell 7.6.5 的原生解析器检查脚本语法，并用 Roslyn 检查内嵌 C# 语法，均为 0 个语法错误；在 macOS 上试运行会按预期拒绝执行且不产生 CSV。这些检查不等于 Windows PowerShell 5.1 的 COM 绑定或实际模型导出验证。

## 运行方法

1. 在 Windows 64 位设计电脑安装并正常启动 SOLIDWORKS 2018 或更高版本。只保留一个 SOLIDWORKS 实例，避免连接错误窗口。
2. 打开目标装配，切换到本次订单的有效配置。手动完全解析所有组件、重建需要导出的配置并保存。脚本不会替你解析轻化组件、切换配置或保存源文件。
3. 在零件的“自定义属性”或相应“配置特定属性”中准备下表字段。配置特定属性优先于文件级属性。
4. 在同一个 Windows 用户会话打开 **Windows PowerShell 5.1**，执行：

```powershell
powershell.exe -NoProfile -STA -File .\Export-SolidWorksBOM.ps1 `
  -OutputCsv C:\CabinetFlow\order-001.csv `
  -AssemblyQuantity 3
```

`AssemblyQuantity=3` 表示生产三套当前装配。默认值是 1。已有输出文件不会自动覆盖；需要保留新版本时换文件名。明确覆盖导出结果可加 `-Force`，它不影响任何 SOLIDWORKS 源文件。

若 SOLIDWORKS 安装目录不同，补充其实际接口库位置：

```powershell
powershell.exe -NoProfile -STA -File .\Export-SolidWorksBOM.ps1 `
  -OutputCsv C:\CabinetFlow\order-001.csv `
  -InteropPath 'D:\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll'
```

如果公司策略阻止运行本地脚本，按公司的脚本签名/执行策略流程处理；本工具不修改系统执行策略。保留脚本的 UTF-8 BOM 编码，供 Windows PowerShell 5.1 正确识别中文属性名。

导出会得到 `order-001.csv` 和 `order-001.csv.audit.json`。后者记录装配文件、配置、套数、导出时间、CSV 哈希、抑制节点数量及警告。导入 CSV 后的零件仍需审核。

## 属性约定

| SOLIDWORKS 属性 | CSV 字段 | 含义与示例 |
|---|---|---|
| `CF_PartNumber`，兼容 `PartNumber`、`零件编号`、`图号` | `part_number` | 企业图号或料号，如 `WC-001` |
| `CF_Name`，兼容 `Description`、`名称`、`零件名称` | `name` | 如“底柜左侧板”；缺失时保留真实文件名及配置名 |
| `CF_Material`，兼容 `Material`、`材料`、`材质` | `material` | 如“18mm 多层板”；仅读取属性，不从模型颜色推断材料 |
| `CF_Category`，兼容 `category`、`工艺分类` | `category` | `wood` 木工、`metal` 五金加工、`glass` 玻璃、`electrical` 电气、`hardware` 标准件/外购件 |
| `CF_CutLength_mm`，兼容 `下料长度mm` | `length_mm` | 工艺人员确认的下料长度，毫米 |
| `CF_CutWidth_mm`，兼容 `下料宽度mm` | `width_mm` | 工艺人员确认的下料宽度，毫米 |
| `CF_CutThickness_mm`，兼容 `下料厚度mm` | `thickness_mm` | 工艺人员确认的下料厚度，毫米 |
| `CF_Finish`，兼容 `Finish`、`表面处理`、`饰面` | `finish` | 如“哑光烤漆”“拉丝”；具体工艺必须复核 |
| `CF_Revision`，兼容 `Revision`、`版本`、`修订` | `revision` | 如 `R3` |
| `CF_ExportAsItem=true` | 控制导出层级 | 外购子装配作为一个项目导出；否则递归导出其零件 |

`category=metal` 表示需要五金加工的金属构件；`category=hardware` 表示标准件/外购件。未知分类、缺失材料与缺失尺寸保留为空。属性读取未解析时也保留为空，并在审计文件说明原因。使用小数点，不使用千位逗号；尺寸接受 `1200`、`1200 mm` 或 `1200毫米`。脚本不会把 `1.2m` 静默解释成毫米。

另有自动生成的 `id`、`quantity`、`unit`、`source_file`、`source_reference` 字段。`id` 来自源文件路径和配置的哈希；同路径同配置聚合，数量等于实际组件出现次数乘以装配套数。文件移动或更名会改变这个 ID，跨系统长期身份需要另行使用企业受控的唯一构件编号。

## 必须核对的工程边界

- 输出是**装配零件实例清单**，不是工程图 BOM 表格的原样导出。抑制组件排除，隐藏组件计入；BOM 排除、子项提升/隐藏、封套组件、长度计量 BOM、自定义 BOM 数量等特殊规则尚未应用，必须与发布 BOM 逐项对照。
- 脚本不读取焊件切割清单或多实体零件的每个实体，也不会自动展开钣金。它不会把外形包围盒、工程图视图尺寸或装配尺寸当作下料尺寸。钣金折弯扣除、木板封边余量、纹理方向、开槽孔位、公差、玻璃倒角等须来自另外的已审核工艺数据。
- 轻化、未加载或无法读取的组件导致本次导出失败，不输出一个看似完整的部分清单。先在 SOLIDWORKS 中解决后重新运行。
- 属性使用 `Get6(..., UseCached=true, ...)`，避免脚本为了读属性而激活其他配置。缓存可能过期，因此“手动重建并保存有效配置”属于导出前置步骤；导出的文件不能替代工程发布签核。
- 不同配置单独聚合，当前顶层配置决定所遍历的装配结构。若订单包含多个配置，应分别导出并标明各自的生产套数。
- CSV 可以在本机浏览器导入；桥接本身不自动连接软件、上传数据或下发工单。

## 第一次实机验证

准备一个包含木板、金属支架、玻璃、标准件的脱敏小装配，至少包含一个重复零件、一个两次出现的子装配、两个配置和一个抑制件。先由技术员写出人工答案，再执行脚本。

| 检查项 | 通过条件 |
|---|---|
| 数量 | 与当前配置的非抑制实例清单一致；套数从 1 改为 3 后只增加数量，不改变零件分类和尺寸 |
| 子装配 | 默认拆至零件；显式 `CF_ExportAsItem=true` 后只导出该子装配项目，不同时计入其子零件 |
| 配置属性 | 同一文件的不同配置不合并；各自采用配置属性，缺配置字段才采用文件级字段 |
| 缺值和异常单位 | 未填写的尺寸为空，`1.2m` 不变成 `1.2mm`；未知分类为空 |
| 不完整装配 | 未解析组件触发可见错误，不生成部分 CSV |
| 源文件 | 导出前后文件哈希与修改时间一致；没有新增模型保存记录 |
| 软件导入 | CSV 各行能回查来源与配置；没有从文件名凭空生成尺寸或已审核状态 |

验证记录应包含 SOLIDWORKS 版本、Windows 版本、样本配置、预期/实际 CSV、审计 JSON 和审核人。

## DWG、DXF 与其他文件

DWG 先在设计软件中另存为 **ASCII DXF**，或使用已安装的 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) 导出 DXF。保留原始 DWG 和转换后的 DXF，核对图纸单位、块、文字、外部参照和版本。转换器只转换格式，不会自动理解“这个矩形就是要切的一块木板”。

本版本 DXF 规则读取有限实体与明示元数据。推荐使用项目提供的示例 DXF 学习 `CABINET_PART` 元数据或 `CABINET::category::name::material::thickness::finish::quantity` 图层约定。未知单位、缺失材料/数量、任意复杂轮廓和未标注的图形都需要审核；普通平立剖视图不能按图上出现次数计算生产数量。

STEP、原生 SOLIDWORKS、PDF 与图片需另行转换为明确的 BOM 或完成后续专用解析器适配。当前不把这些文件的上传成功显示为结构识别成功。

接口依据：[SOLIDWORKS GetComponents](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAssemblyDoc~GetComponents.html)、[GetChildren](https://help.solidworks.com/2019/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IComponent2~GetChildren.html)、[GetModelDoc2](https://help.solidworks.com/2022/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IComponent2~GetModelDoc2.html)、[Get6](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICustomPropertyManager~Get6.html)。接口文档核查日期：2026-09-04。

## 将 SolidWorks 装配用于 Web 3D 查看

新增 `Export-SolidWorksModel.ps1` 可在安装 SolidWorks 的 Windows 电脑上导出 STEP 几何、实例层级索引和源文件审计。它不会从 BOM 尺寸造模型，也不会替换本来的 BOM 导出器。详细步骤、拒绝条件与尚未进行的实机验证见 [MODEL-EXPORT.md](MODEL-EXPORT.md)。
