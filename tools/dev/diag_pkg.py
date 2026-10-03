"""验证 current_package 解析是否正确。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import Device  # noqa: E402

dev = Device()
dev.ensure_connected()

raw = dev.shell("dumpsys activity activities | grep -m1 topResumedActivity")
print("raw:", repr(raw))
print("current_package():", repr(dev.current_package()))

# 看完整一行
raw2 = dev.shell("dumpsys activity activities")
for line in raw2.splitlines():
    if "topResumedActivity" in line or "mResumedActivity" in line:
        print("LINE:", line.strip())
