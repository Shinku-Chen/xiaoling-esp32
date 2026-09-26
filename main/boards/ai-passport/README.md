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
2. **BLE 配网需要额外约 56 KB，且配网完成后不会释放**：小聆默认的 BLE 配网（Blufi）在这块板上要配套两项板级配置才能起来：
   - 关闭开机提示音（`CONFIG_DISABLE_STARTUP_SOUND=y`）——否则播配网提示音时堆只剩约 5 KB，
     音频重采样缓冲分配失败（`std::bad_alloc` 无人捕获）→ `abort()` 重启循环；
   - 裁剪 Wi-Fi/BT 缓冲（`config.json` 里的 `ESP_WIFI_DYNAMIC_TX_BUFFER_NUM` / `BT_CTRL_BLE_MAX_ACT` 等）——
     否则 BLE 初始化阶段就会 `Malloc failed`。

   两者都落到 `config.json` 后，设备可稳定运行、BLE 正常广播并显示配网二维码。
   **仍然受限的是配网之后的阶段**：BLE 配网成功后从不释放（`esp_blufi_host_deinit` 只有定义、无调用方），
   常驻的 56 KB 会挤掉激活用的 TLS 缓冲与语音解码缓冲。要根本解决需要在 fork 里做内存优化
   （配网后释放 BLE、Opus 编码器延迟创建、BT 主机换 NimBLE），属共享代码改动，未包含在本板支持里。

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
