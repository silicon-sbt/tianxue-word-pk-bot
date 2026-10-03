"""端到端离线验证：用真实抓屏 XML 跑完整链路（解析->判定->定位）。"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import parse_screen, resolve  # noqa: E402
from pk_bot import load_bank  # noqa: E402


def _norm(s):
    import re
    return re.sub(r"[\s\-_]+", "", (s or "").strip().lower())


def check(path: pathlib.Path, bank, expect=None):
    raw = path.read_bytes() if path.suffix == ".xml" else None
    q = parse_screen(raw if raw is not None else path.read_text(encoding="utf-8"))
    if q is None:
        return f"  {path.name}: 非答题页"
    t0 = time.perf_counter()
    ans = resolve(q, bank)
    dt = (time.perf_counter() - t0) * 1000
    coord = ""
    if ans:
        o = next((o for o in q.options if o.text == ans), None)
        coord = f" @({o.cx},{o.cy})" if o else ""
    flag = ""
    if expect:
        flag = "  OK" if ans == expect else f"  <-- 期望 {expect}"
    return (f"  {path.name}: [{q.direction}] {q.prompt!r} -> {ans!r}{coord} "
            f"({dt:.2f}ms, {len(q.options)}选项){flag}")


if __name__ == "__main__":
    bank = load_bank()
    print(f"词库: {len(bank.by_gloss):,} 键 / {len(bank.words):,} 词\n")

    samples = sorted(pathlib.Path(r"E:\code\单词pk\samples").glob("*.xml"))
    print(f"-- 扫描 {len(samples)} 个样本 --")
    for s in samples:
        print(check(s, bank))

    print("\n-- 已知答案样本 --")
    known = pathlib.Path(r"E:\code\单词pk\samples\u4.xml")
    if known.exists():
        print(check(known, bank, expect="living"))
