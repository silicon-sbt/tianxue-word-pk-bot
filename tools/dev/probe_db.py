"""探查 ed.db 结构，找出 单词->中文释义 的映射。"""
import sqlite3
import pathlib

DB = pathlib.Path(r"E:\code\单词pk\data\ed.db")
con = sqlite3.connect(DB)

print("=== tables ===")
tables = list(con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
for name, sql in tables:
    print(f"\n-- {name}")
    print("   ", (sql or "")[:400].replace("\n", " "))

print("\n=== row counts ===")
for name, _ in tables:
    try:
        n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name}: {n}")
    except Exception as e:
        print(f"  {name}: ERR {e}")

print("\n=== sample rows (first table with data) ===")
for name, _ in tables:
    try:
        rows = con.execute(f'SELECT * FROM "{name}" LIMIT 5').fetchall()
        cols = [d[0] for d in con.execute(f'SELECT * FROM "{name}" LIMIT 1').description]
        if rows:
            print(f"\n-- {name} cols={cols}")
            for r in rows:
                print("   ", str(r)[:300])
    except Exception as e:
        print(f"  {name}: ERR {e}")
