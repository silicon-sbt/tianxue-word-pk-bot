"""ADB 设备驱动：截图 / dump UI / 点击。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from pk_core import decode_dump


def _find_adb() -> str:
    """自动定位 adb。按优先级：环境变量 → PATH → 常见安装位置。

    不写死用户目录，换机器也能跑。
    """
    env = os.environ.get("ADB") or os.environ.get("ANDROID_ADB")
    if env and os.path.isfile(env):
        return env

    found = shutil.which("adb")
    if found:
        return found

    home = os.path.expanduser("~")
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Android", "Sdk", "platform-tools", "adb.exe"),
        os.path.join(home, "AppData", "Local", "Android", "Sdk",
                     "platform-tools", "adb.exe"),
        r"C:\platform-tools\adb.exe",
        r"D:\platform-tools\adb.exe",
        r"E:\platform-tools\adb.exe",
        "/usr/local/bin/adb",
        "/usr/bin/adb",
        os.path.join(home, "Library", "Android", "sdk", "platform-tools", "adb"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c

    # 兜底：仍然返回 adb，让 subprocess 报出清晰的错误
    return "adb"


ADB = _find_adb()


def _run(args: list[str], timeout: float = 20.0, binary: bool = False):
    p = subprocess.run(
        [ADB] + args,
        capture_output=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()
        if not binary:
            raise RuntimeError(f"adb {' '.join(args)} failed: {err}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def _screen_signature(xml: str) -> str:
    """屏幕内容的轻量指纹：所有文本节点拼接。用于判断两次 dump 是否同一画面。"""
    texts = re.findall(r'text="([^"]*)"', xml)
    return "|".join(t for t in texts if t.strip())


def _looks_transitional(xml: str) -> bool:
    """零成本判断是否读到了「切题瞬间」的混合画面。

    依据（实测）：正常一题 6 个选项；切题瞬间会读到 7 个，且**末两项完全相同**。

    注意：不能对全部 text 节点做「有重复就算异常」——无障碍树里本来就有大量
    空 text 和重复文本（如 'Score: 0' 之类）。只认「非空文本末尾两项相同」。
    """
    texts = [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]
    if len(texts) < 2:
        return True
    # 末两项完全相同 -> 典型的混合画面（新题选项追加在旧题选项之后）
    if texts[-1] == texts[-2]:
        return True
    return False


class Device:
    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial

    def _args(self, *a: str) -> list[str]:
        return (["-s", self.serial] if self.serial else []) + list(a)

    def shell(self, cmd: str, timeout: float = 20.0) -> str:
        return _run(self._args("shell", cmd), timeout=timeout)

    def ensure_connected(self) -> str:
        out = _run(["devices"])
        devs = [l.split()[0] for l in out.splitlines()[1:] if "\tdevice" in l]
        if not devs:
            raise RuntimeError("没有 adb 设备连接")
        if self.serial is None:
            self.serial = devs[0]
        return self.serial

    def dump_ui(self, retries: int = 3) -> str:
        """dump 当前界面 XML，返回已解码的 str。

        关键坑：
          1) 必须用 exec-out 读原始字节再自己解码。走 `adb shell cat` + PowerShell
             重定向会把 UTF-16 输出二次破坏，所有 text="..." 提取失败。
          2) `uiautomator dump` 会偶发失败（实测 6 次里 4 次），且失败时 adb 返回
             非零退出码、stdout 为空。必须显式容忍非零码，否则整个循环被异常打断。
        """
        last = ""
        for attempt in range(retries):
            # 不用 self.shell（它遇到非零码会抛），这里要容忍失败后重试
            p = subprocess.run(
                [ADB] + self._args("shell", "uiautomator dump /sdcard/_pk_ui.xml"),
                capture_output=True, timeout=30,
            )
            out = p.stdout.decode("utf-8", "replace")
            if "dumped to" in out or "UI hierchary" in out:
                data = _run(self._args("exec-out", "cat /sdcard/_pk_ui.xml"),
                            timeout=20.0, binary=True)
                if data:
                    return decode_dump(data)
            last = (out + p.stderr.decode("utf-8", "replace")).strip()
            time.sleep(0.25 + attempt * 0.35)
        raise RuntimeError(f"uiautomator dump 失败: {last[:200]}")

    def current_package(self) -> str:
        """当前前台应用包名。用于确认我们还在答题页而不是别的 App。"""
        out = self.shell("dumpsys activity activities | grep -m1 topResumedActivity")
        m = re.search(r"u0 ([a-zA-Z0-9_.]+)/", out)
        return m.group(1) if m else ""

    def dump_ui_stable(self, retries: int = 3) -> str:
        """避免读到「切题瞬间」的混合画面。

        教训：最初实现是「连 dump 两次直到一致」，但单次 dump 就要 2.5-5s，
        两次直接飙到 11-13s，把 6 秒限时彻底打爆（实测 run3）。
        改成**零成本**的结构判据：正常一题是 6 个选项，若解析出的选项数
        明显异常（如 7 个、末项重复），才重 dump 一次。
        """
        xml = self.dump_ui()
        for _ in range(retries - 1):
            if not _looks_transitional(xml):
                return xml
            time.sleep(0.1)
            xml = self.dump_ui()
        return xml





    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def screenshot(self, path: str) -> None:
        data = _run(self._args("exec-out", "screencap", "-p"), binary=True)
        with open(path, "wb") as f:
            f.write(data)

    def screen_size(self) -> tuple[int, int]:
        out = self.shell("wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)

    def foreground(self) -> str:
        out = self.shell("dumpsys activity activities | grep -m1 topResumedActivity")
        m = re.search(r"(com\.[\w.]+)/", out)
        return m.group(1) if m else ""
