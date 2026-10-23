"""对比：手机端直出 420 宽 vs 解码后再缩放。"""
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"E:\code\单词pk")
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import av
from PIL import Image

from adb_parse import pick_serial
from screen_stream import NoSeekRaw

ADB = r"C:\Users\A\AppData\Local\Android\Sdk\platform-tools\adb.exe"


def run(size: str, seconds: float = 6.0):
    ser = pick_serial(ADB)
    cmd = [ADB, "-s", ser, "exec-out", "screenrecord",
           "--output-format=h264", "--bit-rate", "4000000",
           "--size", size, "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    t0 = time.perf_counter()
    container = av.open(NoSeekRaw(proc.stdout), format="h264")
    stream = container.streams.video[0]

    n = 0
    first_t = None
    decode_ms = []
    resize_ms = []
    encode_ms = []
    w = h = 0
    try:
        for frame in container.decode(stream):
            now = time.perf_counter()
            if first_t is None:
                first_t = now
            if now - first_t > seconds:
                break

            t1 = time.perf_counter()
            img = frame.to_image()
            t2 = time.perf_counter()
            w, h = img.size
            if w != 420:
                img = img.resize((420, int(h * 420 / w)), Image.BILINEAR)
            t3 = time.perf_counter()
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=62)
            t4 = time.perf_counter()

            decode_ms.append((t2 - t1) * 1000)
            resize_ms.append((t3 - t2) * 1000)
            encode_ms.append((t4 - t3) * 1000)
            n += 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    dur = (time.perf_counter() - t0 - seconds)
    def avg(x):
        return sum(x) / len(x) if x else 0
    return {
        "size": size, "frames": n, "wh": (w, h),
        "decode": avg(decode_ms), "resize": avg(resize_ms),
        "encode": avg(encode_ms),
        "total": avg(decode_ms) + avg(resize_ms) + avg(encode_ms),
    }


def main():
    print("对比手机端直出 420 vs 解码后缩放\n")
    results = []
    for size in ("480x1066", "420x932"):
        print(f"--- {size} ---")
        r = run(size)
        results.append(r)
        print(f"  解出 {r['frames']} 帧，输出 {r['wh']}")
        print(f"  to_image {r['decode']:.2f}ms  缩放 {r['resize']:.2f}ms  "
              f"JPEG {r['encode']:.2f}ms")
        print(f"  合计 {r['total']:.2f}ms/帧")
        print()

    a, b = results[0], results[1]
    print("=" * 58)
    print(f"  480x1066 总 {a['total']:.2f}ms  ->  {a['total'] and 1000/a['total']:.0f} fps 上限")
    print(f"  420x932  总 {b['total']:.2f}ms  ->  {b['total'] and 1000/b['total']:.0f} fps 上限")
    if a["total"] and b["total"]:
        print(f"  提速 {a['total']/b['total']:.1f}x")
    print("=" * 58)


if __name__ == "__main__":
    main()
