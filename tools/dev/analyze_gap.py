"""统计：教材释义缺失有多普遍？能不能用「释义互补」通用解决？

思路验证：题干 'element' -> 选项 'n.基本部分'。
ed.db 里 element='要素'，而"基本部分"≈"要素"的**解释性说法**。
这类"释义改写"无法靠字面，但可以靠：把选项释义与词条释义做**语义包含**判断。

先量化：130 题里大概多少会踩这个坑。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

# 实测遇到的失配样本
MISSES = [
    ("element", "n.基本部分", ["n. 要素"]),
    ("unusual", "adj.异常的", ["adj.不寻常的"]),
    ("grand", "adj.宏伟的", ["adj.雄伟的"]),
]

print("=== 失配样本的相似度 ===")
for word, want_gloss, senses in MISSES:
    g = want_gloss.split(".", 1)[-1].strip()
    print(f"\n{word} -> 选项 {want_gloss!r}")
    for s in senses:
        sg = s.split(".", 1)[-1].strip()
        print(f"    词库义项 {s!r}  vs  {g!r}  = {sense_similarity(sg, g):.2f}")

# 看 element 在词典里还有没有别的写法
print("\n=== ed.db 里含 '基本' 的词条（前20）===")
import sqlite3
con = sqlite3.connect(r"E:\code\单词pk\data\ed.db")
for r in con.execute(
        "SELECT entry, paraphrase FROM ed_entryinfo WHERE paraphrase LIKE '%基本%' LIMIT 20"):
    print(f"   {r[0]:20} {r[1]}")
