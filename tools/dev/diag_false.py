"""查误判根因：shock->游泳、tend->举起 为什么会匹配上。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity, split_prompt, _synonym_normalize  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

CASES = [
    ("shock", ['vi. & vt. 游泳', 'n. 震惊', 'adj. 焦虑的', 'n. 材料', 'v. 保持', 'n. 好处']),
    ("tend", ['vi. & vt.举起', 'v. 倾向', 'n. 素质', 'n. 鲸', 'v. 包', 'n. 耐心']),
]

for word, opts in CASES:
    print(f"\n{'='*60}")
    print(f"题干: {word}")
    print(f"词库义项: {data.get(word, [])}")
    print(f"选项: {opts}")
    print("\n各选项得分:")
    senses = data.get(word, [])
    for o in opts:
        _, og = split_prompt(o)
        best, bg = 0.0, None
        for g, p in senses:
            s = sense_similarity(g, og)
            if s > best:
                best, bg = s, g
        mark = "  <-- 高分!" if best > 0.3 else ""
        print(f"  {o:22} = {best:.2f}  (义项 {bg!r} vs {og!r}){mark}")
        if best > 0:
            print(f"      归一化后: {_synonym_normalize(bg or '')!r} vs {_synonym_normalize(og)!r}")
