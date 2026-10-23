"""给桌面 App 截图：运行页 + 设置页。"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(r"E:\code\单词pk")
PIDF = ROOT / "logs" / "app.pid"
OUT = ROOT / "captures"

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("L", ctypes.c_long), ("T", ctypes.c_long),
                ("R", ctypes.c_long), ("B", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("X", ctypes.c_long), ("Y", ctypes.c_long)]


def client(hwnd):
    r = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    p = POINT()
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.X, p.Y, r.R - r.L, r.B - r.T


def shot(hwnd, name):
    x, y, w, h = client(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path = OUT / name
    img.save(path)
    print(f"  {name}  {w}x{h}")
    return path


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.9)


def main():
    pid = int(PIDF.read_text().strip())
    hwnd = 0
    for _ in range(20):
        hwnd = user32.GetForegroundWindow()
        # 找属于该 pid 的窗口
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum(h, _):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(h):
                found.append(h)
            return True

        user32.EnumWindows(enum, 0)
        if found:
            hwnd = found[0]
            break
        time.sleep(0.5)
    if not hwnd:
        print("找不到窗口")
        sys.exit(1)

    shot(hwnd, "v_run.png")
    x, y, w, h = client(hwnd)
    # 左侧导航第二个按钮（设置）
    click(x + 30, y + 130)
    shot(hwnd, "v_settings.png")


if __name__ == "__main__":
    main()
