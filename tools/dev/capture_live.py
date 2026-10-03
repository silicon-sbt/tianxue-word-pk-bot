"""采集实时屏幕（exec-out 直读，避免 PowerShell 破坏编码），存为样本 XML。"""
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adb_driver import ADB, Device  # noqa: E402

OUT = pathlib.Path(r"E:\code\单词pk\samples")
OUT.mkdir(exist_ok=True)

dev = Device()
dev.ensure_connected()

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
gap = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

for i in range(n):
    t0 = time.perf_counter()
    dev.shell("uiautomator dump /sdcard/_cap.xml >/dev/null 2>&1")
    p = subprocess.run([ADB, "exec-out", "cat /sdcard/_cap.xml"],
                       capture_output=True, timeout=20)
    raw = p.stdout
    dt = time.perf_counter() - t0
    f = OUT / f"cap_{int(time.time())}_{i}.xml"
    f.write_bytes(raw)
    print(f"saved {f.name}  {len(raw)} bytes  {dt:.2f}s")
    if i < n - 1:
        time.sleep(gap)
