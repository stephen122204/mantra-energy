#!/usr/bin/env python3
# alems-platform/scripts/fix_research_query_sql.py
# =============================================================
# Fixes q01-q30 query_registry rows where sql_text contains:
#   Line 1:     title/question (e.g. "Energy per query by workflow")
#   Line 2-N:   -- comments (description)
#   Rest:       actual SELECT SQL
#
# Action:
#   - Extracts pure SQL (from SELECT onwards)
#   - Moves title → name column (if name is empty)
#   - Moves comments → description column
#   - Updates sql_text to pure SQL only
# =============================================================

import sqlite3
import re
import os

DB_PATH = os.getenv("ALEMS_DB_PATH", "data/experiments.db")

def split_sql_text(raw: str):
    """
    Split mixed sql_text into (title, description, pure_sql).
    Returns tuple of (title, description, sql).
    """
    lines      = raw.strip().splitlines()
    title      = ""
    desc_lines = []
    sql_lines  = []
    in_sql     = False

    for line in lines:
        stripped = line.strip()

        if in_sql:
            # Already in SQL — collect everything
            sql_lines.append(line)
            continue

        # Detect start of SQL
        if re.match(r'^\s*SELECT\b', stripped, re.IGNORECASE):
            in_sql = True
            sql_lines.append(line)
            continue

        # First non-empty, non-comment line = title
        if not title and stripped and not stripped.startswith("--"):
            title = stripped
            continue

        # Comment lines = description
        if stripped.startswith("--"):
            desc_lines.append(stripped.lstrip("- ").strip())
            continue

        # Empty lines before SQL — skip
        if not stripped:
            continue

        # Anything else before SELECT (WITH, CREATE etc.) = start of SQL
        if re.match(r'^\s*(WITH|INSERT|UPDATE|DELETE|CREATE)\b', stripped, re.IGNORECASE):
            in_sql = True
            sql_lines.append(line)

    pure_sql    = "\n".join(sql_lines).strip()
    description = " ".join(desc_lines).strip()

    return title, description, pure_sql


def fix_all(db_path: str):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get all q* rows
    rows = cur.execute("""
        SELECT id, name, description, sql_text
        FROM query_registry
        WHERE id LIKE 'q%'
          AND sql_text IS NOT NULL
          AND active = 1
    """).fetchall()

    fixed   = 0
    skipped = 0

    for row in rows:
        raw_sql = row["sql_text"] or ""

        # Skip if already clean (starts with SELECT or WITH)
        first_line = raw_sql.strip().splitlines()[0].strip() if raw_sql.strip() else ""
        if re.match(r'^\s*(SELECT|WITH)\b', first_line, re.IGNORECASE):
            skipped += 1
            continue

        title, desc, pure_sql = split_sql_text(raw_sql)

        if not pure_sql:
            print(f"  ✗ SKIP {row['id']} — no SELECT found")
            skipped += 1
            continue

        # Only update name if currently empty
        new_name = row["name"] or title or row["id"]
        new_desc = row["description"] or desc or ""

        cur.execute("""
            UPDATE query_registry
            SET sql_text    = ?,
                name        = ?,
                description = ?
            WHERE id = ?
        """, (pure_sql, new_name, new_desc, row["id"]))

        print(f"  ✓ {row['id']}")
        print(f"    name: {new_name[:60]}")
        print(f"    desc: {new_desc[:80]}")
        print(f"    sql:  {pure_sql[:60]}...")
        fixed += 1

    con.commit()
    con.close()
    print(f"\nDone: {fixed} fixed, {skipped} skipped")


if __name__ == "__main__":
    print(f"Fixing research queries in: {DB_PATH}")
    fix_all(DB_PATH)
