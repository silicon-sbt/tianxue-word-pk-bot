"""最小复现：逐步测 dump_ui 的每一段耗时，定位卡点。"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import ADB, Device  # noqa: E402

print(f"ADB = {ADB}")
print(f"exists = {Path(ADB).exists()}\n")

dev = Device()
t0 = time.perf_counter()
serial = dev.ensure_connected()
print(f"ensure_connected: {serial}  ({time.perf_counter()-t0:.2f}s)\n")

# 分步计时
print("--- step 1: uiautomator dump 命令本身 ---")
t0 = time.perf_counter()
try:
    out = dev.shell("uiautomator dump /sdcard/_t.xml 2>&1", timeout=30)
    print(f"  {time.perf_counter()-t0:.2f}s  out={out.strip()[:120]!r}")
except Exception as e:
    print(f"  ERR after {time.perf_counter()-t0:.2f}s: {type(e).__name__}: {e}")

print("\n--- step 2: exec-out cat 读回 ---")
t0 = time.perf_counter()
try:
    p = subprocess.run([ADB, "exec-out", "cat /sdcard/_t.xml"],
                       capture_output=True, timeout=30)
    dt = time.perf_counter() - t0
    print(f"  {dt:.2f}s  rc={p.returncode}  bytes={len(p.stdout)}")
    print(f"  head={p.stdout[:80]!r}")
    if p.stderr:
        print(f"  stderr={p.stderr[:200]!r}")
except Exception as e:
    print(f"  ERR after {time.perf_counter()-t0:.2f}s: {type(e).__name__}: {e}")

print("\n--- step 3: 完整 dump_ui ---")
t0 = time.perf_counter()
try:
    xml = dev.dump_ui()
    print(f"  OK {time.perf_counter()-t0:.2f}s  len={len(xml)}")
except Exception as e:
    print(f"  ERR after {time.perf_counter()-t0:.2f}s: {type(e).__name__}: {e}")

print("\n--- step 4: 连测 3 次 dump_ui ---")
for i in range(3):
    t0 = time.perf_counter()
    try:
        xml = dev.dump_ui()
        print(f"  #{i}: OK {time.perf_counter()-t0:.2f}s len={len(xml)}")
    except Exception as e:
        print(f"  #{i}: ERR {time.perf_counter()-t0:.2f}s {type(e).__name__}: {e}")
