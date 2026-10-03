"""方案对比：uiautomator dump vs screencap 在 4s 限制下的可行性。

结论导向：
  dump    ~2.53s  -> 4s 内最多 1 次，几乎没有余量
  screencap ~0.57s -> 4s 内可轮询 3-5 次

所以走 screencap + 图像识别（模板/差分），或「先截图预判」。
这里先精确测 screencap 的端到端耗时分布，并验证 exec-out 直读。
"""
import pathlib
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adb_driver import ADB, Device  # noqa: E402

dev = Device()
dev.ensure_connected()
OUT = pathlib.Path(r"E:\code\单词pk\captures")
OUT.mkdir(exist_ok=True)

# 1) screencap 走 exec-out 直读字节（不落 sdcard，省一次往返）
times = []
for i in range(5):
    t0 = time.perf_counter()
    p = subprocess.run([ADB, "exec-out", "screencap", "-p"],
                       capture_output=True, timeout=20)
    dt = time.perf_counter() - t0
    times.append(dt)
    if i == 0:
        (OUT / "poll0.png").write_bytes(p.stdout)
print(f"exec-out screencap: n={len(times)} mean={statistics.mean(times):.3f}s "
      f"min={min(times):.3f}s max={max(times):.3f}s")
print(f"  bytes={len(p.stdout)}")

# 2) screencap -> sdcard -> pull 两段式
times2 = []
for i in range(3):
    t0 = time.perf_counter()
    dev.shell("screencap -p /sdcard/_b.png")
    subprocess.run([ADB, "pull", "/sdcard/_b.png", str(OUT / "poll1.png")],
                   capture_output=True, timeout=20)
    times2.append(time.perf_counter() - t0)
print(f"screencap+pull     : mean={statistics.mean(times2):.3f}s min={min(times2):.3f}s")

# 3) 最小 dump：只 dump 一次并测 exec-out cat
times3 = []
for i in range(3):
    t0 = time.perf_counter()
    dev.shell("uiautomator dump /sdcard/_pk_ui.xml >/dev/null 2>&1")
    subprocess.run([ADB, "exec-out", "cat /sdcard/_pk_ui.xml"],
                   capture_output=True, timeout=20)
    times3.append(time.perf_counter() - t0)
print(f"dump+exec-out cat  : mean={statistics.mean(times3):.3f}s min={min(times3):.3f}s")

print("\n-- 结论 --")
print(f"screencap 比 dump 快 {statistics.mean(times3)/statistics.mean(times):.1f}x")
