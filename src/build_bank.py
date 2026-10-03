"""构建 PK 词库（双向：英->中 与 中->英）。

实测题型是双向的：
  A) 题干中文 `v.破坏`  -> 选项英文 destroy/school/mechanic/...
  B) 题干英文 `harmony` -> 选项中文 `n.歌` / `vt.催促` / `adj.幸运的` ...

所以词库要同时支持：
  - lookup_by_gloss(中文, 英文选项)   -> 反向打分
  - lookup_by_word(英文, 中文选项)    -> 正向查义项，再与选项文本比对

数据源：App 自带 ed.db（16915 词条），格式与题目一致。
输出 data/wordbank.json
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build_wordbank import split_paraphrase  # noqa: E402

# 相对本文件定位，换机器/换目录都能跑
ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ed.db"
OUT = ROOT / "data" / "wordbank.json"

_WORD_OK = re.compile(r"^[A-Za-z][A-Za-z'’\-\. ]{1,19}$")


def build() -> dict:
    con = sqlite3.connect(DB)
    words: dict[str, list[list[str]]] = {}

    def add(word: str, para: str) -> None:
        w = word.strip()
        if not w or not _WORD_OK.match(w):
            return
        senses = split_paraphrase(para or "")
        if not senses:
            return
        bucket = words.setdefault(w.lower(), [])
        for pos, gloss in senses:
            gloss = gloss.strip()
            if not gloss:
                continue
            item = [gloss, pos or ""]
            if item not in bucket:
                bucket.append(item)

    for word, para in con.execute(
        "SELECT entry, paraphrase FROM ed_entryinfo "
        "WHERE entry IS NOT NULL AND entry <> ''"
    ):
        add(word, para)

    # entry_prop 提供更细的义项（'adj. 活的，有生命的' 这种拆分粒度更好）
    for word, para in con.execute(
        """SELECT i.entry, p.paraphrase FROM ed_entry_prop p
           JOIN ed_entryinfo i ON i.entry_id = p.entry_id
           WHERE p.paraphrase IS NOT NULL"""
    ):
        add(word, para)

    OUT.write_text(json.dumps({"words": words}, ensure_ascii=False),
                   encoding="utf-8")
    return words


if __name__ == "__main__":
    w = build()
    print(f"单词数: {len(w):,}")
    print(f"义项数: {sum(len(v) for v in w.values()):,}")
    print(f"size: {OUT.stat().st_size/1024/1024:.1f} MB")
    for p in ("grand", "living", "eagle", "harmony", "destroy"):
        print(f"  {p}: {w.get(p)}")
