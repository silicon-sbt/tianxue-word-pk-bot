"""验证「点击错位/时序」假设。

日志显示 shock -> 'vi. & vt. 游泳'，但算法给 'n.震惊' 1.00 分。
说明：判定对，是**坐标对不上真实选项位置**，或**读到的题与点击时不同题**。

PK 选项是**漂浮移动**的（有动画），dump 拿到的坐标是「某一瞬间」的，
等 3.3s 后点击时，选项可能已经飘到别处 => 点错。

这是 4/6 秒限时下最隐蔽的坑。这里验证选项是否真的在动。
"""
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adb_driver import Device  # noqa: E402
from pk_core import parse_screen  # noqa: E402

dev = Device()
dev.ensure_connected()

print("连续 dump，观察同一题的选项坐标是否漂移：\n")
prev = None
for i in range(5):
    try:
        xml = dev.dump_ui()
    except Exception as e:
        print(f"#{i} dump err {e}")
        continue
    q = parse_screen(xml)
    if q is None:
        print(f"#{i} 非答题页")
        time.sleep(1)
        continue
    sig = {o.text: (o.cx, o.cy) for o in q.options}
    print(f"#{i} [{q.direction}] {q.prompt!r} 进度={q.progress}")
    for t, (x, y) in sig.items():
        drift = ""
        if prev and t in prev:
            dx, dy = x - prev[t][0], y - prev[t][1]
            if abs(dx) > 2 or abs(dy) > 2:
                drift = f"  漂移 dx={dx} dy={dy}"
        print(f"     {t:22} ({x:4},{y:4}){drift}")
    prev = sig
    print()
    time.sleep(0.5)
