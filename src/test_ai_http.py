"""AI 兜底的联网路径联调：起一个本地假接口，走真实 HTTP。

覆盖：正常返回 / 超时 / 500 错误 / 返回垃圾，都必须优雅降级成 None，
绝不能抛异常影响答题。

跑法：python -X utf8 src/test_ai_http.py
"""
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from ai_judge import judge  # noqa: E402
from config import Config  # noqa: E402
from pk_core import Option, Question, split_prompt  # noqa: E402

OPTS = ["grand", "kettle", "exact", "painter"]

# 服务器行为由这个开关控制
MODE = {"name": "ok"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def handle_one_request(self):
        # 超时用例里客户端会主动断开，别让服务器刷一堆栈
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)

        if MODE["name"] == "slow":
            time.sleep(3.0)
        if MODE["name"] == "500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return

        if MODE["name"] == "garbage":
            content = "这是一段没有 JSON 的胡说八道"
        elif MODE["name"] == "native":
            # Jev 原生响应结构（decisions 接口）
            body = {"answers": {"answer": {"type": "choice", "choice": "o2",
                                           "confidence": 0.88}}}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        else:
            content = json.dumps({"answers": {"answer": {
                "type": "choice", "choice": "o2", "confidence": 0.77}}})

        body = {"choices": [{"message": {"content": content}}]}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def Q(prompt, options):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in options], screen_h=2800)


def cfg(port, timeout=2.0, mode="chat"):
    key = "api_key" if mode == "chat" else "api_key"
    return Config({"ai": {"enabled": True, "mode": mode, "api_key": "test-key",
                          "base_url": f"http://127.0.0.1:{port}/v1",
                          "model": "fake", "timeout": timeout,
                          "remember": False}}).ai


def main() -> None:
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"假接口已启动 127.0.0.1:{port}\n")

    fails = []

    def check(name, got, want):
        ok = got == want
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
        if not ok:
            fails.append(name)

    q = Q("adj.宏伟的", OPTS)

    MODE["name"] = "ok"
    t0 = time.perf_counter()
    r = judge(q, cfg(port))
    dt = time.perf_counter() - t0
    check("正常返回 -> choice", r.text, "exact")
    check("正常返回 -> confidence", round(r.confidence, 2), 0.77)
    print(f"        (真实 HTTP 往返 {dt*1000:.0f}ms)")

    MODE["name"] = "native"
    # 原生 Jev 走 /decisions，必须用 mode="jev" 才会命中
    check("Jev 原生结构", judge(q, cfg(port, mode="jev")).text, "exact")

    MODE["name"] = "garbage"
    check("返回垃圾 -> None", judge(q, cfg(port)).text, None)

    MODE["name"] = "500"
    r5 = judge(q, cfg(port))
    check("HTTP 500 -> None", r5.text, None)
    check("HTTP 500 有原因", "500" in r5.raw, True)

    MODE["name"] = "slow"
    t0 = time.perf_counter()
    rs = judge(q, cfg(port, timeout=1.0))
    dt = time.perf_counter() - t0
    check("超时 -> None", rs.text, None)
    ok = dt < 2.0
    print(f"  [{'OK ' if ok else 'FAIL'}] 超时准时放弃: {dt:.2f}s (上限 1.0s)")
    if not ok:
        fails.append("超时未按时放弃")

    # 断网（没人监听的端口）也必须优雅
    check("连不上 -> None", judge(q, cfg(9)).text, None)
    # 没配 key 就不该发请求
    MODE["name"] = "ok"
    nokey = Config({"ai": {"enabled": True, "api_key": ""}}).ai
    check("无 key -> None", judge(q, nokey).text, None)
    # 关闭时直接返回
    off = Config({"ai": {"enabled": False, "api_key": "x"}}).ai
    check("未启用 -> None", judge(q, off).text, None)

    srv.shutdown()
    print()
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
