import os
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.normpath(os.path.join(_HERE, "..", "nomadright_kb.db"))
if not os.path.exists(db_path):
    db_path = "nomadright/nomadright_kb.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

scheme_id = "MGNREGS_001"
print(f"=== MGNREGS Data in {db_path} ===\n")

tables = [
    "eligibility", "beneficiary_categories", "documents",
    "benefits", "application_steps", "state_rules",
    "exceptions_and_limitations", "faq", "important_definitions",
    "official_contacts"
]

for t in tables:
    cur.execute(f"SELECT * FROM {t} WHERE scheme_id = ?", (scheme_id,))
    rows = cur.fetchall()
    print(f"--- {t} ({len(rows)} rows) ---")
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, str) and len(v) > 100:
                d[k] = v[:100] + "..."
        print(" ", d)
    print()

conn.close()
