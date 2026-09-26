# FoloToy AI Passport (ai-passport)

让「小聆 AI」运行在 [FoloToy AI Passport](https://github.com/FoloToy/ai-passport) 徽章设备上的板级定义。

## 硬件

- MCU：ESP32-C3，8 MB Flash，**无 PSRAM**，控制台走 USB Serial/JTAG
- 音频：ES8311（I2C 地址 0x18，与电量计共用 I2C 总线），I2S 全双工（功放使能未接到 MCU，视为常开）
- 屏幕：ST7789（ST7789P3）240x320 竖屏，4 线 SPI
- 电池：CW2017 电量计（I2C 地址 0x63，可选，缺失时只是不显示电量）
- 按键：UP / DOWN / OK 通过电阻梯共享 GPIO0（ADC1_CH0）

引脚映射与 `ai-passport/components/bsp/include/bsp_pins.h` 一致：

| 功能 | 引脚 |
| --- | --- |
| LCD MOSI / SCLK / CS / DC | 9 / 8 / 1 / 20 |
| LCD 背光（PWM） | 21 |
| I2S MCLK / BCLK / WS / DOUT / DIN | 6 / 5 / 3 / 2 / 4 |
| I2C SDA / SCL | 10 / 7 |
| 按键（ADC 电阻梯） | GPIO0 |

## 编译

```sh
python scripts/release.py ai-passport
```

产物为 `build/merged-binary.bin`（8 MB Flash，`partitions/v2/8m.csv`，USB Serial/JTAG 控制台）。
由于 Flash 为 8 MB，而 `sdkconfig.defaults.esp32c3` 默认是 16 MB，板级 `config.json` 里
显式覆盖了 Flash 大小与分区表，不要手工改成其它分区表。

## 按键

三个物理键对应语音助手的常用操作：

- **OK**：单击切换对话状态（开机阶段单击进入配网）- **UP**：单击音量 +10；长按最大音量
- **DOWN**：单击音量 -10；长按静音

电阻梯共用一个 ADC 引脚，因此按三路独立 ADC 按键解析（与 ESP-BOX-Lite 同一套做法）。
上游 XiaoZhi 的板级定义默认关闭唤醒词（`CONFIG_USE_ESP_WAKE_WORD=n`），由 OK 键手动起停对话；
本板沿用该行为，如需常开唤醒词，改 `config.json` 里的这一项即可（C3 无 PSRAM，注意 Flash 占用）。

## 备注 / 标定

- 屏幕方向、颜色反转与背光极性取自 Passport BSP；实测如果画面旋转/反色或背光相反，
  调整 `config.h` 里的 `DISPLAY_*` 宏。
- 按键电压窗口假定 Passport 外部 10 kOhm 上拉，阈值漂移时用电压实测值重新标定
  `BSP_ADC_BUTTON_*` 宏。
- CW2017 是否焊有是可选的；没有该芯片时状态栏不显示电量，其余功能不受影响。

## 内存约束（ESP32-C3，无 PSRAM）

实测该板只剩约 230 KB 堆，运行小聆（LSPLATFORM）方案时有两处硬约束：

1. **表情集只能用 32 px**：小聆表情是 240x124 的 GIF，`gifdec.c` 按 5 字节/像素
   分配画布（约 145 KB），无法与 Wi-Fi/音频/LVGL 共存（改前实测空闲堆只剩 5-6 KB）。
   本板用 `twemoji_32`（上游 XiaoZhi 同名板也是 32 px 表情）；小聆配色的表情名
   （ready/happy/…）在 twemoji_32 中命中一部分，未命中的回落到 FontAwesome 图标。
2. **BLE 配网 + Wi-Fi + 应用在 230 KB 上要精打细算**：这块板最终靠下面三件事才把「蓝牙配网 → 激活 → 对话」跑通
   （2026-09-26 实机验证，全链路无 abort、无 `malloc failed`）：
   - 关闭开机提示音（`CONFIG_DISABLE_STARTUP_SOUND=y`）：否则播配网提示音时堆只剩约 5 KB，
     音频重采样缓冲（2880 B）分配失败 → `std::bad_alloc` 无人捕获 → `abort()` 重启循环；
   - 裁剪 Wi-Fi/TCP/BT 缓冲（见 `config.json`）：不裁剪时 BLE 初始化就会 `Malloc failed`，之后 BLE 安全握手
     要 530 B 也会失败（实测 `BT_OSI: malloc failed size=530`，同时 `largest_block=480`），手机侧表现是
     "卡在接收 wifi 账号"。注意 BT 控制器参数不能压太狠：`BT_CTRL_BLE_MAX_ACT=1` 会让广播起不来
     （`Advertising start failed, status 3`），本板保持 2；
   - Opus **上行编码器按需创建**（`main/audio/audio_service.cc`，省约 25.8 KB）：不延迟创建时，关联 Wi-Fi 后
     DHCP 争不到 pbuf（1.5~3 KB），拿不到 IP，同样卡在配网。该路径同时改为失败时丢帧 + 报错，
     不再让 `std::bad_alloc` 逃出音频任务触发重启。

   实测链路：BLE 配网（收 SSID/密码 → `sta ip` → 收 `done` → `BLUFI config done` → 自动重启）→
   `Got IP` → `starting -> activating` → `Activation done` → 会话中按需创建编码器
   （`Created Opus encoder on demand`）→ 多轮 `listening/speaking` 正常。

   当前 BLE 仍常驻约 56 KB（`esp_blufi_host_deinit` 无调用方）；激活阶段的服务端二维码
   （`image_fetcher` 按图尺寸分配解码缓冲）在 BLE 常驻下尚未验证。若要再腾空间，可做
   「配网后释放 BLE」（~56 KB）或把 BT 主机换 NimBLE（~20-25 KB），属共享代码改动。

## 待机表情（小聆动图）

240px 的小聆动图放不下（`gifdec` 画布 5B/px，240x124 ≈ 145KB），所以本板用小尺寸方案
（`scripts/gen_xl_emoji_small.py` 生成到 `main/assets/xl_emoji/idle/`，由 CMakeLists 的
`xl_idle_gif` 分支挂上）：

- 待机情绪 `ready`：**96x50 的小聆动图**（画布约 25KB），只在待机时占用；
- 其余 10 个小聆情绪名：32px 静态图（几乎不占堆）。

`SetEmotion()` 换情绪时会先释放旧动图，因此动图画布不会长期与音频/TLS 抢内存。

与之配套、同样必须保留的两条（都是实测踩出来的）：

- **mbedTLS 输入记录缓冲 16384 → 4096**（`CONFIG_MBEDTLS_SSL_IN_CONTENT_LEN`，并打开
  `CONFIG_MBEDTLS_SSL_VARIABLE_BUFFER_LENGTH`）：默认 16KB 输入 + 4KB 输出在建立 WS/TLS 时会
  吃掉会话期仅有的余量，实测导致上行麦克风缓冲（2.8KB）分配失败 → `abort()` 重启循环；
- **上行编码器要尽早创建**（`Application` 在激活完成后调用 `AudioService::PrepareUplinkEncoder()`）：
  Opus 16k 编码器约占 25.8KB 且是一次性大块分配，等对话首帧再建会撞上碎片化，
  `opus_encoder_create()` 返回 `OPUS_ALLOC_FAIL`，而上行会一直发不出去（用户什么也听不到）。
  现在创建前先检查连续块大小、创建后用堆下降量确认真建起来了，失败只丢帧并重试。

上行/解码路径在堆不足时都只丢数据 + 限流打日志，不再让 `std::bad_alloc` 逃出音频任务触发重启。

## 蓝牙配网二维码

配网二维码不再直接嵌 PNG。本仓关闭了 LVGL 图片缓存（`CONFIG_LV_CACHE_DEF_SIZE=0`），
以 PNG/JPEG 这类压缩图作为 `lv_image` 源时每一帧都要重新解码：128x128 需要约 32 KB 解码缓冲，
而 C3 在蓝牙配网阶段只剩几 KB 堆，解码必然失败，表现就是**屏幕上只有文案、没有二维码**。
现改为预解码的 RGB565 常量图（`main/assets/common/xl_ble_prov_qr.rgb565`，32 KB 放 flash），
绘制时不做解码、不占堆。

改图流程（`main/CMakeLists.txt` 的 `BLUFI_ASSETS` 指向产物，改完重新编译即可）：

```sh
python scripts/gen_qr_image.py   # main/assets/common/xl_ble_prov.png -> xl_ble_prov_qr.rgb565
```

注意：激活阶段的服务端二维码（`cdn.iflyos.cn/.../*.jpg`）仍走 `image_fetcher` 的解码路径，
需要按图片尺寸分配解码缓冲，在 BLE 常驻内存的情况下可能同样显示不出来；这要靠上面说的内存优化解决。
