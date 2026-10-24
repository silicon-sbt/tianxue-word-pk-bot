"""天学网单词PK助手 - 桌面应用（pywebview 套壳）

架构：Python 后端（本地 HTTP + SSE） <- pywebview 原生窗口 <- 单页 HTML

画面链路（见 app/screen_stream.py）：
  adb screencap 单帧 600-800ms，做不了连续画面。
  改用 screenrecord 的 H.264 流 -> PyAV 解码 -> JPEG，
  经 MJPEG 长连接推给前端，上限 20fps。

启动：python -X utf8 app/main.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# ---- 路径解析 ----
# 冻结态（PyInstaller）下不能用 __file__ 推目录：
#   可写数据（config/data/logs）放 exe 旁边，只读资源（index.html）在 _MEIPASS。
# launcher.py 会通过环境变量把两者都告诉我们。
_env_root = os.environ.get("PK_APP_ROOT")
_env_bundle = os.environ.get("PK_BUNDLE_ROOT")

if _env_root:
    ROOT = Path(_env_root)
else:
    ROOT = Path(__file__).resolve().parent.parent

if _env_bundle:
    UI = Path(_env_bundle)
else:
    UI = Path(__file__).resolve().parent

SRC = ROOT / "src"
LOG = ROOT / "logs" / "live_out.txt"
CONFIG = ROOT / "config.toml"
WIRELESS_STATE = ROOT / "data" / "wireless.json"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tools"))

import proc  # noqa: E402  子进程工具：统一加 CREATE_NO_WINDOW，不弹控制台

HOST, PORT = "127.0.0.1", 8791

_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()


# ------------------------------------------------------------------ 基础

def _adb() -> str:
    try:
        from adb_driver import ADB
        return ADB
    except Exception:  # noqa: BLE001
        return "adb"


def _run(args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    p = proc.run([_adb()] + args, capture_output=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip()


_devices_cache: dict = {"at": -1e9, "rows": []}
DEVICES_TTL = 2.5   # 秒

def _devices() -> list[dict]:
    """列出设备（带 2.5s 缓存）。

    这个函数被 /api/status（1s）和 SSE（1s）各调一次，每次起一个
    `adb devices -l` 子进程约 70ms —— 每秒白烧 140ms 一个核。
    设备状态 2.5 秒内基本不会变，缓存掉。

    无线调试（mDNS）的序列号含空格，形如
      adb-10AE7X036B0018B-kFzd2o (2)._adb-tls-connect._tcp device product:...
    用 split() 会把 " (2)" 切走。这里按 " device" 切，前面整体是序列号。
    """
    now = time.monotonic()
    if now - _devices_cache["at"] < DEVICES_TTL:
        return _devices_cache["rows"]

    rc, out = _run(["devices", "-l"], timeout=15)
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
    _devices_cache["at"] = now
    _devices_cache["rows"] = rows
    return rows



def _device_status() -> dict:
    try:
        rows = _devices()
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "serial": "", "mode": "", "error": str(e)[:80]}

    ok = [d for d in rows if d["state"] == "device"]
    if ok:
        wired = [d for d in ok if not d["wireless"] and ":" not in d["serial"]]
        pick = (wired or ok)[0]
        return {
            "connected": True,
            "serial": pick["serial"],
            "mode": "wifi" if pick["wireless"] else "usb",
            "error": "",
        }
    if rows:
        return {"connected": False, "serial": "", "mode": "",
                "error": "设备未授权，请在手机上点允许调试"}
    return {"connected": False, "serial": "", "mode": "", "error": ""}


def _load_wireless() -> dict:
    try:
        return json.loads(WIRELESS_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_wireless(d: dict) -> None:
    WIRELESS_STATE.parent.mkdir(parents=True, exist_ok=True)
    WIRELESS_STATE.write_text(
        json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _mdns() -> dict:
    try:
        rc, out = _run(["mdns", "services"], timeout=12)
    except Exception:  # noqa: BLE001
        return {"pairing": [], "connect": [], "other": []}
    import re
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


# ------------------------------------------------------------------ 配置

def read_config() -> str:
    try:
        return CONFIG.read_text(encoding="utf-8")
    except OSError:
        return ""


def check_config(text: str) -> dict:
    import tomllib
    try:
        d = tomllib.loads(text)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"TOML 语法错误：{e}"}
    ai = d.get("ai") if isinstance(d.get("ai"), dict) else {}
    mode = str(ai.get("mode", "chat")).lower()
    if ai.get("enabled") and mode not in ("chat", "jev"):
        return {"ok": False, "msg": f'ai.mode 只能是 "chat" 或 "jev"，当前是 {mode!r}'}
    t = ai.get("timeout", 1.8)
    if ai.get("enabled") and not isinstance(t, (int, float)):
        return {"ok": False, "msg": "ai.timeout 必须是数字"}
    return {"ok": True, "msg": "语法正确"}


def write_config(text: str) -> dict:
    r = check_config(text)
    if not r["ok"]:
        return r
    try:
        CONFIG.write_text(text, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True, "msg": "已保存，正在运行的 bot 会即时生效"}


def config_summary() -> dict:
    import tomllib
    try:
        d = tomllib.loads(read_config())
    except Exception:  # noqa: BLE001
        return {}
    ai = d.get("ai") if isinstance(d.get("ai"), dict) else {}
    sc = d.get("score") if isinstance(d.get("score"), dict) else {}
    bt = d.get("bot") if isinstance(d.get("bot"), dict) else {}
    try:
        from config import load as load_config
        c = load_config()
        key_ok = bool(c.ai.api_key)
        key_len = len(c.ai.api_key)
    except Exception:  # noqa: BLE001
        key_ok, key_len = False, 0
    return {
        "ai_enabled": bool(ai.get("enabled")),
        "ai_mode": ai.get("mode", "chat"),
        "ai_model": ai.get("model", ""),
        "ai_timeout": ai.get("timeout", 1.8),
        "ai_remember": ai.get("remember", True),
        "key_present": key_ok,
        "key_len": key_len,
        "score_enabled": bool(sc.get("enabled")),
        "score_target": sc.get("target_accuracy", 0.7),
        "question_seconds": bt.get("question_seconds", 6.0),
    }


# ------------------------------------------------------------------ 统计

# /api/status 与 SSE 每秒各要一次统计，每次重解析整个日志是白费。
# 日志只在 bot 写的时候变，按 (mtime, size) 缓存结果即可。
_stats_cache: dict = {"key": None, "val": None}


def _stats_from_log() -> dict:
    running = _proc is not None and _proc.poll() is None
    if not LOG.exists():
        return {"hit": 0, "ai": 0, "guess": 0, "fake": 0, "miss": 0,
                "lines": 0, "running": running}

    try:
        st = LOG.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None

    if key is not None and key == _stats_cache["key"]:
        cached = dict(_stats_cache["val"])
        cached["running"] = running
        return cached

    s = {"hit": 0, "ai": 0, "guess": 0, "fake": 0, "miss": 0, "lines": 0}
    try:
        text = LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        s["running"] = running
        return s
    lines = text.splitlines()
    s["lines"] = len(lines)
    for line in lines:
        if "[+]" in line:
            if " AI " in line:
                s["ai"] += 1
            elif " 控分 " in line:
                s["fake"] += 1
            elif " 猜 " in line:
                s["guess"] += 1
            else:
                s["hit"] += 1
        elif "[?]" in line or "[!]" in line:
            s["miss"] += 1

    _stats_cache["key"] = key
    _stats_cache["val"] = dict(s)

    s["running"] = running
    return s


def _tail(n: int = 200) -> list[str]:
    if not LOG.exists():
        return []
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


# ------------------------------------------------------------------ 手机画面

# 画面走 screenrecord 的 H.264 流（见 app/screen_stream.py）：
#   screencap 单帧 600-800ms，做连续画面必然卡；H.264 流能到 20fps 以上。
# 流断了（设备掉线 / screenrecord 到时）由 ScreenStream 自己重启。
_stream = None


def _pick_serial() -> str:
    st = _device_status()
    return st.get("serial", "") if st.get("connected") else ""


def start_screen() -> None:
    global _stream
    if _stream is not None:
        return
    try:
        from screen_stream import ScreenStream
    except Exception as e:  # noqa: BLE001 - 缺 av 依赖时降级，不影响主功能
        # 打包后没有控制台，光 print 用户看不到；写进 crash.log
        import traceback
        try:
            (ROOT / "logs" / "screen_error.log").write_text(
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                encoding="utf-8")
        except Exception:
            pass
        print(f"[画面] 无法加载流模块（{e}），画面不可用")
        return
    _stream = ScreenStream(_adb(), _pick_serial)
    _stream.start()


def screen_jpeg() -> bytes:
    s = _stream
    return s.latest() if s is not None else b""


def screen_meta() -> dict:
    s = _stream
    if s is None:
        # 只在流模块加载失败时走到这里（正常情况 start_screen 会建实例）
        return {"mode": "off", "size": 0, "age": None, "fps": 0,
                "decoded": 0, "err": "未启动"}
    return s.stats()

# ------------------------------------------------------------------ 启停

def start_bot(live: bool = True) -> dict:
    global _proc
    with _proc_lock:
        if _proc is not None and _proc.poll() is None:
            return {"ok": False, "msg": "已经在跑了"}
        st = _device_status()
        if not st["connected"]:
            return {"ok": False,
                    "msg": "手机没连上，" + (st["error"] or "请先连接设备")}
        LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            LOG.write_text("", encoding="utf-8")
        except OSError:
            pass
        # 新一局从零开始：清掉统计缓存，避免沿用上一局的数
        _stats_cache["key"] = None
        _stats_cache["val"] = None
        args = [sys.executable, "-X", "utf8", str(SRC / "run_watch.py"),
                "--max", "130", "--minutes", "30", "--wait", "600"]
        if live:
            args.append("--live")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        _proc = proc.popen(args, cwd=str(ROOT), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=flags)
        return {"ok": True, "msg": "已启动" + ("" if live else "（只读）")}


def stop_bot() -> dict:
    global _proc
    with _proc_lock:
        if _proc is None or _proc.poll() is not None:
            _proc = None
            return {"ok": False, "msg": "没在跑"}
        try:
            if os.name == "nt":
                proc.run(["taskkill", "/PID", str(_proc.pid), "/T", "/F"],
                         capture_output=True, timeout=10)
            else:
                _proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        _proc = None
        return {"ok": True, "msg": "已停止"}


# ------------------------------------------------------------------ 连接

def conn_scan() -> dict:
    st = _device_status()
    saved = _load_wireless()
    return {"status": st, "mdns": _mdns(), "saved": saved,
            "onboarded": bool(saved.get("onboarded")),
            "last_ip": saved.get("ip", "")}


def mark_onboarded() -> dict:
    st = _load_wireless()
    st["onboarded"] = True
    _save_wireless(st)
    return {"ok": True, "msg": "已记住"}


def conn_wifi_pair(addr: str, code: str) -> dict:
    addr = (addr or "").strip()
    code = (code or "").strip()
    if ":" not in addr:
        return {"ok": False, "msg": "配对地址要带端口，例如 192.168.0.103:41234"}
    if not code.isdigit():
        return {"ok": False, "msg": "配对码是 6 位数字"}
    rc, out = _run(["pair", addr, code], timeout=40)
    ok = "Successfully paired" in out or rc == 0
    if ok:
        st = _load_wireless()
        st["ip"] = addr.split(":")[0]
        st["pair_addr"] = addr
        _save_wireless(st)
        return {"ok": True, "msg": "配对成功，接着点连接"}
    return {"ok": False, "msg": out[:200] or "配对失败"}


def conn_wifi_connect(addr: str = "") -> dict:
    addr = (addr or "").strip()
    st = _load_wireless()
    if not addr:
        ip = st.get("ip")
        if not ip:
            return {"ok": False, "msg": "还没有地址，先配对"}
        addr = f"{ip}:{st.get('port', 5555)}"
    elif ":" not in addr:
        addr = addr + ":5555"

    rc, out = _run(["connect", addr], timeout=30)
    ok = "connected to" in out.lower()
    if not ok:
        return {"ok": False, "msg": out[:200] or "连接失败"}

    st["ip"] = addr.split(":")[0]
    st["port"] = addr.split(":")[1]
    _save_wireless(st)
    for _ in range(8):
        time.sleep(0.4)
        if _device_status()["connected"]:
            return {"ok": True, "msg": f"已连接 {addr}"}
    return {"ok": False, "msg": "adb 说连上了但设备没就绪，检查手机是否授权"}


def conn_wifi_disconnect() -> dict:
    d = _device_status()
    if d["mode"] != "wifi":
        return {"ok": False, "msg": "当前不是无线连接"}
    _run(["disconnect"], timeout=15)
    return {"ok": True, "msg": "已断开无线"}


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, (UI / "index.html").read_bytes(),
                              "text/html; charset=utf-8")
        if p == "/api/status":
            return self._json({"stats": _stats_from_log(),
                               "device": _device_status(), "tail": _tail(120)})
        if p == "/api/config":
            return self._json({"text": read_config(), "summary": config_summary()})
        if p == "/api/conn":
            return self._json(conn_scan())
        if p == "/api/screen.mjpeg":
            return self._mjpeg()
        if p == "/api/screen.meta":
            return self._json(screen_meta())
        if p == "/api/screen.jpg":
            data = screen_jpeg()
            if not data:
                return self._send(404, b"no frame")
            return self._send(200, data, "image/jpeg")
        if p == "/api/stream":
            return self._stream()
        self._send(404, b"not found")

    def _mjpeg(self):
        """MJPEG 长连接：一个请求持续推帧。

        为什么不用前端轮询 /api/screen.jpg：
        轮询间隔受 HTTP 往返限制，900ms 一次就只有 1fps。
        MJPEG 用一个持久连接推帧，浏览器原生支持，能跑满流的帧率。

        先等首帧到手再发 200：端点在自己还不能产出内容时就回 200 是错的，
        那样前端必须额外探 /api/screen.meta 才知道该不该显示。
        等不到首帧就 503，<img> 的 onerror 自然触发。
        """
        s = _stream
        first_seq, first = (0, b"")
        if s is not None:
            first_seq, first = s.wait_frame(0, timeout=3.0)

        if not first:
            # 还没有任何帧（设备没连 / 刚启动）：明确告诉客户端失败
            self.send_error(503, "no frame yet")
            return

        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        seq, data = first_seq, first
        try:
            while True:
                # 拼成一个 bytes 一次写出：原实现每帧 4 次 write，
                # 而 wbufsize=0 表示每次都是独立 sendall（20fps 就是 80 syscall/s）。
                head = (b"--frame\r\nContent-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(data)}\r\n\r\n".encode())
                self.wfile.write(head + data + b"\r\n")
                self.wfile.flush()

                s = _stream
                if s is None:
                    return
                # 阻塞等下一条新帧；5 秒没有就断开让前端重连
                new_seq, new_data = s.wait_frame(seq, timeout=5.0)
                if not new_data:
                    return
                seq, data = new_seq, new_data
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = 0
        try:
            while True:
                st = _stats_from_log()
                payload = {"stats": st, "device": _device_status()}
                if st["lines"] < last:
                    payload["reset"] = True
                last = st["lines"]
                self.wfile.write(
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
                for ln in _tail(400)[-40:]:
                    self.wfile.write(
                        f"event: log\ndata: {json.dumps(ln, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        p = self.path.split("?")[0]
        try:
            b = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:  # noqa: BLE001
            b = {}

        routes = {
            "/api/start": lambda: start_bot(bool(b.get("live", True))),
            "/api/stop": stop_bot,
            "/api/config": lambda: write_config(b.get("text", "")),
            "/api/config/check": lambda: check_config(b.get("text", "")),
            "/api/wifi/pair": lambda: conn_wifi_pair(b.get("addr", ""), b.get("code", "")),
            "/api/wifi/connect": lambda: conn_wifi_connect(b.get("addr", "")),
            "/api/wifi/disconnect": conn_wifi_disconnect,
            "/api/onboarded": mark_onboarded,
        }
        fn = routes.get(p)
        if fn is None:
            return self._send(404, b"not found")
        self._json(fn())


def serve():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


def main() -> None:
    """开发态入口：后端 + pywebview 原生窗口。

    打包后（exe）不走这里 —— 见 app/launcher.py，它只用 serve()，
    窗口交给 Edge --app（避免 pythonnet 的 .NET 打包问题）。
    """
    threading.Thread(target=serve, daemon=True).start()
    start_screen()
    time.sleep(0.6)
    import webview
    webview.create_window(
        "天学网单词PK助手", f"http://{HOST}:{PORT}/",
        width=1280, height=820, min_size=(1000, 680),
        background_color="#FBFBFD", menu=[],
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
