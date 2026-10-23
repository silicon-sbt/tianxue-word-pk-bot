"""冒烟测试：真启动桌面 App，验证进程/接口/窗口/长时间运行稳定性。

不做单元断言，只看「它能不能活」。手机没连时也要能干净运行。

跑法：python -X utf8 tools/smoke.py
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"E:\code\单词pk")
PY = sys.executable
BASE = "http://127.0.0.1:8791"
PID_FILE = ROOT / "logs" / "smoke.pid"

FAILS = []


def ok(name, cond, detail=""):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def get(path, timeout=8):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read()


def post(path, body=None, timeout=10):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def kill_existing():
    """杀掉所有 app/main.py 实例与占用 8791 的进程。

    只按 PID_FILE kill 不够：之前跑残留的实例会占着端口，
    新实例起不来但接口仍然响应，测试连到的是旧代码 —— 典型的假绿。
    """
    import subprocess as sp
    # 1) 按命令行匹配所有 app/main.py
    try:
        ps = sp.run(["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process | "
                     "Where-Object { \.CommandLine -like '*app*main.py*' } | "
                     "ForEach-Object { \.ProcessId }"],
                    capture_output=True, timeout=20)
        for line in ps.stdout.decode("utf-8", "replace").split():
            if line.strip().isdigit():
                sp.run(["taskkill", "/PID", line.strip(), "/T", "/F"],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    # 2) 按端口兜底
    try:
        ps = sp.run(["powershell", "-NoProfile", "-Command",
                     "(Get-NetTCPConnection -LocalPort 8791 -State Listen "
                     "-ErrorAction SilentlyContinue).OwningProcess"],
                    capture_output=True, timeout=20)
        for line in ps.stdout.decode("utf-8", "replace").split():
            if line.strip().isdigit():
                sp.run(["taskkill", "/PID", line.strip(), "/T", "/F"],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(2)
    # 3) 确认端口真的空出来
    for _ in range(20):
        try:
            urllib.request.urlopen(BASE + "/api/status", timeout=1)
            time.sleep(0.5)
        except Exception:
            return
    raise SystemExit("端口 8791 仍被占用，无法开始冒烟测试")


def main():
    print("== 1. 启动 App ==")
    kill_existing()
    proc = subprocess.Popen(
        [PY, "-X", "utf8", str(ROOT / "app" / "main.py")],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    PID_FILE.write_text(str(proc.pid))
    print(f"  PID {proc.pid}")

    # 等端口起来
    ready = False
    for _ in range(40):
        time.sleep(0.5)
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", "replace")
            print("  进程提前退出！stderr:")
            print("   ", err[-800:])
            ok("进程存活", False)
            return
        try:
            get("/api/status", timeout=2)
            ready = True
            break
        except Exception:
            continue
    ok("服务在 20 秒内就绪", ready)

    if not ready:
        proc.terminate()
        return

    print("\n== 2. HTTP 接口 ==")
    checks = [
        ("/api/status", lambda b: all(k in json.loads(b) for k in ("stats", "device", "tail"))),
        ("/api/conn", lambda b: "status" in json.loads(b) and "onboarded" in json.loads(b)),
        ("/api/config", lambda b: "text" in json.loads(b) and "summary" in json.loads(b)),
        ("/api/screen.meta", lambda b: "mode" in json.loads(b)),
    ]
    for path, verify in checks:
        try:
            code, body = get(path)
            ok(f"{path} 200 且结构正确", code == 200 and verify(body))
        except Exception as e:
            ok(f"{path}", False, str(e)[:60])

    # 首页
    try:
        code, body = get("/")
        html = body.decode("utf-8")
        ok("首页 200", code == 200)
        ok("首页含关键元素",
           all(k in html for k in ('id="screenImg"', 'id="btnConnect"',
                                   'id="viewSettings"', 'id="log"')),
           f"{len(html)} 字节")
    except Exception as e:
        ok("首页", False, str(e)[:60])

    print("\n== 3. 画面端点（按实际设备状态分支）==")
    # 有无设备决定期望值：无设备必须 404/503，有设备必须给真帧
    has_dev = json.loads(get("/api/conn")[1])["status"]["connected"]
    print(f"  当前设备: {'已连接' if has_dev else '未连接'}")

    if has_dev:
        # 有设备：等一会儿让流产出首帧
        deadline = time.time() + 20
        frame_ok = False
        while time.time() < deadline:
            meta = json.loads(get("/api/screen.meta")[1])
            if meta.get("size", 0) > 0 and not meta.get("err"):
                frame_ok = True
                break
            time.sleep(1)
        ok("有设备时能产出画面帧", frame_ok)
        if frame_ok:
            meta = json.loads(get("/api/screen.meta")[1])
            print(f"    meta: size={meta['size']} decoded={meta.get('decoded')} "
                  f"age={meta.get('age')}")
            code, body = get("/api/screen.jpg")
            ok("screen.jpg 有帧时返回 JPEG", code == 200 and body[:2] == b"\xff\xd8",
               f"{code}, {len(body)} 字节")
    else:
        try:
            code, body = get("/api/screen.jpg")
            ok("screen.jpg 无帧时 404（不是 200 空图）", code == 404, f"实际 {code}")
        except urllib.error.HTTPError as e:
            ok("screen.jpg 无帧时 404（不是 200 空图）", e.code == 404, f"实际 {e.code}")
        except Exception as e:
            ok("screen.jpg", False, str(e)[:60])

    # MJPEG：有帧就 200+multipart，没帧就 503，不能 200 空帧糊弄
    try:
        r = urllib.request.urlopen(BASE + "/api/screen.mjpeg", timeout=8)
        ctype = r.headers.get("Content-Type", "")
        is_mp = "multipart/x-mixed-replace" in ctype
        if has_dev:
            ok("MJPEG 有设备时返回 multipart", is_mp, ctype)
            r.read(64)
        else:
            ok("MJPEG 无设备时不该回 200", False, f"200 {ctype}")
        r.close()
    except urllib.error.HTTPError as e:
        if has_dev:
            ok("MJPEG 有设备时不该 503", False, f"实际 {e.code}")
        else:
            ok("MJPEG 无设备时返回 503", e.code == 503, f"实际 {e.code}")
    except Exception as e:
        ok("MJPEG 端点", False, str(e)[:80])

    print("\n== 4. 写接口 ==")
    try:
        cfg = json.loads(get("/api/config")[1])["text"]
        code, r = post("/api/config/check", {"text": cfg})
        ok("配置语法检查（好配置）", r.get("ok") is True)
        code, r = post("/api/config/check", {"text": "坏 [ ["})
        ok("配置语法检查（坏配置被拒）", r.get("ok") is False)
    except Exception as e:
        ok("配置检查", False, str(e)[:60])

    try:
        code, r = post("/api/onboarded")
        ok("/api/onboarded 可调用", r.get("ok") is True)
    except Exception as e:
        ok("/api/onboarded", False, str(e)[:60])

    print("\n== 5. 稳定运行 10 秒（无设备，看会不会崩）==")
    alive = True
    for i in range(10):
        time.sleep(1)
        if proc.poll() is not None:
            alive = False
            break
        try:
            get("/api/status", timeout=3)
        except Exception as e:
            alive = False
            print(f"    第 {i+1}s 请求失败: {e}")
            break
    ok("10 秒内进程存活且接口可用", alive)

    # 检查 stderr 有没有异常堆栈
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    err = proc.stderr.read().decode("utf-8", "replace")
    crash_words = ["Traceback", "Exception", "Error:"]
    has_crash = any(w in err for w in crash_words)
    ok("stderr 无异常堆栈", not has_crash, err[:200] if has_crash else "")
    if err.strip() and not has_crash:
        print(f"    stderr（非异常输出）: {err.strip()[:200]}")

    print()
    print("=" * 60)
    if FAILS:
        print(f"冒烟测试失败 {len(FAILS)} 项: {FAILS}")
        sys.exit(1)
    print("冒烟测试全部通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
