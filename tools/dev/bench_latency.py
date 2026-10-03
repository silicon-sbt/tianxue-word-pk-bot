"""测一轮「dump -> 解析 -> 定位」的真实耗时。4s 答题时间下这是生死线。"""
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adb_driver import Device  # noqa: E402
from pk_core import parse_screen, decode_dump  # noqa: E402

dev = Device()
dev.ensure_connected()
print(f"device={dev.serial} screen={dev.screen_size()}\n")

ROUNDS = 5
dump_t, parse_t = [], []

for i in range(ROUNDS):
    t0 = time.perf_counter()
    raw = dev.shell("uiautomator dump /sdcard/_bench.xml >/dev/null 2>&1; cat /sdcard/_bench.xml")
    t1 = time.perf_counter()
    q = parse_screen(raw)
    t2 = time.perf_counter()
    dump_t.append(t1 - t0)
    parse_t.append(t2 - t1)
    st = f"prompt={q.prompt!r} opts={len(q.options)}" if q else "无题"
    print(f"round {i}: dump={t1-t0:.3f}s parse={t2-t1:.3f}s  {st}")

print(f"\ndump  平均 {sum(dump_t)/len(dump_t):.3f}s  (min {min(dump_t):.3f})")
print(f"parse 平均 {sum(parse_t)/len(parse_t):.3f}s  (min {min(parse_t):.3f})")
print(f"合计  平均 {(sum(dump_t)+sum(parse_t))/len(dump_t):.3f}s")

# 单独测 input tap 的往返
t0 = time.perf_counter()
dev.shell("input tap 630 1400")
print(f"\ninput tap 往返: {time.perf_counter()-t0:.3f}s")

# 单独测 screencap
t0 = time.perf_counter()
dev.screenshot(r"E:\code\单词pk\captures\bench.png")
print(f"screencap 往返: {time.perf_counter()-t0:.3f}s")
