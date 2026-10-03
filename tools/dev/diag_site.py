"""查 'site' -> 'n.网站' 为什么未匹配（这题本应可解）。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
from pk_core import WordBank, resolve, Question, Option, split_prompt  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

print("site 的义项:", data.get("site"))

bank = WordBank()
for w, senses in data.items():
    bank.words.add(w)
    for g, p in senses:
        bank.add_sense(w, g, p or None)
        bank.by_gloss.setdefault(g.strip().lower(), set()).add(w)

opts = ['n. 新闻业', 'adj. 身体的', 'vt. & vi.分解', 'vt. & vi. 伸出', 'n.网站', 'n. 山谷']
q = Question(prompt="site", pos=None, gloss="site",
             options=[Option(t, 0, 0) for t in opts], screen_h=2800)

print("\n各选项得分:")
for s, w in bank.score_options("site", opts, None):
    print(f"   {s:.2f}  {w}")

print(f"\nresolve -> {resolve(q, bank)}")
print("期望 -> n.网站")
