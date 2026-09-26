#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成小内存板的「待机小聆动图 + 其余静态图」表情集（输出到 main/assets/xl_emoji/idle/）。

为什么需要它
------------
小聆风格会把待机情绪 `neutral` 映射成 `ready`，而 `ready/waiting` 只存在于 240px 的那套
小聆 GIF 里。那块 GIF 直接放不下：`gifdec.c` 按 5 字节/像素分配画布，240x124 = 145KB，
而无 PSRAM 的 ESP32-C3 总共只有约 230KB 堆。

折中方案（本脚本产出的集合，配合 main/CMakeLists.txt 里 `xl_idle_gif` 分支）：
- `ready`：缩小版小聆动图（默认 96x50 → 画布约 25KB），只在**待机**时占用；
  一旦情绪换成别的，`SetEmotion()` 会先释放旧 GIF，画布就还给对话/音频用；
- 其余 10 个小聆情绪名：直接用 xiaozhi-fonts 的 32px 静态表情图（几乎不占堆），
  避免聊天时再分配动图画布。

用法
----
    python scripts/gen_xl_emoji_small.py [--size 96x50] [--source main/assets/xl_emoji/240]

依赖 Pillow（系统 python 已带；IDF 虚拟环境里没有）。源 GIF 与 32px 静态图分别来自
main/assets/xl_emoji/240/ 与 managed_components/78__xiaozhi-fonts/png/twemoji_32/。
"""

import argparse
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageSequence
except ImportError:  # pragma: no cover
    print("需要 Pillow：请用带 Pillow 的 python 运行本脚本（pip install Pillow）", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "main" / "assets" / "xl_emoji" / "240"
DEFAULT_OUTPUT = ROOT / "main" / "assets" / "xl_emoji" / "idle"
STATIC_SOURCE = ROOT / "managed_components" / "78__xiaozhi-fonts" / "png" / "twemoji_32"

# 小聆情绪名 -> 32px 静态图文件名（不含扩展名）
STATIC_MAP = {
    "happy": "happy",
    "waiting": "funny",
    "sad": "sad",
    "angry": "angry",
    "loving": "loving",
    "surprised": "surprised",
    "confused": "confused",
    "delicious": "delicious",
    "kissy": "kissy",
    "sleepy": "sleepy",
}


def shrink_gif(src: Path, dst: Path, size: tuple[int, int]) -> None:
    """把源动图等比缩到 size，并保留帧数/时长/无限循环。"""
    im = Image.open(src)
    frames = []
    durations = []
    for frame in ImageSequence.Iterator(im):
        durations.append(frame.info.get("duration", 60))
        # 源图是黑底不透明，直接转 RGB 缩放即可（暗色主题下与原生观感一致）
        frames.append(frame.convert("RGB").resize(size, Image.LANCZOS))

    # 用所有帧共用量化，避免 GIF 逐帧调色板导致颜色抖动
    sheet = Image.new("RGB", (size[0], size[1] * len(frames)))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (0, i * size[1]))
    palette = sheet.quantize(colors=255, method=Image.MEDIANCUT)

    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    dst.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        dst,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        disposal=1,
        optimize=True,
    )
    print(f"{src.name}: {im.size} x{len(frames)}帧 -> {dst.relative_to(ROOT)} {size[0]}x{size[1]} ({dst.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="96x50", help="待机动图尺寸，默认 96x50（画布约 25KB）")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="240px 小聆 GIF 目录")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出目录")
    args = parser.parse_args()

    w, h = (int(v) for v in args.size.lower().split("x"))
    source = Path(args.source)
    output = Path(args.output)
    ready_src = source / "ready.gif"
    if not ready_src.exists():
        print(f"找不到待机源动图：{ready_src}", file=sys.stderr)
        return 1

    output.mkdir(parents=True, exist_ok=True)
    shrink_gif(ready_src, output / "ready.gif", (w, h))

    if not STATIC_SOURCE.exists():
        print(f"找不到 32px 静态表情目录：{STATIC_SOURCE}（先构建一次让组件下载完成）", file=sys.stderr)
        return 1
    for name, src_name in STATIC_MAP.items():
        src = STATIC_SOURCE / f"{src_name}.png"
        if not src.exists():
            print(f"缺少静态图：{src}", file=sys.stderr)
            return 1
        shutil.copyfile(src, output / f"{name}.png")
    print(f"静态图 {len(STATIC_MAP)} 张已复制到 {output.relative_to(ROOT)}")
    print(f"动图待机画布约 {5 * w * h / 1024:.1f}KB（gifdec 5B/px），仅在待机情绪下常驻")
    return 0


if __name__ == "__main__":
    sys.exit(main())
