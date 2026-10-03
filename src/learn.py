"""自学习：把未匹配题整理成可补齐的清单。

未匹配的题都存进了 data/unknown.jsonl。这里做两件事：
  1) 汇总去重，输出人类可读的待补清单
  2) 支持从「已确认答案」回填 learned.json，下次直接命中

用法:
  python learn.py --report                     看有哪些待补
  python learn.py --add "element=n.基本部分"    手工确认一条
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNKNOWN = ROOT / "data" / "unknown.jsonl"
LEARNED = ROOT / "data" / "learned.json"


def load_unknown() -> list[dict]:
    if not UNKNOWN.exists():
        return []
    out = []
    for line in UNKNOWN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def report() -> None:
    rows = load_unknown()
    if not rows:
        print("没有未匹配记录")
        return

    # 按题干去重
    seen: dict[str, dict] = {}
    for r in rows:
        key = f"{r.get('prompt')}"
        if key not in seen:
            seen[key] = r
            seen[key]["count"] = 0
        seen[key]["count"] += 1

    print(f"未匹配题目 {len(seen)} 种（共 {len(rows)} 次）\n")
    for prompt, r in sorted(seen.items(), key=lambda kv: -kv[1]["count"]):
        print(f"[{r.get('direction')}] {prompt!r}  (出现 {r['count']} 次)")
        print(f"    词性={r.get('pos')} 释义={r.get('gloss')!r}")
        print(f"    选项={r.get('options')}")
        print()

    # 统计方向分布
    c = Counter(r.get("direction") for r in seen.values())
    print("方向分布:", dict(c))


def add(pairs: list[str]) -> None:
    learned = {}
    if LEARNED.exists():
        learned = json.loads(LEARNED.read_text(encoding="utf-8"))
    for p in pairs:
        if "=" not in p:
            print(f"跳过（格式应为 word=释义）: {p}")
            continue
        word, gloss = p.split("=", 1)
        learned[gloss.strip()] = word.strip()
        print(f"已登记: {gloss.strip()} -> {word.strip()}")
    LEARNED.write_text(json.dumps(learned, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"\nlearned.json 现有 {len(learned)} 条")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="列出去重后的待补清单")
    ap.add_argument("--add", nargs="*", default=None,
                    help='手工登记映射，格式 "word=释义"（可多个）')
    ap.add_argument("--clear", action="store_true", help="清空 unknown.jsonl")
    a = ap.parse_args()

    if a.clear:
        UNKNOWN.write_text("", encoding="utf-8")
        print("已清空 unknown.jsonl")
        return
    if a.add:
        add(a.add)
        return
    report()


if __name__ == "__main__":
    main()
