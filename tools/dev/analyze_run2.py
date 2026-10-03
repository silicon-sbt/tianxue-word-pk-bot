"""分析 run2 日志的题目/选项配对，找出「选项属于另一题」的证据。

关键怀疑：dump 耗时 3.3s，期间题目可能已切换，
导致「题干是第 N 题，选项是第 N+1 题」的错配 => 判定看似成功但实际答错题。
"""
import pathlib
import re

log = pathlib.Path(r"E:\code\单词pk\logs\run2_final.txt").read_text(
    encoding="utf-8", errors="replace")

# 抓取所有 "题干 -> 判定" 行
pat = re.compile(r"\[(.?)\] \((\d+), 130\) \[(\w+)\] '([^']*)' (?:-> '([^']*)' @\((\d+),(\d+)\)|未匹配 选项=\[(.*?)\])")

rows = []
for line in log.splitlines():
    m = pat.search(line)
    if m:
        rows.append({
            "mark": m.group(1), "prog": int(m.group(2)), "dir": m.group(3),
            "prompt": m.group(4), "answer": m.group(5),
            "xy": (m.group(6), m.group(7)) if m.group(6) else None,
            "opts": m.group(8),
        })

print(f"解析出 {len(rows)} 条判定记录\n")

# 检查：判定出的答案，是否真的出现在该题的选项里
print("=== 一致性检查：判定答案是否在选项列表中 ===")
for r in rows:
    if r["mark"] == "+" and r["opts"] is None:
        # 命中行没记选项，跳过
        continue
print("(命中行未记录选项列表，改用未匹配行检查)")

for r in rows:
    if r["mark"] == "?":
        opts = [o.strip().strip("'") for o in (r["opts"] or "").split(",")]
        print(f"\n未匹配 进度{r['prog']} 题干={r['prompt']!r}")
        print(f"  选项({len(opts)}): {opts}")

# 关键：同一进度号出现多次时，题干是否一致
print("\n\n=== 同一进度号多次读取，题干/选项是否漂移 ===")
from collections import defaultdict
byp = defaultdict(list)
for r in rows:
    byp[r["prog"]].append(r)
for p, rs in sorted(byp.items()):
    if len(rs) > 1:
        prompts = {x["prompt"] for x in rs}
        ans = {x["answer"] for x in rs}
        print(f"  进度{p}: {len(rs)}次 题干={prompts} 判定={ans}")
