"""定位主循环卡点：每次 dump + parse 都打印，看走到哪一步。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import Device  # noqa: E402
from pk_core import parse_screen  # noqa: E402

dev = Device()
dev.ensure_connected()
print("device ok", flush=True)

for i in range(6):
    t0 = time.perf_counter()
    try:
        xml = dev.dump_ui()
        t1 = time.perf_counter()
        q = parse_screen(xml)
        t2 = time.perf_counter()
        if q:
            print(f"#{i} dump={t1-t0:.2f}s parse={t2-t1:.3f}s "
                  f"[{q.direction}] prompt={q.prompt!r} opts={len(q.options)} "
                  f"prog={q.progress} t={q.seconds_left}", flush=True)
        else:
            print(f"#{i} dump={t1-t0:.2f}s parse={t2-t1:.3f}s -> 非答题页 "
                  f"(len={len(xml)})", flush=True)
    except Exception as e:
        print(f"#{i} ERR {time.perf_counter()-t0:.2f}s {type(e).__name__}: {e}",
              flush=True)
    time.sleep(0.2)
print("done", flush=True)
