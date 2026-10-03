"""诊断未匹配题：'adj.异常的' -> unusual 为什么查不到。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity, split_prompt  # noqa: E402

BANK = pathlib.Path(r"E:\code\单词pk\data\wordbank.json")
data = json.loads(BANK.read_text(encoding="utf-8"))["words"]

gloss, opts = "异常的", ["register", "statue", "clear", "unusual", "elderly", "originality"]

print(f"题干: adj.{gloss}")
print(f"选项: {opts}\n")

for o in opts:
    senses = data.get(o.lower())
    if not senses:
        print(f"  {o:14} 词库无此词")
        continue
    best = 0.0
    best_g = None
    for g, p in senses:
        s = sense_similarity(gloss, g)
        if s > best:
            best, best_g = s, (g, p)
    print(f"  {o:14} {best:.2f}  义项={senses}")
    if best_g:
        print(f"                最佳匹配: {best_g}")
