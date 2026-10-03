"""查 run4 的误判：'n.图像' -> resemble（应为 image）。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import sense_similarity, split_prompt  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

gloss = "图像"
# 推测当时的选项集合（日志未记录命中行的选项）
cands = ["resemble", "image", "picture", "scene", "structure", "advance"]

print(f"题干: n.{gloss}")
print("\n各候选词与 '图像' 的相似度:")
for w in cands:
    ss = data.get(w, [])
    best, bg = 0.0, None
    for g, p in ss:
        s = sense_similarity(gloss, g)
        if s > best:
            best, bg = s, g
    print(f"  {w:12} {best:.2f}   义项={ss}")
    if bg:
        print(f"              最佳: {bg!r}")

print("\n=== 关键：resemble 到底为什么拿到分 ===")
for g, p in data.get("resemble", []):
    print(f"  {g!r} vs {gloss!r} = {sense_similarity(gloss, g):.2f}")

print("\n=== '图像' 在各词下的义项 ===")
for w, ss in data.items():
    for g, p in ss:
        if "图像" in g or "图象" in g:
            print(f"  {w:16} {g!r} ({p})")
