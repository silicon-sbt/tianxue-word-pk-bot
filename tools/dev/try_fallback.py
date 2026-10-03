"""通用兜底：当字面匹配全失败时，用「词形/词根 + 选项互斥性」再试一次。

以 element -> 'n.基本部分' 为例：
  - element 词库义项=['要素','少量','天气']，与 '基本部分' 字面无关
  - 但 element 本身含 'element' 词根，'基本部分' 是它的释义改写

通用做法（不依赖逐条手补）：
  1) 若选项里有词的**词库义项**与题干(英文词)的**词库义项**存在共同近义字，加分
  2) 若某个选项的词，其释义集合中含有题干词条释义的**上位概念**，加分

这里先实现一个可测的近似：把题干词的义项与每个选项词的义项交叉比对，
找「共享义项」的候选。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity, split_prompt  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]


def senses(word: str):
    return data.get(word.lower(), [])


def cross_score(prompt_word: str, opt: str) -> float:
    """题干词 与 选项(中文释义) 的交叉分。

    关键：题干是英文词，选项是中文释义。直接比对只看题干词的义项够不够。
    element 这题失败是因为 element 没有 '基本部分' 这个义项。
    """
    pos_o, gloss_o = split_prompt(opt)
    best = 0.0
    for g, p in senses(prompt_word):
        s = sense_similarity(g, gloss_o)
        if pos_o and p and pos_o == p:
            s = min(1.0, s * 1.35)
        best = max(best, s)
    return best


print("=== element 各选项交叉分 ===")
opts = ['adj. 不合法的', 'n.基本部分', 'vt. 提取', 'n. 装置', 'n. 顾问', 'vt. 表达']
for o in opts:
    print(f"  {o:16} {cross_score('element', o):.2f}")

print("\n=== 关键检查：'基本部分' 是不是别的词的标准释义？===")
hits = []
for w, ss in data.items():
    for g, p in ss:
        if "基本" in g and "部分" in g:
            hits.append((w, g, p))
for h in hits[:20]:
    print(f"   {h[0]:18} {h[1]!r} ({h[2]})")
if not hits:
    print("   (无)")

print("\n=== '要素' 都在哪些词下 ===")
for w, ss in data.items():
    for g, p in ss:
        if g == "要素":
            print(f"   {w:18} {g!r} ({p})")
