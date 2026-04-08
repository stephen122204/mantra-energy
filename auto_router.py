# alems-platform/auto_router.py
# Reads query_registry from DB → auto-registers GET endpoints.
# Updates the existing server.py pattern.
# Called on startup and on /internal/reload webhook.
# Zero restart needed — app.add_api_route() is live immediately.

import json
import logging
from fastapi import FastAPI
import os


logger = logging.getLogger(__name__)


def register_all_from_db(app: FastAPI, get_conn) -> int:
    """
    Register all active sql_* queries as GET endpoints.
    get_conn: callable that returns a DB connection (from server.py _conn())

    Returns count of newly registered endpoints.
    Skips: computed, sql_column types (not endpoints).
    Skips: already registered paths (safe to call multiple times).
    """
    with get_conn() as db:
        rows = db.execute("""
            SELECT id, name, description, metric_type,
                   sql_text, sql_file, returns,
                   endpoint_path, group_name, parameters,
                   enrich_metrics, cache_ttl_sec
            FROM query_registry
            WHERE active = 1
              AND metric_type IN ('sql_aggregate','sql_rows','timeseries')
              AND endpoint_path IS NOT NULL
        """).fetchall()
        rows = [dict(r) for r in rows]

    # Validate before registering any
    _validate_registry(rows)

    existing_paths = {r.path for r in app.routes}
    registered     = 0

    for row in rows:
        path = row["endpoint_path"]
        if path in existing_paths:
            logger.debug(f"  skip (exists): {path}")
            continue

        handler = _make_handler(row, get_conn)
        app.add_api_route(
            path     = path,
            endpoint = handler,
            methods  = ["GET"],
            tags     = [row.get("group_name", "analytics")],
            summary  = row.get("name", row["id"]),
            description = row.get("description", ""),
        )
        logger.info(f"  ✓ registered: GET {path}")
        registered += 1

    return registered


def _validate_registry(rows: list) -> None:
    """
    Validate all SQL rows before registering any endpoint.
    Fails loud at startup — never silently serve empty endpoints.
    """
    import os
    for row in rows:
        has_sql_text = bool((row.get("sql_text") or "").strip())
        has_sql_file = bool(row.get("sql_file"))

        if not has_sql_text and not has_sql_file:
            raise ValueError(
                f"\n\nquery_registry validation FAILED:\n"
                f"  id:       {row['id']}\n"
                f"  path:     {row['endpoint_path']}\n"
                f"  sql_text: NULL\n"
                f"  sql_file: NULL\n"
                f"\nFix: add sql_text for this query in Directus admin\n"
                f"  URL: http://localhost:8055/admin/content/query_registry\n"
            )

        if has_sql_file and not has_sql_text:
            if not os.path.exists(row["sql_file"]):
                raise FileNotFoundError(
                    f"query_registry[{row['id']}]: "
                    f"sql_file not found: {row['sql_file']}\n"
                    f"Add sql_text in Directus to fix."
                )


def _resolve_sql(row: dict) -> str:
    """
    Resolve SQL from registry row.
    Prefers sql_text (DB-managed).
    Falls back to sql_file (legacy, queries/ folder).
    """
    is_pg = bool(os.getenv("ALEMS_DB_URL",""))
    if is_pg and (row.get("sql_text_pg") or "").strip():
        return row["sql_text_pg"]
    if (row.get("sql_text") or "").strip():
        return row["sql_text"]
    if row.get("sql_file"):
        base = Path(os.getenv("ALEMS_BASE",".")) / "queries"
        if is_pg:
            pg = base / row["sql_file"].replace(".sql",".pg.sql")
            if pg.exists(): return pg.read_text()
        return (base / row["sql_file"]).read_text()
    raise ValueError(f"No SQL for: {row['id']}")


def _make_handler(row: dict, get_conn):
    """
    Build async handler for one query_registry row.
    Handles: optional limit/exp_id/run_id params.
    Merges computed metrics when enrich_metrics=1.
    """
    from metric_engine import compute_batch

    qid      = row["id"]
    enrich   = bool(row.get("enrich_metrics", 0))
    returns  = row.get("returns", "rows")
    params   = json.loads(row.get("parameters") or "{}")
    sql      = _resolve_sql(row)

    # Build param signature dynamically
    has_limit  = "limit" in params
    has_exp_id = "exp_id" in params
    has_run_id = "run_id" in params

    def _exec(query_params: dict):
        import re
        with get_conn() as db:
            # Adapt :param → ? for SQLite or %(param)s for PG
            import os
            is_pg = bool(os.getenv("ALEMS_DB_URL", ""))
            if is_pg:
                adapted = re.sub(r':(\w+)', r'%(\1)s', sql)
            else:
                adapted = sql
            cur = db.cursor()
            cur.execute(adapted, query_params)
            rows = [dict(r) for r in cur.fetchall()]
        return rows

    if has_limit:
        default_limit = params["limit"].get("default", 50) if isinstance(params["limit"], dict) else 50

        async def handler(limit: int = default_limit):
            rows = _exec({"limit": limit})
            if enrich and returns == "single_row":
                base = rows[0] if rows else {}
                computed = {}
                return {**base, **computed}
            return rows[0] if returns == "single_row" and rows else rows

    elif has_exp_id:
        async def handler(exp_id: int):
            rows = _exec({"exp_id": exp_id})
            return rows

    elif has_run_id:
        async def handler(run_id: int):
            rows = _exec({"run_id": run_id})
            return rows

    else:
        async def handler():
            rows = _exec({})
            if enrich and returns == "single_row":
                base = rows[0] if rows else {}
                computed = compute_batch(base, None)
                return {**base, **computed}
            return rows[0] if returns == "single_row" and rows else rows

    handler.__name__ = f"get_{qid}"
    return handler
