"""检查 index.html 里 JS 引用的元素是否都存在于 HTML。"""
import pathlib
import re

h = pathlib.Path(r"E:\code\单词pk\app\index.html").read_text(encoding="utf-8")
i = h.find("<script>")
js = h[i:]

refs = sorted(set(re.findall(r"\$\('([\w-]+)'\)", js)))
ids = set(re.findall(r'id="([\w-]+)"', h))
missing = [r for r in refs if r not in ids]

print(f"JS 引用 {len(refs)} 个元素")
print(f"HTML 定义 {len(ids)} 个 id")
print()

if missing:
    print("!! 引用了但不存在:")
    lines = js.splitlines()
    for m in missing:
        for n, line in enumerate(lines, 1):
            if f"$('{m}')" in line:
                print(f"   [{m}] L{n}: {line.strip()[:100]}")
                break
else:
    print("全部存在")

# 也检查 querySelectorAll 的选择器
print()
for sel in [".nav-item", ".view", ".choice", ".tab", ".cfg-pane"]:
    cnt = len(re.findall(f'class="[^"]*{sel[1:]}[^"]*"', h))
    print(f"  {sel}: HTML 里 {cnt} 个")
