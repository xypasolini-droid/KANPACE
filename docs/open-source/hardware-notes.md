# KANPACE 工牌与工业连接：选型备注

核验日期：2026-09-06。主清单为 [hardware.json](./hardware.json)，含15项主要选择及OPC UA/Modbus两项补充。许可证核验依据上游原文；维护时间保留GitHub release条目`updated`或commit时间，不把条目更新时间冒充最初发布日期。全部为只读研究，没有接触串口、联网工牌、烧写固件、读取秘密文件或执行下载的项目代码。

建议近期继续使用现有Arduino/Adafruit固件、Python USB桥与业务事务，将无线报工和手机/工位扫码做完整。设备数量增长时接入Mosquitto与兼容MQTT client。图形库更换应由实际刷新耗时或维护成本触发；OTA双槽、完整离线语音和机台通信需要独立的资源与平台选择。

## 已确认的板级事实

本地只读查看了`outputs/cabinet-flow/firmware/goldenmorning-display/platformio.ini`及`README.md`：金逸晨ESP32-C3FH4，4MB Flash，ST7789 170×320，CST816D触摸。背光GPIO0、状态灯1、触摸reset/IRQ 2/3、SDA/SCL 4/5、LCD SCLK/MOSI 6/7、LCD reset8、BOOT9、DC10；CS固定有效，40MHz、MODE3。当前使用固定提交的Adafruit ST7735/ST7789、GFX、BusIO与TJpg_Decoder，已有成熟中文和图册管线。

README声明单3MB应用分区、960KiB LittleFS，USB业务报工，Wi-Fi HTTP任务下发；**未实现无线报工**。设备先持久化再回任务ACK，保留32个投递摘要；8条执行outbox、同任务一条未确认事件，等待业务ACK后才改变状态。LAN/VPN下的端到端无线成功率、当前可用堆和功耗均没有在本次研究中实测。

C3是160MHz单核、400KB片内SRAM，不能借用S3示例的PSRAM假设。170×320 RGB565整帧需108800字节，双全帧217600字节；这是尺寸计算，尚未计入Wi-Fi、TLS、任务JSON和图像解码。LVGL试点应从局部缓冲开始，约1/10屏为10880字节。[Espressif C3数据手册](https://documentation.espressif.com/esp32-c3_datasheet_en.html)、[LVGL partial rendering](https://lvgl.io/docs/open/9.2/porting/display)

## 总报告应保留的关键区别

1. **C3并非完全不能用ESP-SR，但能力很有限。** 官方自2025-04-21加入WakeNet9s，明确面向没有PSRAM/SIMD的C3/C5。MultiNet命令识别及AFE目标表不含C3，不能把唤醒词说成自由中文语音控制。当前组件manifest为2.5.3、要求IDF≥5.0；旧GitHub release2.0.0不能说明新C3能力。ESP-SR使用带Espressif产品限制的“ESPRESSIF MIT”且构建中链接预编译库，不能列为标准MIT、全部算法源码开放。[官方README](https://github.com/espressif/esp-sr)、[许可证](https://github.com/espressif/esp-sr/blob/master/LICENSE)、[构建定义](https://github.com/espressif/esp-sr/blob/master/CMakeLists.txt)

2. **Whisper放主机。** whisper.cpp官方tiny参考磁盘75MiB、内存约273MB，远超本板。手机或工位录音、本机转写、显示草稿并确认，适合暂停/交接备注；语音不能直接替代完工和质检事务。[whisper.cpp内存与平台说明](https://github.com/ggml-org/whisper.cpp)

3. **有otadata不等于已具备可靠OTA。** 标准可回滚OTA需要至少两个应用槽；当前3MB单应用无法在4MB Flash里原样复制两份。须先测真实镜像占用，再考虑字体/资源重分配或下一代更大Flash硬件。签名、TLS、Flash encryption、NVS encryption作用不同；当前试验板可继续受控USB app-only更新。[C3 OTA文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/system/ota.html)、[Flash与NVS加密边界](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/security/flash-encryption.html)

4. **ESP Web Tools默认安装流程有数据保留风险。** 现有JSONL配网不是Improv，默认识别失败会视作新安装并可能擦除数据。优先用esptool/esptool-js封装板型核验、应用地址白名单和刷后重握手。C3 bootloader偏移0x0不能照抄经典ESP32的0x1000；浏览器刷机前释放Python占用的串口。[ESP Web Tools默认行为](https://esphome.github.io/esp-web-tools/)、[esptool-js能力边界](https://github.com/espressif/esptool-js)

5. **现行EMQX应归source-available。** 5.9起为BSL1.1；单节点额外许可不允许任意嵌入向第三方提供的解决方案。特定版本四年后转Apache2，不能提前按Apache用。旧5.8 Apache社区版已于2026-02-28结束维护；Enterprise5.8的生命周期不可套到社区版。[当前LICENSE](https://github.com/emqx/emqx/blob/master/LICENSE)、[官方FAQ](https://www.emqx.com/en/content/license-faq)、[社区EOL公告](https://www.emqx.com/en/news/a-notice-on-the-emqx-5-8-open-source-version)

6. **ESPHome不是全MIT。** Python/其他部分MIT，C/C++ runtime GPLv3。可用作独立辅助传感器或呼叫节点，替换现有工牌要重做正式任务状态机、outbox和图册，不值得仅为统一生态而重刷。[许可证原文](https://github.com/esphome/esphome/blob/dev/LICENSE)

7. **CST816S与CST816D不能只靠型号相近就判定已适配。** LovyanGFX和Espressif触摸组件README明确列CST816S；ESPHome的CST816文档明确列CST816D。新驱动仍需验证ID、触摸IRQ、坐标和休眠唤醒。官方cst816s1.1.2及esp_lvgl_port2.9.0都要求IDF≥5.2，不能直接套进当前Arduino2基线。[LovyanGFX矩阵](https://github.com/lovyan03/LovyanGFX)、[Espressif触摸组件](https://components.espressif.com/components/espressif/esp_lcd_touch_cst816s/versions/1.1.2/readme)、[ESPHome CST816](https://esphome.io/components/touchscreen/cst816/)

## 无线可靠性建议（项目设计推断）

MQTT可改善多设备主动连接、在线状态和双向消息组织，但并不自动修复VPN或AP隔离。建议保留原有业务载荷，USB、HTTP、MQTT统一调用同一处理器；`delivery_id`用于派工，`event_id`用于报工，两个ACK的含义继续区分。

建议采用QoS1与稳定业务ID：设备写Flash后提交；主机对事件去重、检查任务/负责人/版次、更新状态、保存结果并在**同一事务完成后**发`execution_ack`。跨通道重复投递仍返回同一结果。协议层PUBACK不能表明生产事务完成；ESP-MQTT默认outbox及Paho会话也不能当成掉电持久业务队列。[ESP-MQTT语义](https://docs.espressif.com/projects/esp-mqtt/en/latest/esp32/)、[Paho已知持久化限制](https://github.com/eclipse-paho/paho.mqtt.python#known-limitations)

建议topic为`kanpace/v1/devices/{device_id}/{task|delivery_ack|execution|execution_ack|availability}`。按设备ACL；动作命令不retain，离线任务加过期时间和版次；先保持现有8条业务队列，满队列明确阻止新增，重试同ID并退避。图片保留manifest、版本/哈希、分块下载和原子替换，不作为单个大MQTT载荷。

当前Python后端优先Paho接Mosquitto，避免仅为MQTT.js引入Node。MQTT.js适合已有Node服务或确需浏览器WS/WSS连接的场景。ESP-MQTT1.1.0要求IDF≥5.3，因此须选兼容当前框架的client版本或先做IDF升级验证。[ESP-MQTT manifest](https://github.com/espressif/esp-mqtt/blob/master/idf_component.yml)、[MQTT.js](https://github.com/mqttjs/MQTT.js)

## 扫码与机台接口边界

ZXing浏览器层适合手机/工位相机和上传图片。USB键盘式扫描枪走输入框，它不属于ZXing支持的实体硬件驱动。手机相机需权限与安全上下文，LAN普通HTTP可打开页面不等于可录音/扫码；短ID二维码解析后仍须服务端确认设备、任务与权限。[ZXing浏览器层](https://github.com/zxing-js/browser)、[W3C媒体捕获规范](https://www.w3.org/TR/mediacapture-streams/)

open62541适合工位网关读取机台OPC UA NodeId、订阅运行/告警/计数；PyModbus与现有Python后端贴合，可经网口或USB-RS485读取有文档的寄存器。两者都优先放网关，当前工牌不承担PLC协议集中器。Modbus需明确地址基准、字节序、倍率、ID、计数清零/回绕；机器状态必须保留源时间和质量码，掉线标记unknown，不能自动算完工或产量。[open62541官方说明](https://github.com/open62541/open62541)、[PyModbus官方说明](https://github.com/pymodbus-dev/pymodbus)

## 维护证据速查

下列日期为GitHub发布条目更新时间或默认分支提交时间；具体字段和版本在JSON中保留。

| 项目 | 可见维护证据 | 建议 |
|---|---|---|
| ESP-IDF（含官方 OTA、rollback、Secure Boot、Flash/NVS encryption） | [ESP-IDF Release v6.1](https://github.com/espressif/esp-idf/releases/tag/v6.1) · 2026-08-27 | 直接用官方组件；分阶段迁移。现板先保留已验证 USB app-only 更新，双槽 OTA 待分区预算解决后加入。 |
| Arduino-ESP32 | [Arduino Release v3.3.11 based on ESP-IDF v5.5.5](https://github.com/espressif/arduino-esp32/releases/tag/3.3.11) · 2026-07-23 | 直接继续用；先锁版本，不为开源选型而重写可用工牌。 |
| LVGL | [Release v9.5.0](https://github.com/lvgl/lvgl/releases/tag/v9.5.0) · 2026-02-18 | 按需借鉴/试点；只在交互复杂度或维护收益明确时引入。 |
| LovyanGFX | [1.2.28](https://github.com/lovyan03/LovyanGFX/releases/tag/1.2.28) · 2026-08-25 | 借鉴并作为显示性能候选；当前稳定 Adafruit 无瓶颈时无需替换。 |
| TFT_eSPI | [Update README.md](https://github.com/Bodmer/TFT_eSPI/commit/16e37595040eac69cd628e4bffb56fc30cad6299) · 2026-04-03 | 备选借鉴；没有明确性能收益时不迁移。 |
| esp_lcd + esp_lcd_touch + esp_lvgl_port（ESP-BSP） | [Merge pull request #822 from Kainarx/feat/add_lt9611_conponent](https://github.com/espressif/esp-bsp/commit/b1bc71e7980663110055fbeba7eab59d5e689c2b) · 2026-09-04 | 中期直接用官方抽象；CST816D适配保留验证闸口。 |
| esptool | [Version 5.4.0](https://github.com/espressif/esptool/releases/tag/v5.4.0) · 2026-09-02 | 直接用，优先封装为受控维护流程。 |
| ESP Web Tools + esptool-js | [10.4.0](https://github.com/esphome/esp-web-tools/releases/tag/10.4.0) · 2026-07-15 | 借鉴安装体验；受控集成esptool-js。默认全擦安装不建议直接引入。 |
| ESP-MQTT + Mosquitto + MQTT.js（Python侧优先Paho） | [v1.1.0](https://github.com/espressif/esp-mqtt/releases/tag/v1.1.0) · 2026-07-30 | 直接用Mosquitto和兼容client；业务可靠性继续由现有outbox/幂等事务保证。MQTT.js仅在确需Node/浏览器MQTT时引入。 |
| ESPHome | [2026.8.2](https://github.com/esphome/esphome/releases/tag/2026.8.2) · 2026-08-31 | 借鉴配网/维护与辅助节点；不建议重刷当前工牌改用ESPHome。 |
| ThingsBoard Community Edition | [ThingsBoard 4.3.1.4 Release](https://github.com/thingsboard/thingsboard/releases/tag/v4.3.1.4) · 2026-08-27 | 借鉴设备管理；暂不引入为主业务平台。 |
| EMQX（现行统一版） | [EMQX Enterprise (LTS) 6.3.0](https://github.com/emqx/emqx/releases/tag/6.3.0) · 2026-09-03 | 当前不建议作为开源默认选项；有集群/商业支持需求时单独核验商业条款。 |
| ESP-SR（WakeNet9s / MultiNet / AFE） | [Merge branch 'fix/esp32s31_docs-f' into 'master'](https://github.com/espressif/esp-sr/commit/efa8d907c6d457cd0f99dae6c6b493412d3078d4) · 2026-09-04 | 仅借鉴/小范围试验WakeNet9s；完整语音输入放手机/工位主机。 |
| whisper.cpp | [v1.9.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.3) · 2026-08-20 | 主机侧可直接试点；C3端不建议。 |
| ZXing for JS：@zxing/browser + @zxing/library | [v0.2.1](https://github.com/zxing-js/browser/releases/tag/v0.2.1) · 2026-07-06 | 直接用在手机/工位；扫描枪作为并列输入入口。 |
| open62541（OPC UA） | [v1.5.8](https://github.com/open62541/open62541/releases/tag/v1.5.8) · 2026-09-06 | 有实际OPC UA设备后直接用于网关只读采集；不建议放工牌。 |
| PyModbus（Modbus TCP / RTU） | [Pymodbus v3.15.0](https://github.com/pymodbus-dev/pymodbus/releases/tag/v3.15.0) · 2026-08-13 | 有寄存器文档时直接用作网关只读采集；工牌端不建议。 |
