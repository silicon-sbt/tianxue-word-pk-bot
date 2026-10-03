"""常驻等待版：先进入等待态，一旦出现答题页立刻开跑。

用法:
  python run_watch.py [--live] [--max 130] [--minutes 10]

与 pk_bot.py 的区别：
  pk_bot 假设「运行时就该在答题页」；
  run_watch 会一直等到答题页出现（你手点开始 PK 后立刻接管）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from adb_driver import Device  # noqa: E402
from pk_bot import PK_PACKAGE, Runner, log, reset_log  # noqa: E402
from pk_core import parse_screen  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="真正点击（缺省只读）")
    ap.add_argument("--max", type=int, default=130)
    ap.add_argument("--minutes", type=float, default=10.0, help="总上限（默认10分钟）")
    ap.add_argument("--wait", type=float, default=180.0,
                    help="最多等待多久出现答题页（默认180s）")
    a = ap.parse_args()

    reset_log()
    dev = Device()
    try:
        dev.ensure_connected()
    except RuntimeError as e:
        # 无窗口启动时用户看不到控制台，必须把原因写进日志（VBS 会读日志显示），
        # 并以非零码退出，否则启动器会误报「成功」。
        log(f"[错误] {e}")
        log("请检查：1) USB 线已连接  2) 手机已开 USB 调试  3) 手机上点了「允许调试」")
        sys.exit(1)
    dry = not a.live
    log(f"=== 等待模式 === 设备 {dev.serial} dry={dry} 等待上限 {a.wait:.0f}s")

    # 阶段一：等答题页出现
    t_start = time.time()
    seen = False
    while time.time() - t_start < a.wait:
        pkg = dev.current_package()
        if pkg and not pkg.startswith(PK_PACKAGE):
            log(f"前台={pkg}（不是天学网），请切到天学网")
            time.sleep(1.5)
            continue
        try:
            xml = dev.dump_ui()
        except Exception as e:
            log(f"dump 失败: {str(e)[:60]}")
            time.sleep(0.5)
            continue
        q = parse_screen(xml)
        if q is not None:
            log(f"检测到答题页: [{q.direction}] {q.prompt!r} 进度={q.progress}")
            seen = True
            break
        left = a.wait - (time.time() - t_start)
        if int(left) % 10 == 0:
            log(f"等待答题页中… 剩余 {left:.0f}s（请在手机上点「开始PK」）")
        time.sleep(0.6)

    if not seen:
        log("等待超时，未出现答题页，退出")
        return

    # 阶段二：接管
    deadline = time.time() + a.minutes * 60
    Runner(dev, dry).run(a.max, deadline=deadline)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("已中断")
