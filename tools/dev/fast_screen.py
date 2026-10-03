"""快速变化检测：用 screencap 判断「题目是否已经换了一题」。

4s 限制下，dump(2.6s) 太慢，但 screencap(0.6s) 可以每秒 1-2 次。
思路：题目框区域(题干)一变，说明刷新了新题 -> 立刻用上一轮算好的答案点击。

这里实现像素级快速比较，只比题干矩形区域，代价极小。
"""
from __future__ import annotations

import hashlib
import io
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import ADB  # noqa: E402


def screencap_bytes() -> bytes:
    p = subprocess.run([ADB, "exec-out", "screencap", "-p"],
                       capture_output=True, timeout=20)
    return p.stdout


def png_to_rgb(data: bytes):
    """极简 PNG 解码：只支持 screencap 输出的 8bit RGBA/RGB 非隔行。

    返回 (w, h, bytes)。避免引入 Pillow 依赖。
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not png")
    pos = 8
    w = h = bitdepth = colortype = None
    idat = bytearray()
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bitdepth, colortype = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln

    if bitdepth != 8:
        raise ValueError(f"bitdepth {bitdepth} unsupported")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colortype]
    raw = zlib.decompress(bytes(idat))

    stride = w * channels
    out = bytearray(stride * h)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, channels, bytes(out)


def crop_hash(img, rect, step: int = 4) -> str:
    """对矩形区域做稀疏采样哈希，用于快速判断变化。"""
    w, h, ch, px = img
    x1, y1, x2, y2 = rect
    md5 = hashlib.md5()
    for y in range(max(0, y1), min(h, y2), step):
        base = y * w * ch
        for x in range(max(0, x1), min(w, x2), step):
            o = base + x * ch
            md5.update(px[o:o + 3])
    return md5.hexdigest()


if __name__ == "__main__":
    t0 = time.perf_counter()
    data = screencap_bytes()
    t1 = time.perf_counter()
    img = png_to_rgb(data)
    t2 = time.perf_counter()
    print(f"screencap {t1-t0:.3f}s  decode {t2-t1:.3f}s  size={img[0]}x{img[1]} ch={img[2]}")

    # 题干框位置（实测 1260x2800: [330,690]-[930,850] 附近）
    rect = (330, 660, 930, 860)
    t3 = time.perf_counter()
    hh = crop_hash(img, rect)
    t4 = time.perf_counter()
    print(f"crop_hash {t4-t3:.4f}s  -> {hh[:16]}")

    # 连续 5 次，看总耗时
    print("\n-- 连续 5 次 poll --")
    for i in range(5):
        a = time.perf_counter()
        d = screencap_bytes()
        im = png_to_rgb(d)
        hh = crop_hash(im, rect)
        b = time.perf_counter()
        print(f"  poll {i}: {b-a:.3f}s  hash={hh[:12]}")
