"""adb devices 输出解析 —— 唯一实现。

实测坑：输出里序列号与状态的间隔**不是制表符，是空格填充**：
  192.168.0.104:35957    device product:PD2403 ...
而 mDNS 无线序列号本身**含空格**：
  adb-10AE7X036B0018B-kFzd2o (2)._adb-tls-connect._tcp device product:...
所以既不能 split()（会把序列号切碎），也不能按 \\t 切（根本没有制表符）。
正确做法：按最后一个 " device" 之前切，或正则精准匹配「序列号 + 状态」。

这里用正则：序列号（可含空格、冒号、括号）后面跟 状态。
"""
from __future__ import annotations

import re
import subprocess

# 状态是固定枚举，用它做右边界最可靠
_STATES = r"(?:device|offline|unauthorized|recovery|sideload|bootloader|rescue)"

# 序列号允许：字母数字、点、下划线、连字符、冒号（IP:port）、空格、括号
_ROW = re.compile(
    r"^(?P<serial>.+?)\s+(?P<state>" + _STATES + r")\b"
)


def parse_devices(text: str) -> list[dict]:
    """解析 `adb devices -l` 的输出。"""
    rows = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("List of devices"):
            continue
        if line.startswith("*"):
            continue
        m = _ROW.match(line)
        if not m:
            continue
        serial = m.group("serial").strip()
        state = m.group("state")
        if not serial:
            continue
        rows.append({
            "serial": serial,
            "state": state,
            "wireless": ":" in serial or "_adb-tls" in serial,
        })
    return rows


def list_devices(adb: str, timeout: float = 15.0) -> list[dict]:
    p = subprocess.run([adb, "devices", "-l"], capture_output=True, timeout=timeout)
    return parse_devices(p.stdout.decode("utf-8", "replace"))


def pick_serial(adb: str) -> str:
    """选一个可用设备。优先 USB（更快更稳），没有就用无线。"""
    rows = [d for d in list_devices(adb) if d["state"] == "device"]
    if not rows:
        return ""
    wired = [d for d in rows if not d["wireless"] and ":" not in d["serial"]]
    return (wired or rows)[0]["serial"]


if __name__ == "__main__":
    import sys
    ADB = r"C:\Users\A\AppData\Local\Android\Sdk\platform-tools\adb.exe"
    rows = list_devices(ADB)
    print(f"设备 {len(rows)} 个:")
    for d in rows:
        print(f"  {d['serial']!r}  state={d['state']}  wireless={d['wireless']}")
    print(f"选中: {pick_serial(ADB)!r}")

    # 自检：两种真实格式都要能解析
    cases = [
        ("192.168.0.104:35957    device product:PD2403 model:V2403A",
         "192.168.0.104:35957", "device"),
        ("adb-10AE7X036B0018B-kFzd2o (2)._adb-tls-connect._tcp device product:PD2403",
         "adb-10AE7X036B0018B-kFzd2o (2)._adb-tls-connect._tcp", "device"),
        ("R5CT12345\tdevice", "R5CT12345", "device"),
        ("ABC123\tunauthorized", "ABC123", "unauthorized"),
    ]
    ok = True
    for line, want_serial, want_state in cases:
        got = parse_devices("List of devices attached\n" + line)
        good = got and got[0]["serial"] == want_serial and got[0]["state"] == want_state
        print(f"  [{'OK ' if good else 'FAIL'}] {line[:50]!r}")
        if not good:
            ok = False
            print(f"        得到 {got}")
    sys.exit(0 if ok else 1)
