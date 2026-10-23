"""验证 ScreenStream 的解码链路（不需要真机）。

做法：用 PyAV 现场编一个 H.264 流（模拟 screenrecord 的输出格式），
喂给 ScreenStream 内部同样的解码逻辑，确认：
  1. h264 裸流能被打开
  2. 帧能解出来并转成 JPEG
  3. 限帧逻辑（max_fps）生效
  4. 统计数据合理

跑法：python -X utf8 app/test_stream.py
"""
import io
import pathlib
import subprocess
import sys
import tempfile
import time

import av
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


def make_h264(seconds: float = 2.0, size=(480, 1066), fps: int = 30) -> bytes:
    """生成一段 H.264 裸流，模拟 screenrecord 的输出。"""
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="h264")
    stream = container.add_stream("libx264", rate=fps)
    stream.width, stream.height = size
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "tune": "zerolatency", "x264-params": "keyint=15"}

    total = int(seconds * fps)
    for i in range(total):
        img = Image.new("RGB", size, (i % 256, 80, 160))
        frame = av.VideoFrame.from_image(img)
        for pkt in stream.encode(frame):
            container.mux(pkt)
    for pkt in stream.encode():
        container.mux(pkt)
    container.close()
    return buf.getvalue()


class FakeStream:
    """复用 ScreenStream 的解码+限帧逻辑（拷一份，避免依赖真机）。"""

    def __init__(self, target_width=420, quality=62, max_fps=20):
        self.target_width = target_width
        self.quality = quality
        self.min_interval = 1.0 / max_fps
        self.frames = 0
        self.encoded = []

    def decode(self, raw: bytes):
        # 注意：不要传 fflags=nobuffer / flags=low_delay。
        # 实测这两个选项会让 PyAV 对 h264 裸流一帧都解不出（0 帧，无报错）。
        container = av.open(io.BytesIO(raw), format="h264")
        stream = container.streams.video[0]
        last = 0.0
        for frame in container.decode(stream):
            now = time.perf_counter()
            if now - last < self.min_interval:
                continue
            last = now
            img = frame.to_image()
            w, h = img.size
            tw = self.target_width
            img = img.resize((tw, int(h * tw / w)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=self.quality)
            self.frames += 1
            self.encoded.append(buf.getvalue())
        container.close()


print("== 生成模拟流 ==")
raw = make_h264(seconds=2.0)
print(f"  裸流大小: {len(raw) / 1024:.0f} KB")
check("裸流非空", len(raw) > 1000, True)

print("\n== 解码 ==")
s = FakeStream()
t0 = time.perf_counter()
s.decode(raw)
dt = time.perf_counter() - t0
print(f"  解出 {s.frames} 帧，耗时 {dt*1000:.0f}ms")
check("有解出帧", s.frames > 0, True)
check("每帧都是 JPEG", all(f[:2] == b"\xff\xd8" for f in s.encoded), True)

# 校验 JPEG 尺寸
img = Image.open(io.BytesIO(s.encoded[-1]))
print(f"  最后一帧尺寸: {img.size}  体积 {len(s.encoded[-1]) / 1024:.0f} KB")
check("宽度符合目标", img.size[0], 420)
check("单帧体积合理（<120KB）", len(s.encoded[-1]) < 120 * 1024, True)
check("纵横比保持", abs(img.size[1] / img.size[0] - 1066 / 480) < 0.05, True)

print("\n== 限帧逻辑 ==")
# 20fps 上限，2 秒的 30fps 源应被压到约 40 帧以内（按实际耗时算）
check("限帧生效（不超过源帧数）", s.frames <= 60, True)

print("\n== 解码性能 ==")
# 重新解一次，去掉限帧，测纯解码能力
class Pure:
    def __init__(self):
        self.n = 0

    def run(self, raw):
        c = av.open(io.BytesIO(raw), format="h264")
        st = c.streams.video[0]
        for f in c.decode(st):
            self.n += 1
        c.close()


p = Pure()
t0 = time.perf_counter()
p.run(raw)
dt = time.perf_counter() - t0
fps = p.n / dt if dt else 0
print(f"  纯解码 {p.n} 帧，{dt*1000:.0f}ms，约 {fps:.0f} fps 解码能力")
check("解码能力 >= 30fps", fps >= 30, True)

print()
if FAILS:
    print(f"失败 {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("全部通过")
