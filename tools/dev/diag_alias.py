"""查 ed.db 里有没有 '异常' 相关义项，判断是词库缺失还是别名问题。"""
import sqlite3
import pathlib

con = sqlite3.connect(r"E:\code\单词pk\data\ed.db")

for kw in ("异常", "不寻常", "反常", "独特"):
    print(f"=== 含 {kw} 的条目 ===")
    rows = list(con.execute(
        "SELECT entry, paraphrase FROM ed_entryinfo WHERE paraphrase LIKE ? LIMIT 10",
        (f"%{kw}%",)))
    for r in rows:
        print(f"   {r[0]:16} {r[1]}")
    if not rows:
        print("   (无)")
    print()

# unusual 的完整信息
print("=== unusual 全部字段 ===")
for r in con.execute(
    "SELECT entry_id, entry, paraphrase FROM ed_entryinfo WHERE entry='unusual'"):
    print(f"  entryinfo: {r}")
    for p in con.execute(
        "SELECT paraphrase FROM ed_entry_prop WHERE entry_id=? ORDER BY display_order",
        (r[0],)):
        print(f"     prop: {p[0]}")
