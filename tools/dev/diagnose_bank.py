"""诊断：为什么 '宏伟的'->grand / '活的'->living 查不到。看 ed.db 里真实存什么。"""
import sqlite3
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

DB = pathlib.Path(r"E:\code\单词pk\data\ed.db")
con = sqlite3.connect(DB)

for w in ("grand", "living", "live", "eagle", "magnificent"):
    print(f"\n=== {w} ===")
    rows = list(con.execute(
        "SELECT entry_id, entry, paraphrase FROM ed_entryinfo WHERE entry = ?", (w,)))
    for eid, entry, para in rows:
        print(f"  entryinfo: {entry!r} :: {para!r}")
        props = list(con.execute(
            "SELECT paraphrase FROM ed_entry_prop WHERE entry_id=? ORDER BY display_order", (eid,)))
        for (p,) in props[:8]:
            print(f"     prop: {p!r}")

# 统计 paraphrase 里含 "宏伟" 的条目
print("\n=== 含 '宏伟' 的条目 ===")
for r in con.execute("SELECT entry, paraphrase FROM ed_entryinfo WHERE paraphrase LIKE '%宏伟%' LIMIT 10"):
    print("   ", r)
print("\n=== 含 '活的' 的条目 ===")
for r in con.execute("SELECT entry, paraphrase FROM ed_entryinfo WHERE paraphrase LIKE '%活的%' LIMIT 10"):
    print("   ", r)
