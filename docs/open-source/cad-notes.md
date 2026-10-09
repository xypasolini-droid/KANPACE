CAD / 图纸 / OCR / BOM / 3D / 排料 / CAM 分支已完成 17 项候选，详见 `cad.json`。研究只读取官方仓库、许可证、文档、模型卡与公开元数据；没有安装或运行候选代码，没有改业务或数据库。

- 第一批值得落地：PDF.js 负责施工图原文定位，ezdxf 补齐当前 ASCII DXF 自定义解析，沿用 Three.js 和 occt-import-js 真模型交互。数据应保留文件哈希、修订、页码/区域或实体 handle、单位与识别来源。
- FreeCAD / OCCT 适合精确几何与工程工作站。FreeCAD 1.1 官方发布说明已包含装配 BOM，不能再把它描述为完全无 BOM 能力；但采购件、虚拟件、工序耗材和制造拆件映射仍需 KANPACE 规则。[官方 1.1 说明](https://freecad.github.io/Website/download/releases/1-1/)
- PaddleOCR 优先用于图纸小字/中文标注；Docling 优先用于整页 BOM 表与技术说明的结构化。二者的输出都应作为待核验字段，原始文字、页区、置信度/模型版本不能丢弃。没有进行真实 KANPACE 工程图正确率测试。
- 原生 SLDASM / SLDPRT 完整参数树、配置和配合仍有缺口。现有 Windows SolidWorks 导出桥尚未实测，仍要如此标注。STEP/BREP 中性格式与浏览器网格不是原始 SolidWorks 设计历史；效果图不提供缺失的加工尺寸。
- 钣金 SheetMetal 插件维护活跃，2026-08-22 发布清单为 0.8.22；Engineering UX Mode 明确要求用户填写视觉无法检查的参数。应确认材料、厚度、折弯半径、K 因子，再接受展开 DXF。[插件工程模式](https://github.com/shaise/FreeCAD_SheetMetal#engineering-mode)
- 排料优先新增 PackingSolver PoC：官方包含一维、矩形、齐头切和异形求解器，最新可见提交为 2026-09-06；可从已批准 BOM 通过本地 CLI 传入 CSV/JSON。它提供布局优化，不提供完整 CAM。先验证矩形/型材，后验证带孔凹形与旋转约束。[官方仓库](https://github.com/fontanf/packingsolver)
- CAM 先试 FreeCAD CAM；PyCAM 的默认分支最新可见提交为 2021-11-25，Windows/macOS 安装说明明显不完整，不应拿它作现代跨平台开箱即用的承诺。libnest2d 最新可见提交 2022-11-16，官方还写明矩形/凸形、无孔洞/凹形边界，适合作为备选算法参考。

必须在总报告保留的许可差异：

1. **occt-import-js 本体为 LGPL-2.1，不是 MIT**；内嵌 OCCT 又有独立的 LGPL2.1 例外。CadQuery / OCP 的 Apache2.0 也不覆盖底层 OCCT。[封装许可](https://github.com/kovacsv/occt-import-js/blob/main/LICENSE.md) · [OCCT 例外](https://github.com/Open-Cascade-SAS/OCCT/blob/master/OCCT_LGPL_EXCEPTION.txt)
2. **deepnest-next/deepnest 不是纯 MIT**：官方 LICENSES.md 明列 `main/deepnest.js` 为 GPLv3。原版核心文件也声明 GPLv3；社区的另一仓 `deepnest-next/deepnest-next` 是独立代码线，不能混合许可结论。[组件清单](https://github.com/deepnest-next/deepnest/blob/main/LICENSES.md)
3. IfcOpenShell 核心/Python 为 LGPL3+，Bonsai 为 GPL3+。GitHub latest release 返回 Bonsai alpha，不能当作 Python 稳定版。[官方逐组件表](https://github.com/IfcOpenShell/IfcOpenShell)
4. Docling 代码 MIT；docling-models 卡同时列 CDLA-Permissive-2.0 与 Apache2.0，Heron 和 Granite-Docling 卡为 Apache2.0。PaddleOCR 两个已具体核验的 PP-OCRv5 server det/rec 权重均为 Apache2.0；其他可选模型不能一概推广。[Docling 模型卡](https://huggingface.co/docling-project/docling-models) · [PaddleOCR 识别模型卡](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec)
5. FreeCAD 当前根 LICENSE 是 LGPL2.1，但部分旧文档/贡献说明仍写 LGPL2+，锁定版本时要按实际文件确认。旧 FreeCAD-documentation 仓库归档不等于 FreeCAD 软件归档；同理，旧 pdfjs-dist GitHub 仓库归档不等于 PDF.js 停更。
6. PackingSolver 主体 MIT，但默认 CMake 同时打开 CLP 和 HiGHS；需针对实际构建核验依赖。若选择仅 HiGHS，应显式关闭未审计后端；可选 KNITRO 默认关闭，属于专有求解器方向，不纳入全开源组合。

已有每条 release 或 commit 日期、许可证 URL、能力与边界、部署平台、接入建议和成熟度依据。GitHub API 中途遇 403，转用官方 Atom feed / 页面，没有把缺失结果写成零活动。部分 UTC 日期为 2026-09-07，用户所在 America/New_York 仍是 2026-09-06。证据原文/元数据保存在同目录 `cad-*-evidence.json`；这些日期是此次实际观察值，不是建议直接部署最新开发提交。
