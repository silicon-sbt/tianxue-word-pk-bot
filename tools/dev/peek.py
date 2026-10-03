"""诊断当前屏幕：打印所有文本节点与分类结果。"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import parse_screen, split_prompt  # noqa: E402

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\code\单词pk\samples\live1.xml")
raw = path.read_text(encoding="utf-8", errors="replace")

print(f"file: {path}")
print(f"len: {len(raw)}")
print(f"webview nodes: {raw.count('WebView')}")

print("\n-- all text nodes --")
for m in re.finditer(r'text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', raw):
    t = m.group(1).strip()
    if not t:
        continue
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(2, 6))
    print(f"  {t!r:40} cx={(x1+x2)//2:5} cy={(y1+y2)//2:5} w={x2-x1:4} h={y2-y1:4}")

print("\n-- parse_screen --")
q = parse_screen(raw)
if q is None:
    print("  None  (未识别为答题页)")
else:
    print(f"  prompt={q.prompt!r} pos={q.pos!r} gloss={q.gloss!r}")
    print(f"  progress={q.progress} seconds={q.seconds_left}")
    print(f"  options={q.option_texts()}")
    print(f"  screen_h={q.screen_h}")
