"""带超时保护地逐步调用 Runner 内部逻辑，定位卡死点。"""
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adb_driver import Device  # noqa: E402
from pk_core import parse_screen  # noqa: E402
from pk_bot import load_bank, PK_PACKAGE  # noqa: E402


def step(name, fn, limit=15):
    t0 = time.perf_counter()
    print(f"-> {name} ...", flush=True)
    try:
        r = fn()
        print(f"   OK {time.perf_counter()-t0:.2f}s  {str(r)[:90]}", flush=True)
        return r
    except Exception as e:
        print(f"   ERR {time.perf_counter()-t0:.2f}s {type(e).__name__}: {str(e)[:120]}",
              flush=True)
        return None


dev = Device()
step("ensure_connected", dev.ensure_connected)
step("current_package", dev.current_package)
step("load_bank", lambda: f"{len(load_bank().by_gloss)} keys")

xml = step("dump_ui", dev.dump_ui)
if xml:
    q = step("parse_screen", lambda: parse_screen(xml))
    print(f"   parse -> {q}")
