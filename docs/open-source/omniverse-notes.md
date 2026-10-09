能用得上，但应作为 KANPACE 的 CAD 格式补充与装配可视化转换节点。官方 [omniverse-cad-to-usd 技能](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/SKILL.md) 已找到并只读阅读：v0.2.0 使用独立 Python 3.12 wheel，不再依赖 Omniverse Kit。没有安装或执行任何技能/转换器。

真正新增的价值是读取真实 STEP、SLDPRT、SLDASM 等，形成带装配层级、实例、名字、变换与选配元数据的 USD。它可以帮助把真实模型接到分工界面，输出仍是三角化可视化资产；工程 BOM 应以源 BOM/施工图和人工确认关联。[官方数据映射](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/docs/concept_mapping.md) 明确没有原生 B-rep 往返、完整约束、可视或可编辑 PMI。效果图不能借这个技能恢复准确加工尺寸、孔位、公差或工艺。

当前 Mac 不在官方平台里。[NVIDIA wheel 索引](https://pypi.nvidia.com/usd-convert-cad/) 实际有 Windows amd64、Linux x86_64、Linux aarch64 的 CPython 3.12 包。Linux aarch64 还不支持 AutoCAD DWG/DXF 与 Revit。可让 KANPACE 在 Mac 上继续运行 Web，把转换作业交给合适的自有 Windows/Linux 节点。转换前仍须验证真实文件版本和引用完整性。

这里必须分清三层许可：技能文档 CC-BY-4.0、技能代码 Apache-2.0；OpenUSD 本身是 Tomorrow Open Source Technology License 1.0，OpenUSD Exchange SDK 是 Apache-2.0；实际转换 runtime 使用 NVIDIA 协议并包含专有 HOOPS Exchange SDK，不能列为纯开源。[技能许可](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/skills/omniverse-cad-to-usd/LICENSE.md)、[依赖声明](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/THIRD_PARTY_NOTICES.md)、[转换器根许可](https://github.com/NVIDIA-Omniverse/usd-convert-cad/blob/main/LICENSE.md)。

独立 wheel 技术前置条件未列 RTX 型号，也不要求 Kit。但 [NVIDIA AI 产品条款](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/) §8.15 对 Omniverse 专有组件规定 NVIDIA Platforms 条件；[主协议](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) §17.30 的定义包括 NVIDIA GPU 或 NVIDIA CPU 系统。应核实所用包的生产权益、硬件条件及分发条款，不能凭免费 pip 下载认定任意商用，也不能未经证据宣称必须额外买 HOOPS 或企业订阅。

网页接入有两条路线：常规路线保留 Three.js，另做 USD→GLB/网页网格适配并保留 BOM ID、层级、变换和单位；该转换器自己只输出 USD/USDA/USDC，GLB 是输入，USDZ 也暂不支持。另一条是在支持的 Windows/Linux RTX 服务上开 Kit 渲染，再通过 [Omniverse WebRTC](https://docs.omniverse.nvidia.com/ov-web-sdk/latest/web-streaming-library/overview.html) 嵌入网页，这增加了运行时与渲染服务。Kit 的 GPU 要求不应直接套给 kitless 转换。

仓库最新观察提交为 [2026-07-30 / Release v0.2.0](https://github.com/NVIDIA-Omniverse/usd-convert-cad/commit/208fe2c1cd71ae2bb7bd825daf712617000ae028)，包也为 0.2.0。官方来源与底层 CAD SDK可信，但新封装未在 KANPACE 样本实测。建议列“条件采用 / 专有依赖补充”，保留现有 OCCT + Three.js 主线；先用真实 STEP 与完整 SLDASM 样本验证，再决定接入。机器可读证据见 omniverse.json。
