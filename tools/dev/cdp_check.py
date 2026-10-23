"""用 CDP 在真实页面里验证视图切换 + 抓 console 错误。"""
import json
import os
import subprocess
import time
import urllib.request

import websocket  # pip install websocket-client

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
URL = "http://127.0.0.1:8791/"
PORT = 9334


def start():
    prof = os.path.join(os.environ["TEMP"], "edge-cdp2")
    p = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={prof}", "--disable-gpu", "--remote-allow-origins=*", URL],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5).read())
    page = next(x for x in d if x.get("url", "").startswith("http"))
    return p, page["webSocketDebuggerUrl"]


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=15)
        self.id = 0
        self.errors = []

    def send(self, method, params=None):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                det = msg["params"]["exceptionDetails"]
                self.errors.append(det.get("text", "") + " | " +
                                   str(det.get("exception", {}).get("description", ""))[:200])
            if msg.get("method") == "Runtime.consoleAPICalled":
                args = msg["params"].get("args", [])
                txt = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
                if msg["params"].get("type") == "error":
                    self.errors.append("console.error: " + txt[:200])
            if msg.get("id") == self.id:
                return msg

    def eval(self, expr):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True})
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return f"<EXC> {res['exceptionDetails'].get('text')}"
        return res.get("result", {}).get("value")


def main():
    proc, ws = start()
    c = CDP(ws)
    c.send("Runtime.enable")
    c.send("Page.enable")
    time.sleep(1)

    print("=== 初始状态 ===")
    print("  switchView 存在:", c.eval("typeof switchView"))
    print("  nav 数量:", c.eval("document.querySelectorAll('.nav-item').length"))
    print("  当前激活视图:", c.eval(
        "[...document.querySelectorAll('.view')].filter(v=>v.classList.contains('active')).map(v=>v.id).join(',')"))

    print("\n=== 点击「设置」 ===")
    r = c.eval("document.querySelector('[data-view=settings]').click(); 'clicked'")
    print("  点击结果:", r)
    time.sleep(0.6)
    print("  激活导航:", c.eval(
        "[...document.querySelectorAll('.nav-item.active')].map(n=>n.dataset.view).join(',')"))
    print("  激活视图:", c.eval(
        "[...document.querySelectorAll('.view')].filter(v=>v.classList.contains('active')).map(v=>v.id).join(',')"))
    print("  viewSettings display:", c.eval(
        "getComputedStyle(document.getElementById('viewSettings')).display"))

    print("\n=== 点回「运行」 ===")
    c.eval("document.querySelector('[data-view=run]').click(); 'ok'")
    time.sleep(0.4)
    print("  激活视图:", c.eval(
        "[...document.querySelectorAll('.view')].filter(v=>v.classList.contains('active')).map(v=>v.id).join(',')"))

    print("\n=== console / JS 异常 ===")
    if c.errors:
        for e in c.errors[:10]:
            print("  !!", e)
    else:
        print("  无")

    proc.terminate()


if __name__ == "__main__":
    main()
