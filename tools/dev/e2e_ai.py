"""端到端验证：配置 -> 环境变量 -> 真实 Jev -> 判定。

不打印密钥。跑法：python -X utf8 tools/dev/e2e_ai.py
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from ai_judge import judge  # noqa: E402
from config import load  # noqa: E402
from pk_core import Option, Question, split_prompt  # noqa: E402


def Q(prompt, options):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in options], screen_h=2800)


def main() -> None:
    cfg = load()
    print(f"配置: enabled={cfg.ai.enabled} mode={cfg.ai.mode} model={cfg.ai.model}")
    print(f"      base_url={cfg.ai.base_url}")
    print(f"      api_key={'已读到（%d 字符）' % len(cfg.ai.api_key) if cfg.ai.api_key else '❌ 空'}")
    if not cfg.ai.api_key:
        raise SystemExit("环境变量没读到，双击启动时也会读不到")

    cases = [
        ("element", ["adj. 不合法的", "n.基本部分", "vt. 提取", "n. 装置", "n. 顾问", "vt. 表达"], "n.基本部分"),
        ("adj.宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"], "grand"),
        ("harmony", ["n. 歌", "vt. 催促", "adj. 幸运的", "n.融洽相处", "n. 聚集"], "n.融洽相处"),
    ]

    ok = 0
    print()
    for prompt, opts, want in cases:
        q = Q(prompt, opts)
        t0 = time.perf_counter()
        res = judge(q, cfg.ai, timeout=5.0)
        dt = (time.perf_counter() - t0) * 1000
        good = res.text == want
        ok += good
        print(f"  [{'OK ' if good else 'MISS'}] {prompt!r} -> {res.text!r} "
              f"(期望 {want!r})  {dt:.0f}ms  置信 {res.confidence:.2f}")
        if not good and res.raw:
            print(f"         原始返回: {res.raw[:120]}")

    print(f"\n准确率 {ok}/{len(cases)}")


if __name__ == "__main__":
    main()
