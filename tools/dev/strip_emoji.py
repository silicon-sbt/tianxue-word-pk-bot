"""清理项目里的 emoji 与装饰性符号。

规则（本人明确要求，2026-10-19）：只要能写字的地方都不要 emoji，符号也尽量别用。
这里处理两类：
 1. emoji（表情符号）
 2. 装饰性符号：箭头、制表符画线、约等号、数学符号等，换成纯文字
保留：中英文标点、全角破折号、代码必需字符。
"""
import pathlib
import re

ROOT = pathlib.Path(r"E:\code\单词pk")

EMOJI = re.compile(
 "["
 "\U0001F300-\U0001FAFF"
 "\U0001F000-\U0001F0FF"
 "\U0001F1E6-\U0001F1FF"
 "\u2705\u274c\u2b50\u2728\u26a0\u2757\u2753\u2764"
 "]+"
)

SYMBOLS = [
 ("->", "->"), ("->", "->"), ("->", "->"),
 ("->", "->"), ("<-", "<-"), ("^", "^"), ("v", "v"), ("<->", "<->"),
 ("约", "约"), ("不等于", "不等于"), ("<=", "<="), (">=", ">="), ("属于", "属于"),
 ("x", "x"), ("v", "v"), ("*", "*"), ("o", "o"),
 ("-", "-"), ("-", "-"), ("-", "-"), ("|", "|"),
]

SKIP_DIRS = {".git", "node_modules", "logs", "captures", "samples",
 "__pycache__", "data", "tools/dev", "video"}
EXTS = {".py", ".html", ".md", ".toml", ".css", ".js", ".bat", ".vbs", ".yml"}


def main():
 changed = []
 for f in ROOT.rglob("*"):
 if not f.is_file():
 continue
 if any(p in f.parts for p in SKIP_DIRS):
 continue
 if f.suffix.lower() not in EXTS:
 continue
 try:
 text = f.read_text(encoding="utf-8")
 except (UnicodeDecodeError, OSError):
 continue
 orig = text
 text = EMOJI.sub("", text)
 for a, b in SYMBOLS:
 text = text.replace(a, b)
 if text == orig:
 continue
 text = re.sub(r"[ \t]+$", "", text, flags=re.M)
 text = re.sub(r"(?<!^)[ \t]{2,}(?=\S)", " ", text)
 f.write_text(text, encoding="utf-8")
 changed.append(f.relative_to(ROOT))
 for rel in changed:
 print(f" {rel}")
 print(f"\n清理 {len(changed)} 个文件")


if __name__ == "__main__":
 main()
