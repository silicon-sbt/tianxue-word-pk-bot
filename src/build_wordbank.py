"""从 ed.db 构建离线词库：中文释义 -> 英文单词。

关键点：PK 题干格式（'adj.宏伟的'）与 ed_entryinfo.paraphrase 格式一致，
所以能直接做反向查询。同时用 ed_entry_prop 补充更细的义项。
"""
from __future__ import annotations

import re
import sqlite3
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ed.db"
OUT = ROOT / "data" / "wordbank.json"

# "adj. 能；有能力的，能干的" 里切出 (词性, 义项) 对
_POS_RE = re.compile(
    r"(?P<pos>(?:adj|adv|n|v|vt|vi|prep|conj|pron|num|art|int|aux|abbr|"
    r"modal|det|interj|link-v|phr)\.)\s*"
)

_SPLIT = re.compile(r"[；;，,、/]")

# 括号内的分隔符不能切：'（建筑物，城镇等的）地点' 被按 '，' 切开后会变成
# '（建筑物' + '城镇等的）地点' 两个垃圾义项（实测 site 就是这个问题）。
_BRACKET_PAIRS = [("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")]


def _split_outside_brackets(text: str) -> list[str]:
    """按分隔符切分，但跳过括号内部。"""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if any(ch == o for o, _ in _BRACKET_PAIRS):
            depth += 1
        elif any(ch == c for _, c in _BRACKET_PAIRS):
            depth = max(0, depth - 1)
        if depth == 0 and _SPLIT.match(ch):
            seg = "".join(buf).strip()
            if seg:
                out.append(seg)
            buf = []
        else:
            buf.append(ch)
    seg = "".join(buf).strip()
    if seg:
        out.append(seg)
    return out



def _is_real_gloss(s: str) -> bool:
    """过滤解析产生的垃圾义项。

    实测：'vt. & vi.' 这种纯词性串被 '/' 切开后会留下 '&' 这种单字符，
    它会与选项 'vi. & vt.举起' 的解析结果串味，造成误判。这里剔掉。
    """
    s = s.strip()
    if not s:
        return False
    # 必须含中文，或是像样的英文词
    if any("\u4e00" <= c <= "\u9fff" for c in s):
        return True
    if len(s) <= 2:               # '&'、'vt' 这类碎片
        return False
    return bool(re.search(r"[A-Za-z]{3,}", s))



def split_paraphrase(text: str) -> list[tuple[str | None, str]]:
    """'adj. 能；有能力的，能干的' -> [('adj.','能'), ('adj.','有能力的'), ('adj.','能干的')]"""
    if not text:
        return []
    out: list[tuple[str | None, str]] = []

    def push(pos: str | None, seg: str) -> None:
        seg = seg.strip()
        if seg and _is_real_gloss(seg):
            out.append((pos, seg))

    parts = _POS_RE.split(text)
    # re.split 带捕获组：['前缀', pos, '内容', pos, '内容', ...]
    if len(parts) == 1:
        for seg in _split_outside_brackets(text):
            push(None, seg)
        return out

    lead = parts[0].strip()
    if lead:
        for seg in _split_outside_brackets(lead):
            push(None, seg)

    for i in range(1, len(parts) - 1, 2):
        pos = parts[i].strip().lower()
        body = parts[i + 1]
        for seg in _split_outside_brackets(body):
            push(pos, seg)
    return out


def build() -> dict:
    con = sqlite3.connect(DB)
    entries: dict[str, list[tuple[str | None, str]]] = {}

    # 主来源：entryinfo.paraphrase
    for word, para in con.execute(
        "SELECT entry, paraphrase FROM ed_entryinfo WHERE entry IS NOT NULL AND entry <> ''"
    ):
        word = word.strip()
        if not word or " " in word.strip("/ "):
            # 保留 'a / an' 这类，但跳过纯短语（PK 一般考单词）
            if "/" not in word:
                continue
        entries.setdefault(word, []).extend(split_paraphrase(para or ""))

    # 补充：entry_prop 里更细的义项
    for word, para in con.execute(
        """SELECT i.entry, p.paraphrase FROM ed_entry_prop p
           JOIN ed_entryinfo i ON i.entry_id = p.entry_id
           WHERE p.paraphrase IS NOT NULL"""
    ):
        word = (word or "").strip()
        if not word:
            continue
        entries.setdefault(word, []).extend(split_paraphrase(para))

    # 反转为 gloss -> words
    bank: dict[str, set[str]] = {}
    for word, senses in entries.items():
        for pos, gloss in senses:
            g = gloss.strip()
            if not g:
                continue
            for key in {g, f"{pos}{g}" if pos else g}:
                key = key.strip()
                if key:
                    bank.setdefault(key, set()).add(word)

    data = {k: sorted(v) for k, v in bank.items()}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


if __name__ == "__main__":
    data = build()
    print(f"词库条目(释义键): {len(data):,}")
    print(f"唯一中文键数: {len(set(data)):,}")
    words = {w for v in data.values() for w in v}
    print(f"覆盖英文单词: {len(words):,}")

    # 用真实 PK 题目验证
    print("\n-- 真实题目验证 --")
    cases = [
        ("宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"]),
        ("活的", ["complex", "living", "dollar", "format", "analyst", "ensure"]),
        ("鹰", ["inspire", "eagle", "comb", "exactly", "France", "match"]),
    ]
    for gloss, opts in cases:
        hit = data.get(gloss)
        print(f"  {gloss!r:8} -> {hit}   在选项中: {[o for o in opts if hit and o in hit]}")

    OUT.with_suffix(".sample.json").write_text(
        json.dumps({k: data[k] for k in list(data)[:20]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
