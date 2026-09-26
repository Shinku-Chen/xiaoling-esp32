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

- **OK**：单击切换对话状态（开机阶段单击进入配网）
- **UP**：单击音量 +10；长按最大音量
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
2. **默认必须改用 Wi-Fi AP 配网**：小聆默认的 BLE 配网（Blufi）在此板上需要额外约
   56 KB，实测开启后启动阶段堆仅剩约 5 KB，`BLE_INIT: Malloc failed`，随后本地提示音
   解码分配失败（`audio_service.cc` 的 `std::vector<int16_t> resampled` 抛
   `std::bad_alloc` 且无人捕获）→ `abort()` 重启循环。改用 AP 配网
   （`CONFIG_PROV_MODE_XIAOZHI=y`）后空闲堆约 61 KB，设备正常运行：
   配网 AP `Xiaoling-xxxx` + `http://192.168.4.1` 网页配置，连上后进入 activating
   并显示激活码与二维码。

因此本板当前的可用构建方式：在 `config.json` 的 `sdkconfig_append` 里加
`CONFIG_PROV_MODE_XIAOZHI=y`（本次上机验收用的镜像就是该配置），或先手工在 sdkconfig
追加同一行再 `idf.py build`。是否把这一项固化进 `config.json` 属产品取舍，待确认。

保留 BLE 配网需要先在小聆方案里再腾出约 60 KB 堆（例如关闭 `LSPLATFORM_BANNERS`、
缩小 LVGL/音频缓冲），属产品取舍，未在本板默认配置中改动。
