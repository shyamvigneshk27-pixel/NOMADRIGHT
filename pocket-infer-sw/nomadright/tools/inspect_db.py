import os
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.normpath(os.path.join(_HERE, "..", "nomadright_kb.db"))
if not os.path.exists(db_path):
    db_path = "nomadright/nomadright_kb.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for t in tables:
    cur.execute("PRAGMA table_info(" + t + ")")
    cols = [c["name"] for c in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM " + t)
    count = cur.fetchone()[0]
    print(f"\n  [{t}]  ({count} rows)  cols: {cols}")
    cur.execute("SELECT * FROM " + t + " LIMIT 3")
    for row in cur.fetchall():
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, str) and len(v) > 80:
                d[k] = v[:80] + "..."
        print("   ", d)

conn.close()
