"""构建高中词库（供 PK 反向打分使用）。

输出 data/wordbank.json:
  { "words": { "grand": [["雄伟的","adj."], ["盛大的","adj."]], ... } }

之所以按 word 存 senses，是因为 PK 题干用的是教材释义，
与词典措辞不一致（'宏伟的' vs '雄伟的'），必须靠反向相似度匹配。
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build_wordbank import split_paraphrase  # noqa: E402

DB = pathlib.Path(r"E:\code\单词pk\data\ed.db")
OUT = pathlib.Path(r"E:\code\单词pk\data\wordbank.json")

# 只保留适合 PK 的单词形态：纯字母（可带连字符/点），长度 2..20
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

    for word, para in con.execute(
        """SELECT i.entry, p.paraphrase FROM ed_entry_prop p
           JOIN ed_entryinfo i ON i.entry_id = p.entry_id
           WHERE p.paraphrase IS NOT NULL"""
    ):
        add(word, para)

    data = {"words": words}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


if __name__ == "__main__":
    d = build()
    w = d["words"]
    total_senses = sum(len(v) for v in w.values())
    print(f"单词数: {len(w):,}")
    print(f"义项数: {total_senses:,}")
    for probe in ("grand", "living", "eagle", "magnificent", "exact"):
        print(f"  {probe}: {w.get(probe)}")
    size = OUT.stat().st_size / 1024 / 1024
    print(f"size: {size:.1f} MB")
