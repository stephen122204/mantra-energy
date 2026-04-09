# alems-platform/auto_router.py
# Reads query_registry from DB → auto-registers GET endpoints.
# Called on startup and on POST /internal/reload (Directus webhook).
# Zero restart needed — app.add_api_route() is live immediately.
#
# Fix: _compute_derived_from_db() replaces broken compute_batch(base, None)
# Reads computed metric formulas directly from query_registry DB rows.

import json
import logging
import os
from pathlib import Path
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _compute_derived_from_db(base: dict, get_conn) -> dict:
    """
    Compute derived metrics (tax_multiple, energy_per_token etc.)
    using depends_on + formula columns from query_registry.
    Iterates up to 5 passes to handle chained dependencies.
    Returns flat dict of {metric_id: float_value}.
    """
    import json as _json
    from metric_engine import _safe_eval
    computed = {}

    try:
        with get_conn() as db:
            rows = [dict(r) for r in db.execute("""
                SELECT id, depends_on, formula
                FROM query_registry
                WHERE metric_type = 'computed'
                  AND active = 1
                  AND depends_on IS NOT NULL
                  AND formula IS NOT NULL
            """).fetchall()]

        # Iterative resolution handles chained deps
        for _ in range(5):
            changed = False
            for row in rows:
                if row["id"] in computed:
                    continue
                try:
                    deps = _json.loads(row["depends_on"])
                    ctx  = {}
                    ok   = True
                    for d in deps:
                        v = base.get(d) if base.get(d) is not None else computed.get(d)
                        if v is None:
                            ok = False
                            break
                        ctx[d] = float(v)
                    if ok:
                        computed[row["id"]] = _safe_eval(row["formula"], ctx)
                        changed = True
                except Exception as e:
                    logger.warning(f"  compute {row['id']}: {e}")
            if not changed:
                break

    except Exception as e:
        logger.warning(f"_compute_derived_from_db failed: {e}")

    return computed


def register_all_from_db(app: FastAPI, get_conn) -> int:
    """
    Register all active sql_* queries as GET endpoints.
    get_conn: callable returning a DB connection (_conn from server.py).
    Returns count of NEWLY registered endpoints.
    Skips computed/sql_column types — not endpoints.
    Skips already-registered paths — safe to call multiple times.
    """
    with get_conn() as db:
        rows = db.execute("""
            SELECT id, name, description, metric_type,
                   sql_text, sql_file, returns,
                   endpoint_path, group_name, parameters,
                   enrich_metrics, cache_ttl_sec
            FROM query_registry
            WHERE active = 1
              AND metric_type IN ('sql_aggregate', 'sql_rows', 'timeseries')
              AND endpoint_path IS NOT NULL
        """).fetchall()
        rows = [dict(r) for r in rows]

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
            path        = path,
            endpoint    = handler,
            methods     = ["GET"],
            tags        = [row.get("group_name", "analytics")],
            summary     = row.get("name", row["id"]),
            description = row.get("description", ""),
        )
        logger.info(f"  ✓ registered: GET {path}")
        registered += 1

    return registered


def _validate_registry(rows: list) -> None:
    """
    Validate all rows before registering endpoints.
    Fails loud — never silently serve broken endpoints.
    """
    for row in rows:
        has_sql_text = bool((row.get("sql_text") or "").strip())
        has_sql_file = bool(row.get("sql_file"))

        if not has_sql_text and not has_sql_file:
            raise ValueError(
                f"\nquery_registry validation FAILED:\n"
                f"  id:   {row['id']}\n"
                f"  path: {row['endpoint_path']}\n"
                f"  Both sql_text and sql_file are NULL.\n"
                f"  Fix: add sql_text in Directus → http://localhost:8055\n"
            )

        if has_sql_file and not has_sql_text:
            sql_path = (
                Path(os.getenv("ALEMS_BASE", ".")) / "queries" / row["sql_file"]
            )
            if not sql_path.exists():
                raise FileNotFoundError(
                    f"query_registry[{row['id']}]: sql_file not found: {sql_path}"
                )


def _resolve_sql(row: dict) -> str:
    """
    Resolve SQL from registry row.
    Priority: sql_text_pg (PG mode) → sql_text → sql_file (legacy).
    """
    is_pg = bool(os.getenv("ALEMS_DB_URL", ""))

    if is_pg and (row.get("sql_text_pg") or "").strip():
        return row["sql_text_pg"]

    if (row.get("sql_text") or "").strip():
        return row["sql_text"]

    if row.get("sql_file"):
        base = Path(os.getenv("ALEMS_BASE", ".")) / "queries"
        if is_pg:
            pg_path = base / row["sql_file"].replace(".sql", ".pg.sql")
            if pg_path.exists():
                return pg_path.read_text()
        return (base / row["sql_file"]).read_text()

    raise ValueError(f"No SQL source for: {row['id']}")


def _make_handler(row: dict, get_conn):
    """
    Build async handler for one query_registry row.
    Detects URL params from parameters JSON: limit, exp_id, run_id.
    When enrich_metrics=1 + returns=single_row merges computed metrics.
    """
    qid     = row["id"]
    enrich  = bool(row.get("enrich_metrics", 0))
    returns = row.get("returns", "rows")
    params  = json.loads(row.get("parameters") or "{}")
    sql     = _resolve_sql(row)

    has_limit  = "limit"  in params
    has_exp_id = "exp_id" in params
    has_run_id = "run_id" in params

    def _exec(query_params: dict) -> list:
        """Execute SQL with named params, return list of dicts."""
        import re
        is_pg = bool(os.getenv("ALEMS_DB_URL", ""))
        with get_conn() as db:
            adapted = re.sub(r':(\w+)', r'%(\1)s', sql) if is_pg else sql
            cur = db.cursor()
            cur.execute(adapted, query_params)
            return [dict(r) for r in cur.fetchall()]

    if has_limit:
        default_limit = (
            params["limit"].get("default", 50)
            if isinstance(params["limit"], dict) else 50
        )
        async def handler(limit: int = default_limit):
            rows = _exec({"limit": limit})
            if enrich and returns == "single_row":
                base = rows[0] if rows else {}
                return {**base, **_compute_derived_from_db(base, get_conn)}
            return rows[0] if returns == "single_row" and rows else rows

    elif has_exp_id:
        async def handler(exp_id: int):
            return _exec({"exp_id": exp_id})

    elif has_run_id:
        async def handler(run_id: int):
            return _exec({"run_id": run_id})

    else:
        async def handler():
            rows = _exec({})
            if enrich and returns == "single_row":
                # Merge tax_multiple, energy_per_token_uj, ooi_time into response
                base = rows[0] if rows else {}
                return {**base, **_compute_derived_from_db(base, get_conn)}
            return rows[0] if returns == "single_row" and rows else rows

    handler.__name__ = f"get_{qid}"
    return handler
