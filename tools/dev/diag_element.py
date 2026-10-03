"""诊断 element 这题：为什么 'n.基本部分' 匹配不上。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

print("=== element 的义项 ===")
for s in data.get("element", []):
    print("  ", s)

opts = ['adj. 不合法的', 'n.基本部分', 'vt. 提取', 'n. 装置', 'n. 顾问', 'vt. 表达']
print("\n=== element 义项 vs 各选项 的相似度 ===")
for g, p in data.get("element", []):
    print(f"  义项 {g!r} ({p}):")
    for o in opts:
        og = o.split(".", 1)[-1].strip()
        s = sense_similarity(g, og)
        if s > 0:
            print(f"     vs {o!r:16} = {s:.2f}")
