"""真机画面性能测试：帧率 + 对 bot dump 的影响。

这是 B 方案最关键的验证：
  1. stream 能不能跑到 20fps
  2. 开流会不会拖慢 uiautomator dump（两者都走 adb）

跑法：python -X utf8 tools/bench_screen.py
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"E:\code\单词pk")
BASE = "http://127.0.0.1:8791"
PY = sys.executable
ADB = r"C:\Users\A\AppData\Local\Android\Sdk\platform-tools\adb.exe"


def meta():
    with urllib.request.urlopen(BASE + "/api/screen.meta", timeout=6) as r:
        return json.loads(r.read())


def serial(retries: int = 3) -> str:
    """找设备；没有就尝试用记住的无线地址重连。"""
    for attempt in range(retries):
        p = subprocess.run([ADB, "devices", "-l"], capture_output=True)
        for line in p.stdout.decode("utf-8", "replace").splitlines()[1:]:
            if "\tdevice" in line:
                return line.split("\tdevice")[0].strip()
        if attempt < retries - 1:
            st = ROOT / "data" / "wireless.json"
            try:
                import json as _j
                d = _j.loads(st.read_text(encoding="utf-8"))
                addr = f"{d['ip']}:{d.get('port', 5555)}"
                print(f"  重连 {addr} ...")
                subprocess.run([ADB, "connect", addr], capture_output=True, timeout=20)
            except Exception:
                pass
            time.sleep(3)
    return ""


def dump_ms(ser: str, n: int = 5) -> list[float]:
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run([ADB, "-s", ser, "shell", "uiautomator dump /sdcard/_b.xml"],
                       capture_output=True, timeout=30)
        out.append((time.perf_counter() - t0) * 1000)
    return out


def main():
    ser = serial()
    if not ser:
        raise SystemExit("没有设备")
    print(f"设备: {ser}\n")

    m0 = meta()
    if m0.get("err"):
        print(f"画面状态异常: {m0}")
        print("等 10 秒再看...")
        time.sleep(10)
        m0 = meta()
    print(f"当前 meta: {m0}\n")

    # 1) 流帧率：隔 5 秒采样两次 decoded 差值
    print("== 1. 画面流帧率（5 秒采样）==")
    a = meta()
    time.sleep(5.0)
    b = meta()
    d_decoded = b.get("decoded", 0) - a.get("decoded", 0)
    fps = d_decoded / 5.0
    print(f"  decoded: {a.get('decoded')} -> {b.get('decoded')}  (+{d_decoded})")
    print(f"  实测帧率: {fps:.1f} fps")
    print(f"  帧体积: {b.get('size')} 字节, 延迟 {b.get('age')}s")

    # 2) 开流时的 dump 耗时
    print("\n== 2. 开流时 uiautomator dump 耗时 ==")
    with_stream = dump_ms(ser, 5)
    print(f"  单次: {[f'{x:.0f}ms' for x in with_stream]}")
    print(f"  平均: {sum(with_stream)/len(with_stream):.0f}ms  "
          f"最大: {max(with_stream):.0f}ms")

    print("\n== 3. 对照：停流后的 dump 耗时 ==")
    # 停掉 App（流随之停），只跑裸 adb dump
    try:
        pid = int((ROOT / "logs" / "smoke.pid").read_text().strip())
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=10)
        time.sleep(3)
    except Exception:
        pass
    no_stream = dump_ms(ser, 5)
    print(f"  单次: {[f'{x:.0f}ms' for x in no_stream]}")
    print(f"  平均: {sum(no_stream)/len(no_stream):.0f}ms  "
          f"最大: {max(no_stream):.0f}ms")

    # 3) 结论
    print("\n" + "=" * 64)
    avg_on = sum(with_stream) / len(with_stream)
    avg_off = sum(no_stream) / len(no_stream)
    print(f"  帧率        {fps:.1f} fps  (目标 >= 15)")
    print(f"  开流 dump   {avg_on:.0f}ms")
    print(f"  停流 dump   {avg_off:.0f}ms")
    print(f"  dump 影响   {avg_on - avg_off:+.0f}ms  "
          f"({(avg_on/avg_off - 1)*100:+.0f}%)")
    print("=" * 64)

    verdict = []
    if fps >= 15:
        verdict.append(f"帧率达标 {fps:.1f}fps")
    else:
        verdict.append(f"帧率偏低 {fps:.1f}fps")
    if avg_on < 4000:
        verdict.append(f"dump {avg_on:.0f}ms 仍在 6 秒预算内")
    else:
        verdict.append(f"dump {avg_on:.0f}ms 已吃满预算")
    print("  " + " / ".join(verdict))


if __name__ == "__main__":
    main()
