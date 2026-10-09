# 170×320工牌当前页面与验证边界

参考用户ZIP中的renderTaskPage、renderReportSelectPage、renderQualitySelectPage、renderLockedPage、renderCompletePage、renderSplash及README，仅采用一页突出一个动作/判断、状态明确、底部操作可读的视觉层级；没有采用S3接线、16MB分区或离线演示业务状态。

## 柜序任务模式

| 实际入口 | 可达内容 | 本次处理 |
|---|---|---|
| cabinetScreenSummary | ready、in_progress、done、blocked、invalidated、draft、未知状态 | 24/28px动作，部件/总数与已做/剩余、优先级、暂停原因；收件和生产状态分色；ready使用中性文案 |
| cabinetScreenDetails | 摘要放不下的部件/工序、合并数量、有值暂停/交接、项目、负责人、验收、图纸 | 一字段一组；大标题+最多4行大字；长值续页；顶部回主屏 |
| cabinetScreenNetwork | 未配置、连接中、未找到、失败、已连接 | 相同布局与真实状态色；SSID完整分行；真实IP及2.4GHz配置指引 |
| cabinetScreenIdle | 无任务、未配置/已接入网络、存储错误 | 大字等待派工，USB可继续用，错误明确 |

1.3.1现场显示保留完整项目、任务部件/工序、总量与实际已做/剩余、有效负责人/验收/暂停交接、source中file/reference/model_file/model_reference/revision。摘要能完整呈现的动作/部件不再重复；空项与内部ID、执行时间版本、任意raw字段不建工人页面。原始任务payload不改。

任务页不再有无线状态横幅和“工位”占位字，右上三弧Wi-Fi图标表示连接/连接中/未连接，测试标签独立保留。126≤x<170且y<34进网络详情，详情顶部其他区域回摘要，其余点击/短按BOOT翻页。网络页点击/短BOOT回摘要。网络详情保留状态、SSID/IP和必要配置/返回提示。

ready状态不证明前序已完工，当前任务包没有依赖放行结果；主屏使用“本次任务”，只有非测试in_progress显示“正在执行”。测试标记保留。HTTP成功、设备接收、人员开工、质检与完工没有被合并。

## 原互动/协作模式：21个UiView状态

| 渲染入口 | 状态枚举 |
|---|---|
| renderLinkView | Link，另有配对/重连/掉线真实连接分支 |
| renderHomeView | Home |
| renderChoicePickView | ChoicePick |
| renderChoiceWaitingView | ChoiceWaiting |
| renderChoiceRevealView | ChoiceReveal |
| renderChoiceResultView | ChoiceSpark、ChoiceNext、ChoiceError |
| renderHandshakeOutgoingView | HandshakeOutgoing |
| renderHandshakeIncomingView | HandshakeIncoming |
| renderHandshakeSyncView | HandshakeSync |
| renderHandshakeDeclinedView | HandshakeDeclined |
| renderWaveBase | Wave |
| renderConnectedView | Connected |
| renderSosOutgoingView | SosOutgoing |
| renderSosIncomingView | SosIncoming |
| renderSosSyncView | SosSync |
| renderHelpView(false/true) | HelpSession、HelpWaiting，另有对方已确认分支 |
| renderResolvedView | Resolved |
| renderSosDeclinedView | SosDeclined |

另有启动、初始化错误与阶段提示，以及局部状态脉冲、倒计时和双屏波形刷新。共享shell、连接条、主区域、状态标签、按钮和页脚统一深蓝/金色/真实状态色；常规页面主文字优先于装饰符号。真实触摸区域、双屏动画与倒计时由固件代理保留，协作“解决”不等于生产工单完成。

互动模式的26个注入场景由固件代理维护在hardware-preview/interaction/index.html。柜序48个场景与其分开说明，不把预览张数叫作实板测试次数。

## 参考演示与当前能力边界

参考REPORT_SELECT、QUALITY_SELECT、EXCEPTION_LOCKED、QUALITY_HOLD和COMPLETE使用四条离线任务、本机剩余量与串口演示事件。本轮没有把它们变成可达生产入口，没有自动减件、假品质提交或假解锁。Web已新增实际进度、暂停/恢复、优先级与交接业务API；工牌v1.3接收这些真实状态供工人查看，硬件端仍未提供物理报工、品质提交或完工按钮。收到任务、触摸翻页均不会修改生产状态。

柜序生产header桌面渲染已通过像素边界、146px行宽、每页4行、长验收/来源全文保留校验，预览在hardware-preview/index.html。真实编译、刷写与触摸结果以固件构建报告和实板记录为准。

v1.3.1当前柜序48场景、协作26场景均为离屏验证。主屏含3/10缺料特急与历史进度未记录；数量单卡、空项和raw隐藏、长工序/部件/验收/交接保留均有断言。生产导航函数实际提取到host执行验证图标/返回/翻页热区。协议1的进度等可选字段不变；设备仍只收件显示。
