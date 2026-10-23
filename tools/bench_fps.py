"""纯流帧率测试：不起 App，直接跑 ScreenStream。"""
import sys
import time
from pathlib import Path

ROOT = Path(r"E:\code\单词pk")
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "src"))

import subprocess

from adb_driver import ADB
from screen_stream import ScreenStream


def serial():
    from adb_parse import pick_serial
    return pick_serial(ADB)


def main():
    ser = serial()
    if not ser:
        raise SystemExit("没有设备")
    print(f"设备: {ser}")
    print(f"录制尺寸: wm size -> ", end="")

    s = ScreenStream(ADB, lambda: ser)
    print(s._capture_size(ser))
    print()

    s.start()
    print("等首帧...")
    seq, data = s.wait_frame(0, timeout=20)
    if not data:
        print("  20 秒内没有首帧，失败")
        s.stop()
        raise SystemExit(1)
    print(f"  首帧到手: {len(data)} 字节\n")

    # 分 3 段各 5 秒采样
    fps_list = []
    for rnd in range(3):
        a = s.stats()["decoded"]
        time.sleep(5.0)
        b = s.stats()["decoded"]
        fps = (b - a) / 5.0
        fps_list.append(fps)
        st = s.stats()
        print(f"  第 {rnd+1} 段: +{b-a} 帧 => {fps:.1f} fps   "
              f"体积 {st['size']}B  延迟 {st['age']}s  err={st['err']!r}")

    s.stop()
    avg = sum(fps_list) / len(fps_list)
    print()
    print("=" * 56)
    print(f"  平均帧率: {avg:.1f} fps  (上限 {ScreenStream.MAX_FPS})")
    print(f"  达标(>=15): {'是' if avg >= 15 else '否'}")
    print("=" * 56)


if __name__ == "__main__":
    main()
