"""通过 CDP 点击并截图真实页面（验证设置页渲染）。"""
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import websocket

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
URL = "http://127.0.0.1:8791/"
PORT = 9336
OUT = Path(r"E:\code\单词pk\captures")


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=20)
        self.id = 0

    def send(self, method, params=None):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.id:
                return m

    def eval(self, expr):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")

    def shot(self, name):
        r = self.send("Page.captureScreenshot", {"format": "png"})
        data = r["result"]["data"]
        (OUT / name).write_bytes(base64.b64decode(data))
        print(f"  {name}")


def main():
    prof = os.path.join(os.environ["TEMP"], "edge-cdp-shot")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={prof}", "--disable-gpu", "--remote-allow-origins=*",
         "--window-size=1280,800", URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    try:
        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=8).read())
        page = next(x for x in d if x.get("url", "").startswith("http"))
        c = CDP(page["webSocketDebuggerUrl"])
        c.send("Page.enable")
        c.send("Runtime.enable")
        time.sleep(1.5)

        c.shot("shot_run.png")

        # 切设置页
        c.eval("document.querySelector('[data-view=settings]').click(); 1")
        time.sleep(1.2)
        c.shot("shot_settings.png")

        # 切回
        c.eval("document.querySelector('[data-view=run]').click(); 1")
        time.sleep(0.5)

        # 弹引导
        c.eval("showOnboard(); 1")
        time.sleep(0.9)
        c.shot("shot_onboard.png")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
