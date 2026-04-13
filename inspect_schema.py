import sqlite3, json

db_path = "data/experiments.db"  # adjust if needed
con = sqlite3.connect(db_path)
cur = con.cursor()

# All tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(f"\n{'='*60}")
print(f"TOTAL TABLES: {len(tables)}")
print(f"{'='*60}")

schema = {}
total_cols = 0
for t in tables:
    cur.execute(f"PRAGMA table_info('{t}')")
    cols = cur.fetchall()
    cur.execute(f"SELECT COUNT(*) FROM '{t}'")
    row_count = cur.fetchone()[0]
    col_names = [c[1] for c in cols]
    schema[t] = {"columns": col_names, "col_count": len(cols), "rows": row_count}
    total_cols += len(cols)
    print(f"\n[{t}]  ({len(cols)} cols, {row_count} rows)")
    for c in cols:
        print(f"  {c[1]:40s} {c[2]}")

print(f"\n{'='*60}")
print(f"TOTAL COLUMNS ACROSS ALL TABLES: {total_cols}")
print(f"{'='*60}")

con.close()
