"""用 pywebview 自身截图设置页：点导航 -> 截图。

不再用外部坐标点击（窗口位置/DPI 容易算错），
改用 pywebview 的 evaluate_js 直接触发点击，再截窗口。
"""
import ctypes
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(r"E:\code\单词pk")
user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
 _fields_ = [("L", ctypes.c_long), ("T", ctypes.c_long),
 ("R", ctypes.c_long), ("B", ctypes.c_long)]


class POINT(ctypes.Structure):
 _fields_ = [("X", ctypes.c_long), ("Y", ctypes.c_long)]


def find_window(pid: int):
 found = []

 @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
 def enum(h, _):
 p = wintypes.DWORD()
 user32.GetWindowThreadProcessId(h, ctypes.byref(p))
 if p.value == pid and user32.IsWindowVisible(h):
 found.append(h)
 return True

 user32.EnumWindows(enum, 0)
 return found[0] if found else 0


def grab(hwnd, name):
 r = RECT()
 user32.GetClientRect(hwnd, ctypes.byref(r))
 p = POINT()
 user32.ClientToScreen(hwnd, ctypes.byref(p))
 w, h = r.R - r.L, r.B - r.T
 user32.SetForegroundWindow(hwnd)
 time.sleep(0.7)
 ImageGrab.grab(bbox=(p.X, p.Y, p.X + w, p.Y + h)).save(ROOT / "captures" / name)
 print(f" {name} {w}x{h}")


if __name__ == "__main__":
 pid = int((ROOT / "logs" / "app.pid").read_text().strip())
 hwnd = find_window(pid)
 if not hwnd:
 raise SystemExit("找不到窗口")
 print(f"窗口句柄: {hwnd}")
 grab(hwnd, "final_run.png")
