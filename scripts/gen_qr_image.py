#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把配网二维码 PNG 预解码成 LVGL 的 RGB565 常量图（.bin），供 EMBED_FILES 使用。

为什么需要这一步
----------------
本仓库关闭了 LVGL 图片缓存（CONFIG_LV_CACHE_DEF_SIZE=0）：把 PNG/JPEG 这类压缩图
直接当作 lv_image 的源时，每一帧都要重新解码。128x128 的 PNG 解码缓冲约 32KB，而
ESP32-C3 在蓝牙配网阶段（BLE 与 Wi-Fi 共存）几乎不剩堆，解码必然失败，表现为
配网二维码不显示。预解码成 RGB565 常量图后，绘制时不再需要解码，也不需要堆。

用法
----
    python scripts/gen_qr_image.py [输入.png] [输出.bin]

默认输入 main/assets/common/xl_ble_prov.png，
默认输出 main/assets/common/xl_ble_prov_qr.rgb565。
改图后需重新执行本脚本，并在 main/CMakeLists.txt 里确认 BLUFI_ASSETS 指向新产物。

限制：只支持 8bit RGB/RGBA、非隔行（interlace=0）的 PNG；其它格式直接报错退出，
避免静默产出错误的图像数据。
"""

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "main" / "assets" / "common" / "xl_ble_prov.png"
DEFAULT_OUTPUT = ROOT / "main" / "assets" / "common" / "xl_ble_prov_qr.rgb565"


def read_png_rgba(path: Path):
    """解码非隔行 8bit RGB/RGBA PNG，返回 (width, height, rgba_bytes)。"""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: 不是 PNG 文件")

    pos = 8
    width = height = None
    color_type = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8:
                raise SystemExit(f"{path}: 只支持 8bit PNG（当前 {depth}bit）")
            if color_type not in (2, 6):
                raise SystemExit(f"{path}: 只支持 RGB(2)/RGBA(6) PNG（当前 colortype={color_type}）")
            if interlace != 0:
                raise SystemExit(f"{path}: 不支持隔行 PNG")
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break

    if width is None:
        raise SystemExit(f"{path}: 缺少 IHDR")

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise SystemExit(f"{path}: 解压数据长度异常 {len(raw)} != {expected}")

    # PNG 逐行反滤波（filter 0..4）
    out = bytearray()
    prev = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(up - up_left), abs(left - up_left), abs(left + up - 2 * up_left)
                predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[i] = (line[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise SystemExit(f"{path}: 未知的行滤波类型 {filter_type}")
        out += line
        prev = line
    return width, height, bytes(out), channels


def to_rgb565(width: int, height: int, pixels: bytes, channels: int) -> bytes:
    """按 LVGL 的原生 RGB565（小端）逐像素转换。"""
    out = bytearray()
    for i in range(0, len(pixels), channels):
        r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += struct.pack("<H", value)
    if len(out) != width * height * 2:
        raise SystemExit("RGB565 输出长度异常")
    return bytes(out)


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    width, height, pixels, channels = read_png_rgba(src)
    rgb565 = to_rgb565(width, height, pixels, channels)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(rgb565)
    print(f"{src.name}: {width}x{height} -> {dst} ({len(rgb565)} bytes, RGB565)")
    print(f"对应 LVGL 描述符: w={width}, h={height}, stride={width * 2}, data_size={len(rgb565)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
