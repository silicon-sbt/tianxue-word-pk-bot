"""看 dump 的原始结构统计，判断内容为何不可见。"""
import re
import sys
from collections import Counter
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\code\单词pk\samples\live2.xml")
raw = p.read_text(encoding="utf-8", errors="replace")

print("file:", p)
print("len:", len(raw))
print("nodes:", raw.count("<node"))
print("text= count:", raw.count("text="))
print("content-desc count:", raw.count("content-desc="))
print()
print("--- head ---")
print(raw[:500])
print()
print("--- class histogram ---")
for k, v in Counter(re.findall(r'class="([^"]+)"', raw)).most_common(12):
    print(f"  {v:5}  {k}")
print()
print("--- non-empty text values ---")
hits = [t for t in re.findall(r'text="([^"]*)"', raw) if t.strip()]
print(f"  count={len(hits)}")
for t in hits[:30]:
    print("   ", repr(t))
print()
print("--- content-desc values ---")
descs = [d for d in re.findall(r'content-desc="([^"]*)"', raw) if d.strip()]
print(f"  count={len(descs)}")
for d in descs[:20]:
    print("   ", repr(d))
