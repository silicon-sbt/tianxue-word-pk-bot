"""快路径：用 screencap 检测「题目是否换了」，避开 2.6s 的 dump。

原理（利用 PK 回合内题序固定）：
  - dump 贵(2.6s) 但能拿到完整题面+选项坐标
  - screencap 便宜(0.6s) 但只有像素

结合用：
  1. 先用 dump 拿一次「题面 + 选项 + 答案」，并记录题干区域的像素指纹
  2. 之后每 ~0.6s 截一次图，只看题干那小块区域
  3. 指纹一变 => 换题了，立刻按上一轮预算好的答案点

注意：题干区域会变（题面文字不同），所以不能拿"题面区域"当触发源去找答案，
必须每换一题都重新 dump 拿到新的选项坐标。快路径省掉的是"重复 dump 同一题"。
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import ADB, Device  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None


# 题干框（实测 1260x2800: 蓝色边框内大约 [330,690]-[930,850]）
PROMPT_RECT = (340, 690, 920, 850)


def shot(dev: Device) -> "Image.Image":
    if Image is None:
        raise RuntimeError("需要 Pillow: python -m pip install Pillow")
    p = subprocess.run([ADB, "exec-out", "screencap", "-p"],
                       capture_output=True, timeout=20)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def thumb_hash(img, rect=PROMPT_RECT, size=(64, 16)) -> str:
    """对题干区域降采样后做哈希，抗轻微渲染抖动。"""
    crop = img.crop(rect).resize(size, Image.LANCZOS).convert("L")
    return "".join(f"{b:02x}" for b in crop.tobytes())


def bench(dev: Device, n: int = 6) -> None:
    print("-- screencap 快路径基准 --")
    ts = []
    prev = None
    for i in range(n):
        t0 = time.perf_counter()
        img = shot(dev)
        h = thumb_hash(img)
        dt = time.perf_counter() - t0
        ts.append(dt)
        same = "同" if h == prev else "变"
        prev = h
        print(f"  {i}: {dt:.3f}s  hash={h[:12]} {same}")
    print(f"  平均 {sum(ts)/len(ts):.3f}s  (对比 dump 2.53s)")


if __name__ == "__main__":
    dev = Device()
    dev.ensure_connected()
    bench(dev)
