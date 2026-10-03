"""用真实调用路径验证 resemble 误判是否修复。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import WordBank, resolve, Question, Option, split_prompt  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

bank = WordBank()
for w, senses in data.items():
    bank.words.add(w)
    for g, p in senses:
        bank.add_sense(w, g, p or None)
        bank.by_gloss.setdefault(g.strip().lower(), set()).add(w)


def Q(prompt, opts):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in opts], screen_h=2800)


# 复现 run4 里的那题（选项按当时可能的集合）
cases = [
    ("n.图像", ["image", "resemble", "picture", "scene", "structure", "advance"], "image"),
    ("n.图像", ["resemble", "image", "advance", "structure", "scene", "picture"], "image"),
]

for prompt, opts, want in cases:
    q = Q(prompt, opts)
    scored = bank.score_options(q.gloss, q.option_texts(), q.pos)
    got = resolve(q, bank)
    print(f"\n题干 {prompt!r}  期望={want!r}  判定={got!r}")
    print("  打分排序:")
    for s, w in scored[:5]:
        mark = "  <-- 期望" if w == want else ""
        print(f"    {s:.2f}  {w}{mark}")
