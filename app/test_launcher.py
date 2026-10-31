"""桌面启动器自检：窗口匹配与回环直连。

覆盖两个容易被忽略、但会直接影响启动/退出的行为：
  - 窗口标题必须精确匹配，否则关窗后进程不退、端口一直占着
  - 回环请求必须绕过系统/环境变量代理，否则延迟增加，代理不稳时会误判后端没起来

跑法：python -X utf8 app/test_launcher.py
"""
import http.server
import os
import pathlib
import sys
import threading
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import launcher  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


print("== 窗口标题匹配（必须精确）==")
check("页面标题", launcher._is_our_window_title("天学网单词PK助手"), True)
check("加载中标题", launcher._is_our_window_title("127.0.0.1"), True)
check("带空格", launcher._is_our_window_title("  天学网单词PK助手  "), True)
# 标题包含项目名的窗口（如 IDE）不能被当成程序窗口，否则关窗后进程不会退出
check("IDE 标题不算", launcher._is_our_window_title("天学网单词PK助手开发 — DeepSeek Harness"), False)
check("文件夹标题不算", launcher._is_our_window_title("单词pk - 天学网单词PK助手备份"), False)
check("带端口的地址不算", launcher._is_our_window_title("127.0.0.1:8791"), False)
check("空标题", launcher._is_our_window_title(""), False)
check("None", launcher._is_our_window_title(None), False)

print("\n== 回环直连（绕过代理）==")
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

old = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}
for k in old:
    os.environ.pop(k, None)
os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"      # 黑洞代理：连上就失败
os.environ["http_proxy"] = "http://127.0.0.1:9"
try:
    url = f"http://127.0.0.1:{port}/"
    t0 = time.perf_counter()
    with launcher._local_opener().open(url, timeout=3) as r:
        body = r.read()
    dt = time.perf_counter() - t0
    check("绕代理拿到 200", (r.status, body), (200, b"ok"))
    check("耗时 < 1s", dt < 1.0, True)
    print(f"       {dt * 1000:.0f} ms")

    # 对照组：默认 opener 会被环境变量代理带走，必须失败
    try:
        urllib.request.urlopen(url, timeout=3).read()
        default_ok = True
    except Exception:
        default_ok = False
    check("默认 opener 确实被代理影响（证明用例有效）", default_ok, False)
finally:
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    srv.shutdown()

print("\n== 端口监听者识别 ==")
srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port2 = srv2.server_address[1]
threading.Thread(target=srv2.serve_forever, daemon=True).start()
time.sleep(0.2)
check(f"能认出自己的监听 PID（{port2}）", launcher._port_listener_pid(port2), os.getpid())
srv2.shutdown()
srv2.server_close()
time.sleep(0.3)
check("端口关闭后返回 None", launcher._port_listener_pid(port2), None)

print()
if FAILS:
    print(f"失败 {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("全部通过")
