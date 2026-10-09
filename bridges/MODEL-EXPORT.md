# SolidWorks 装配模型进入 Web 3D 工作区

`Export-SolidWorksModel.ps1` 将 Windows 上已经打开的装配导出为独立 STEP 包。几何由 SolidWorks 自己的 STEP 转换器生成；脚本不会拿 BOM 长宽厚搭方盒，也不自行计算组件变换矩阵。输出保留转换器提供的实体、曲面、装配关系与名称，并另存原始组件名称、层级和 BOM 对应编号。

**当前验证状态：已完成官方 API 契约核对与静态检查；本机为 macOS，没有运行中的 SolidWorks，尚未做 Windows/SolidWorks 实机编译、导出和几何对照。此桥接应先用小装配验收，再用于生产图纸。**

## Windows 使用步骤

1. 使用已安装 SolidWorks 2024 或更新版本的 Windows 电脑。打开目标 `.SLDASM`，激活目标顶层装配与配置，手动完全解析、重建、检查并保存全部相关文档。
2. 退出组件编辑状态，清空选中的零件、面或实体。显示所有需要导出的组件和实体。脚本保守拒绝隐藏组件、隐藏实体、SpeedPak、轻量化、缺失零件、未保存更改和待重建状态。
3. 在 SolidWorks 的 STEP 导出选项中选择：**AP214、实体/曲面几何、导出面/边属性**；关闭“将装配组件导出为单独的 STEP 文件”，输出坐标系采用默认值。脚本只读取这些选项，不替你修改全局设置。
4. 在 64 位 Windows PowerShell 5.1 执行：

```powershell
powershell.exe -NoProfile -STA -File .\Export-SolidWorksModel.ps1 `
  -OutputDirectory C:\CabinetFlow\order-001-model
```

若 DLL 没有装在默认位置，补充：

```powershell
  -InteropPath 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll'
```

同一目录必须存在该安装版本的 `SolidWorks.Interop.swconst.dll`。输出目录必须尚不存在，防止覆盖以前的结果。

5. 将输出的 `model.step` 上传到与 BOM 相同的 Web 项目，在 **3D 工作区**查看、旋转、隐藏/单独查看组件，并逐项关联已有拆单记录。`occurrences.csv` 是关联索引，不是下料 BOM，不应当作零件清单直接导入。

## 输出文件

| 文件 | 用途 |
|---|---|
| `model.step` | 原生 STEP AP214 几何，包含转换器保留的产品名称与装配关系 |
| `occurrences.csv` | 组件实例名称、父子关系、源文件、引用配置、稳定实例 ID、BOM ID、零件号 |
| `audit.json` | 源文件前后 SHA256、配置与未保存状态、导出选项/错误/警告、输出摘要与复核边界 |

STEP 自带单位声明，脚本不修改几何坐标或冒称原始数值就是毫米。Web 的 STEP 导入器应读取单位并统一为毫米。第一次验收时用已知尺寸核对，避免把米、毫米或英寸混为一谈。

`bom_id` 与现有 `Export-SolidWorksBOM.ps1` 使用相同规则：

```text
sw- + SHA256(UTF8(UPPER_INVARIANT(源文件路径 + "|" + 引用配置)))[前20个十六进制字符]
```

`CF_ExportAsItem=true` 的外购子装配作为一个 BOM 项，其后代实例指向同一外购 BOM ID。`part_number` 使用同一组自定义属性别名读取。`occurrence_id` 则包含顶层装配路径、顶层配置和完整组件 `Name2`，用于区分同一零件的多次放置；移动源文件或重命名实例后，ID 可能变化，不能作为跨工程版本永不改变的全局标识。

本桥接**不会假设 STEP 网格顺序或导出的名称与 occurrence 行号天然一一对应**。当前 Web 中的关联仍需核对后确认；保留原名与稳定 BOM ID 为后续自动匹配提供依据。

## 为什么采用 STEP

官方 `IComponent2.GetTessTriangles` 文档明确将该方法限制为轻量化组件的显示三角网格；本任务要求读取已经完全解析的装配，不能以此方法假定取得可靠网格。图形细分也不是加工几何精度的承诺。因此本桥接使用原生 STEP 转换器，并把零件实例与 BOM 关系单独记录。[SolidWorks：GetTessTriangles](https://help.solidworks.com/2021/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.icomponent2~gettesstriangles.html)

`IModelDocExtension.SaveAs3` 支持按扩展名转换当前活动模型；若选中了面或实体，可能只导出选中对象，所以脚本在导出前拒绝非空选择。该方法会触发保存通知，也可能更新配置预览，因此这里的“只读”限定为**脚本不保存/修改源 CAD 文件、不主动解析或重建、不切换配置**，不宣称 SolidWorks 会话绝无副作用。[SolidWorks：SaveAs3](https://help.solidworks.com/2020/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SaveAs3.html)

`swSaveAsOptions_Copy` 的官方说明限定其选项适用于原生格式，不能拿这个标志证明 STEP 导出必然保持源状态。本脚本输出到新的隔离目录，导出后逐个比较已加载源文件 SHA256、活动配置和 dirty 状态；导出有警告、源状态发生变化或 STEP 结构不完整时，不发布成功包。[SolidWorks：Save As 选项](https://help.solidworks.com/2025/English/api/swconst/SOLIDWORKS.Interop.swconst~SOLIDWORKS.Interop.swconst.swSaveAsOptions_e.html)

STEP 选项中的实体/曲面几何、面/边属性、独立组件文件和输出坐标系会影响结果；脚本按官方枚举读取并限制它们。面/边属性开启不等于保证所有面 ID 跨版本稳定，原始组件名称始终另存于实例索引。[SolidWorks：STEP 导出选项 API](https://help.solidworks.com/2026/english/api/swconst/FileSaveAsSTEPOptions.htm)

## 第一次实机验收

使用含重复零件、子装配、旋转放置零件及玻璃/金属/木作的一个小型已批准装配：

- 核对成功包中的源文件 SHA256 前后一致；导出后原装配仍为当前文档、当前配置，且没有新未保存更改。
- 在 Web 与 SolidWorks 对照外形、零件数量、层级、旋转方向、装配位置以及至少三个已知尺寸。
- 检查重复零件的不同实例能独立选择；核对实例索引中的 BOM ID 与 BOM 导出器一致。
- 检查有选中面、缺失/轻量化组件、SpeedPak、隐藏实体、未保存更改、待重建以及原生导出警告时脚本确实拒绝，且不会留下成功目录。
- 多配置实例若引用配置与其已加载文档的活动配置不同，本桥接主动拒绝。此时先通过 SolidWorks 手动导出完整 STEP 并人工复核；脚本不会为了补齐缓存悄悄切配置。

成功通过上述实机对照后，再把具体 SolidWorks 版本、测试装配、STEP 与审计结果记录进项目验收资料。当前的静态检查与 STEP 文件结构检查不代替几何、公差、名称完整性或加工可用性验证。
