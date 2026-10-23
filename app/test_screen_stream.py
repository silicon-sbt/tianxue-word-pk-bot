"""ScreenStream 集成测试：用假 adb 命令喂模拟 H.264 流（不依赖真机）。

假 adb 是独立脚本，自己生成流并按块慢慢写出，模拟直播流按时到达。
一次性写完全部数据会让限帧逻辑失真（解码瞬间跑完，没有时间间隔）。

跑法：python -X utf8 app/test_screen_stream.py
"""
import io
import pathlib
import sys
import time

import av
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from screen_stream import ScreenStream  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


FAKE = HERE / "_fake_stream_adb.py"
FAKE.write_text('''"""假 adb：生成 H.264 流并按块写出，模拟 screenrecord。"""
import io
import sys
import time

import av
from PIL import Image

FPS = 30
SIZE = (480, 1066)
DURATION = 12.0

buf = io.BytesIO()
c = av.open(buf, mode="w", format="h264")
st = c.add_stream("libx264", rate=FPS)
st.width, st.height = SIZE
st.pix_fmt = "yuv420p"
st.options = {"preset": "ultrafast", "tune": "zerolatency"}

out = sys.stdout.buffer
CHUNK = 8192


def flush_pending():
    raw = buf.getvalue()
    buf.seek(0)
    buf.truncate()
    return raw


for i in range(int(DURATION * FPS)):
    img = Image.new("RGB", SIZE, (i * 5 % 256, 90, 150))
    for pkt in st.encode(av.VideoFrame.from_image(img)):
        c.mux(pkt)
    if i % 3 == 0:
        raw = flush_pending()
        for k in range(0, len(raw), CHUNK):
            out.write(raw[k:k + CHUNK])
        out.flush()
        time.sleep(0.03)

for pkt in st.encode():
    c.mux(pkt)
out.write(flush_pending())
out.flush()
time.sleep(20)
''', encoding="utf-8")

print("== 启动 ScreenStream（注入假命令）==")
stream = ScreenStream(
    adb_path="unused",
    serial_getter=lambda: "fake-serial",
    target_width=420,
    quality=62,
    max_fps=20,
    cmd_builder=lambda serial: [sys.executable, "-X", "utf8", str(FAKE)],
)
stream.start()

t0 = time.time()
time.sleep(3.0)
elapsed = time.time() - t0
st = stream.stats()

print(f"  统计: decoded={st['decoded']}  size={st['size']}  err={st['err']!r}")
real_fps = st["decoded"] / elapsed
print(f"  实际产出: {st['decoded']} 帧 / {elapsed:.1f}s = {real_fps:.1f} fps")

check("解出了帧", st["decoded"] >= 10, True)
check("有最新帧", len(stream.latest()) > 0, True)
check("帧是 JPEG", stream.latest()[:2], b"\xff\xd8")
check("模式是 stream", st["mode"], "stream")
check("无错误", st["err"], "")

img = Image.open(io.BytesIO(stream.latest()))
print(f"  帧尺寸: {img.size}")
check("宽度 420", img.size[0], 420)
check("纵横比保持", abs(img.size[1] / img.size[0] - 1066 / 480) < 0.06, True)

check("不超过 22fps（限帧生效）", real_fps <= 22, True)
# 假流的供帧节奏不稳（按块 flush），这个断言只用来说明链路活着；
# 真机 screenrecord 是稳定 30fps 源，实际帧率由 max_fps 决定。
check("至少 5fps（链路活着）", real_fps >= 5, True)

before = st["decoded"]
stream.stop()
time.sleep(0.6)
after = stream.stats()["decoded"]
print(f"  停止后 decoded: {after}（停止前 {before}）")
# 停止的瞬间可能正好在解一帧，允许 1-2 帧收尾
check("停止后基本不再产帧", after - before <= 2, True)

FAKE.unlink(missing_ok=True)

print()
if FAILS:
    print(f"失败 {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("全部通过")