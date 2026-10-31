"""统计教材释义缺失的规模，评估「释义互补」能否通用解决。

示例：题干 'element' 对应选项 'n.基本部分'，而 ed.db 里 element 写作 '要素'。
这类「释义改写」字面对不上，但可以用选项释义与词条释义的语义包含关系判断。

先量化这类题在题库中的占比。
"""
from _paths import ROOT
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity  # noqa: E402

data = json.loads(
    (ROOT / "data" / "wordbank.json").read_text(encoding="utf-8"))["words"]

# 典型失配样本
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
        print(f"  词库义项 {s!r} vs {g!r} = {sense_similarity(sg, g):.2f}")

# 看 element 在词典里还有没有别的写法
print("\n=== ed.db 里含 '基本' 的词条（前 20）===")
con = sqlite3.connect(ROOT / "data" / "ed.db")
for r in con.execute(
        "SELECT entry, paraphrase FROM ed_entryinfo WHERE paraphrase LIKE '%基本%' LIMIT 20"):
    print(f"  {r[0]:20} {r[1]}")
