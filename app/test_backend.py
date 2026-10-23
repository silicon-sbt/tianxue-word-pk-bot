"""后端自检：不起窗口，只验证 HTTP 接口和各函数。

跑法：python -X utf8 app/test_backend.py
"""
import json
import pathlib
import sys
import threading
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import main  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


print("== 纯函数 ==")
st = main._stats_from_log()
check("统计是 dict", isinstance(st, dict), True)
check("含 running 字段", "running" in st, True)
check("tail 返回 list", isinstance(main._tail(5), list), True)

dev = main._device_status()
check("设备状态是 dict", isinstance(dev, dict), True)
check("含 connected", "connected" in dev, True)
print(f"       设备: connected={dev['connected']} serial={dev['serial']!r}")

# 配置读写
cfg = main.read_config()
check("能读 config.toml", len(cfg) > 0, True)
bad = main.write_config("this is [not toml")
check("坏 TOML 被拒", bad["ok"], False)
print(f"       拒绝理由: {bad['msg'][:70]}")
bad2 = main.write_config('a = 1')
check("合法 TOML 接受", bad2["ok"], True)
main.write_config(cfg)          # 还原
check("已还原配置", main.read_config(), cfg)

# 启停（不真跑，只测重复调用不炸）
check("未运行时停止不炸", main.stop_bot()["ok"], False)


print("\n== HTTP 接口 ==")
threading.Thread(target=main.serve, daemon=True).start()
time.sleep(0.8)
BASE = f"http://{main.HOST}:{main.PORT}"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return r.status, r.read()


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.status, json.loads(r.read().decode())


code, body = get("/")
check("首页 200", code, 200)
check("首页是 HTML", b"<!DOCTYPE html>" in body, True)
check("首页含中文标题", "天学网".encode() in body, True)

code, body = get("/api/status")
d = json.loads(body)
check("status 200", code, 200)
check("status 含 stats/device/tail", sorted(d.keys()), ["device", "stats", "tail"])

code, body = get("/api/config")
check("config 200", code, 200)
_cd = json.loads(body)
check("config 含 text/summary", sorted(_cd.keys()), ["summary", "text"])
check("config.text 与磁盘一致", _cd["text"], cfg)
_sm = _cd["summary"]
check("summary 能判出 AI 状态", isinstance(_sm.get("ai_enabled"), bool), True)
check("summary 有 key 探测", "key_present" in _sm, True)
print(f"       AI={_sm['ai_enabled']} mode={_sm['ai_mode']} model={_sm['ai_model']} "
      f"key={'有' if _sm['key_present'] else '无'}")

code, r = post("/api/config", {"text": "bad [["})
check("保存坏配置被拒", r["ok"], False)
code, r = post("/api/config", {"text": cfg})
check("保存好配置成功", r["ok"], True)

# 404
try:
    get("/nope")
    check("未知路径 404", False, True)
except urllib.error.HTTPError as e:
    check("未知路径 404", e.code, 404)

print()
if FAILS:
    print(f"失败 {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("全部通过")
