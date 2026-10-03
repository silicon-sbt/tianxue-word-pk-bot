"""真实调用一次 Jev，验证端点/schema/延迟。

从宝可梦项目的 .env 读密钥（命令行参数传入路径），密钥不落盘、不打印。
跑法：python -X utf8 tools/dev/probe_jev.py <env路径>
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from ai_judge import build_request, judge, parse_answer, post_json, TYPESAFE_ENDPOINT  # noqa: E402
from pk_core import Option, Question, split_prompt  # noqa: E402


def read_key(env_path: pathlib.Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = line.strip()
        if m.startswith("TYPESAFE_API_KEY="):
            return m.split("=", 1)[1].strip()
    raise SystemExit("找不到 TYPESAFE_API_KEY")


def Q(prompt, options):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in options], screen_h=2800)


def main() -> None:
    env_path = pathlib.Path(sys.argv[1])
    key = read_key(env_path)
    print(f"密钥已读取（{len(key)} 字符，不打印内容）\n")

    # 用一道本地词库确实判不出来的题（element -> 基本部分）
    q = Q("element", ["adj. 不合法的", "n.基本部分", "vt. 提取",
                      "n. 装置", "n. 顾问", "vt. 表达"])
    # 和一道本地能判的题作对照
    q2 = Q("adj.宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"])

    payload = build_request(q, "jev-latest")
    payload["state"] = json.dumps(payload["state"], ensure_ascii=False)
    print("请求体（state 已转字符串，符合 TypeSafe 要求）:")
    print("  model =", payload["model"])
    print("  state =", payload["state"][:80])
    print("  criteria keys =", list(payload["questions"]["answer"]["criteria"]))
    print()

    for label, qq in (("难题 element", q), ("对照 宏伟的", q2)):
        payload = build_request(qq, "jev-latest")
        payload["state"] = json.dumps(payload["state"], ensure_ascii=False)
        t0 = time.perf_counter()
        try:
            out = post_json(TYPESAFE_ENDPOINT, payload,
                            {"Authorization": "Bearer " + key}, 20.0)
        except Exception as e:  # noqa: BLE001
            print(f"  [{label}] 调用失败: {type(e).__name__}: {str(e)[:150]}")
            continue
        dt = (time.perf_counter() - t0) * 1000
        res = parse_answer(out, qq.option_texts())
        print(f"  [{label}] -> {res.text!r}  置信 {res.confidence:.2f}  "
              f"耗时 {dt:.0f}ms")
        usage = (out or {}).get("usage") if isinstance(out, dict) else None
        if usage:
            print(f"        usage={usage}")


if __name__ == "__main__":
    main()
