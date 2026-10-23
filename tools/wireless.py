"""无线 ADB：配对、连接、记住地址自动重连。

Android 11+ 的无线调试分两步：先 pair（配对码 + 配对端口），
再 connect（连接端口通常 5555，与配对端口不同）。
配对成功后留下授权记录，之后只需 connect；手机重启可能要重新配对。

用法：
  python -X utf8 tools/wireless.py status
  python -X utf8 tools/wireless.py pair <IP:端口> <配对码>
  python -X utf8 tools/wireless.py connect [IP[:端口]]
  python -X utf8 tools/wireless.py auto
  python -X utf8 tools/wireless.py forget
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from adb_driver import ADB  # noqa: E402

STATE = ROOT / "data" / "wireless.json"
DEFAULT_PORT = 5555


def run(args, timeout=20.0):
    p = subprocess.run([ADB] + args, capture_output=True, timeout=timeout)
    out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    return p.returncode, out


def devices():
    """列设备。无线序列号可能含空格，所以按 " device" 切，不能 split()。"""
    rc, out = run(["devices", "-l"])
    rows = []
    for line in out.splitlines()[1:]:
        line = line.rstrip()
        if not line.strip():
            continue
        if "\t" in line:
            serial, rest = line.split("\t", 1)
        else:
            idx = line.find(" device")
            if idx < 0:
                continue
            serial, rest = line[:idx], line[idx + 1:]
        serial = serial.strip()
        if not serial:
            continue
        state = rest.strip().split()[0] if rest.strip() else "?"
        rows.append({
            "serial": serial,
            "state": state,
            "wireless": ":" in serial or "_adb-tls" in serial,
        })
    return rows


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def status():
    rows = devices()
    wired = [d for d in rows if not d["wireless"] and d["state"] == "device"]
    wifi = [d for d in rows if d["wireless"] and d["state"] == "device"]
    return {"all": rows, "wired": len(wired), "wireless": len(wifi),
            "ready": bool(wired or wifi), "saved": load_state()}


def pair(addr, code):
    if ":" not in addr:
        return False, "配对地址要带端口，例如 192.168.0.101:37123"
    rc, out = run(["pair", addr, code.strip()], timeout=30)
    ok = "Successfully paired" in out or rc == 0
    if ok:
        st = load_state()
        st["pair_addr"] = addr
        st["ip"] = addr.split(":")[0]
        save_state(st)
    return ok, out


def connect(addr=None, port=DEFAULT_PORT):
    st = load_state()
    if not addr:
        ip = st.get("ip")
        port = int(st.get("port", port))
        if not ip:
            return False, "还没记住地址，先 connect <IP> 或先 pair"
        addr = f"{ip}:{port}"
    elif ":" not in addr:
        addr = f"{addr}:{port}"

    rc, out = run(["connect", addr], timeout=25)
    ok = "connected to" in out.lower()
    if ok:
        st["ip"] = addr.split(":")[0]
        st["port"] = addr.split(":")[1]
        save_state(st)
        for _ in range(6):
            time.sleep(0.5)
            if any(d["wireless"] and d["state"] == "device" for d in devices()):
                break
    return ok, out


def mdns_services():
    """扫 mDNS 把服务分类。配对端口与连接端口不同，混用会 pair 失败。"""
    rc, out = run(["mdns", "services"], timeout=10)
    res = {"pairing": [], "connect": [], "other": []}
    for line in out.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
        if not m:
            continue
        addr = f"{m.group(1)}:{m.group(2)}"
        low = line.lower()
        if "pairing" in low:
            res["pairing"].append(addr)
        elif "connect" in low:
            res["connect"].append(addr)
        else:
            res["other"].append(addr)
    return {k: sorted(set(v)) for k, v in res.items()}


def auto():
    st = load_state()
    if st.get("ip"):
        ok, out = connect()
        if ok:
            return True, f"已重连 {st['ip']}:{st.get('port', DEFAULT_PORT)}"

    svc = mdns_services()
    pairing = svc["pairing"] or svc["connect"] or svc["other"]
    if pairing:
        p = pairing[0]
        return False, (
            f"发现手机 {p}。\n"
            f"  下一步：手机上「开发者选项 - 无线调试 - 使用配对码配对设备」，"
            f"填入显示的配对码：\n"
            f"    python -X utf8 tools/wireless.py pair {p} <配对码>\n"
            f"  配好后再 connect <IP>"
        )
    return False, "没连上，也没发现设备。确认手机和电脑在同一 Wi-Fi，无线调试已打开。"


def forget():
    if STATE.exists():
        STATE.unlink()
    return True, "已忘掉记住的无线地址"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "status":
        s = status()
        print(f"有线设备 {s['wired']} 个，无线设备 {s['wireless']} 个")
        for d in s["all"]:
            print(f"  {d['serial']:40} {d['state']}")
        if s["saved"]:
            print(f"记住的地址: {s['saved']}")
    elif cmd == "pair":
        if len(sys.argv) < 4:
            print("用法: pair <IP:端口> <配对码>")
            sys.exit(2)
        ok, out = pair(sys.argv[2], sys.argv[3])
        print(("[OK] " if ok else "[FAIL] ") + out)
        sys.exit(0 if ok else 1)
    elif cmd == "connect":
        ok, out = connect(sys.argv[2] if len(sys.argv) > 2 else None)
        print(("[OK] " if ok else "[FAIL] ") + out)
        sys.exit(0 if ok else 1)
    elif cmd == "auto":
        ok, out = auto()
        print(("[OK] " if ok else "[FAIL] ") + out)
        sys.exit(0 if ok else 1)
    elif cmd == "forget":
        ok, out = forget()
        print(out)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()