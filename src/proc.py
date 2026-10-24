"""子进程工具：统一屏蔽控制台窗口。

为什么单独一个模块：
  exe 用 --noconsole 让主程序无黑框还不够 —— 每次 spawn 子进程
  （adb、taskkill、tasklist 等）Windows 都会给它分配一个新控制台窗口，
  答题时每秒调 adb 好几次，屏幕上就是一串黑框乱闪。

  CREATE_NO_WINDOW (0x08000000) 让子进程不创建控制台。
  这个标志只在 Windows 有效，所以统一在这里判断平台。
"""
from __future__ import annotations

import os
import subprocess

# Windows 的 CREATE_NO_WINDOW
CREATE_NO_WINDOW = 0x08000000

# 非 Windows 平台传 0
NO_WINDOW = CREATE_NO_WINDOW if os.name == "nt" else 0


def run(args, **kw) -> subprocess.CompletedProcess:
    """等价 subprocess.run，但不弹控制台窗口。"""
    kw.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(args, **kw)


def popen(args, **kw) -> subprocess.Popen:
    """等价 subprocess.Popen，但不弹控制台窗口。

    注意：如果调用方自己传了 creationflags（比如 DETACHED_PROCESS），
    就在那个基础上按位或上 CREATE_NO_WINDOW。
    """
    flags = kw.pop("creationflags", 0)
    kw["creationflags"] = flags | NO_WINDOW
    return subprocess.Popen(args, **kw)
