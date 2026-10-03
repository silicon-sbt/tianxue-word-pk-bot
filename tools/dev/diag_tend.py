"""查 tend 误判：'vi. & vt.举起' 是怎么拿到分的。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import split_prompt, sense_similarity  # noqa: E402

data = json.loads(
    pathlib.Path(r"E:\code\单词pk\data\wordbank.json").read_text(encoding="utf-8"))["words"]

opt = "vi. & vt.举起"
print(f"选项原文: {opt!r}")
print(f"split_prompt -> {split_prompt(opt)}")
print()

# tend 的义项
print("tend 义项:")
for g, p in data.get("tend", []):
    print(f"   {g!r} ({p})")

print("\n逐个义项 vs 该选项:")
_, og = split_prompt(opt)
print(f"  解析出的释义 = {og!r}")
for g, p in data.get("tend", []):
    print(f"   {g!r} vs {og!r} = {sense_similarity(g, og):.2f}")

print("\n正确选项:")
print(f"  split_prompt('v. 倾向') -> {split_prompt('v. 倾向')}")
for g, p in data.get("tend", []):
    print(f"   {g!r} vs '倾向' = {sense_similarity(g, '倾向'):.2f}")
