# alems-platform/sync.py
# =============================================================
# TWO-DIRECTION SYNC
#   DOWN: Central PG (Oracle VM) → Local SQLite (metadata only)
#   UP:   Local SQLite → Central PG (run data only, after each run)
#
# Called:
#   FastAPI startup           → sync_metadata_down()
#   After run completes       → push_run_to_central(run_id)
#   POST /internal/reload     → sync_metadata_down()
#   After SQLite write        → broadcast_run_complete(run_id, _subscribers)
#
# Standalone mode: CENTRAL_API_URL not set → no network, no errors
# =============================================================

import os
import json
import logging
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# --- Config from environment -------------------------------------------
CENTRAL_API_URL = os.getenv("CENTRAL_API_URL", "")   # http://oracle-vm:8765
INTERNAL_TOKEN  = os.getenv("INTERNAL_TOKEN",  "")   # shared secret
DB_PATH         = os.getenv("ALEMS_DB_PATH", "data/experiments.db")

# --- Tables synced DOWN: central metadata → local (central wins) -------
METADATA_TABLES = [
    "metric_display_registry",
    "query_registry",
    "standardization_registry",
    "component_registry",
    "page_configs",
    "page_sections",
    "page_metric_configs",
    "eval_criteria",
    "measurement_method_registry",
]

# --- Tables pushed UP: local run data → central (local wins) -----------
DATA_TABLES = [
    "runs",
    "experiments",
    "measurement_methodology",
    "audit_log",
    "orchestration_events",
    "orchestration_tax_summary",
    "llm_interactions",
    "energy_samples",
]


@contextmanager
def _local_db():
    """Open local SQLite in write mode."""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


# ── Metadata sync: Central PG → Local SQLite --------------------------

async def sync_metadata_down() -> dict:
    """
    Pull metadata from Central API into local SQLite.
    Uses INSERT OR REPLACE — central always wins for metadata.
    Returns {table: row_count} summary, or {} in standalone mode.
    """
    if not CENTRAL_API_URL:
        # Standalone mode — fully offline, no errors
        logger.info("sync_metadata_down: standalone mode (CENTRAL_API_URL not set)")
        return {}

    try:
        import httpx
    except ImportError:
        logger.warning("sync_metadata_down: httpx not installed — pip install httpx")
        return {}

    summary = {}
    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}

    async with httpx.AsyncClient(timeout=30) as client:
        for table in METADATA_TABLES:
            try:
                r = await client.get(
                    f"{CENTRAL_API_URL}/internal/metadata/{table}",
                    headers=headers
                )
                r.raise_for_status()
                rows = r.json()

                if rows:
                    with _local_db() as db:
                        _upsert_rows(db, table, rows)
                        db.commit()
                    summary[table] = len(rows)
                    logger.info(f"  ✓ {table}: {len(rows)} rows synced")
                else:
                    summary[table] = 0

            except Exception as e:
                # Log but don't crash — local data still works
                logger.warning(f"  ✗ sync {table} failed: {e}")
                summary[table] = -1

    return summary


def _upsert_rows(db, table: str, rows: list) -> None:
    """
    Upsert rows into local SQLite via INSERT OR REPLACE.
    Serializes dicts/lists → JSON string for SQLite TEXT columns.
    """
    if not rows:
        return

    cols         = list(rows[0].keys())
    col_list     = ", ".join(cols)
    placeholders = ", ".join(["?" for _ in cols])

    for row in rows:
        values = [
            json.dumps(v) if isinstance(v, (dict, list)) else v
            for v in (row[c] for c in cols)
        ]
        db.execute(
            f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
            values
        )


# ── Run data sync: Local SQLite → Central PG --------------------------

async def push_run_to_central(run_id: int) -> bool:
    """
    Push one completed run and all related rows to Central PG.
    Called AFTER run is written to SQLite — not during measurement.
    Returns True on success. False = logged failure, local data safe.
    """
    if not CENTRAL_API_URL:
        return True   # Standalone mode — nothing to push

    try:
        import httpx
    except ImportError:
        logger.warning("push_run_to_central: httpx not installed")
        return False

    payload = {}

    with _local_db() as db:
        for table in DATA_TABLES:
            try:
                # Check if this table has a run_id column
                cols = [r[1] for r in db.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()]

                if "run_id" in cols:
                    rows = [dict(r) for r in db.execute(
                        f"SELECT * FROM {table} WHERE run_id = ?", (run_id,)
                    ).fetchall()]
                    if rows:
                        payload[table] = rows

                elif table == "experiments":
                    # experiments links via exp_id, not run_id
                    run = db.execute(
                        "SELECT exp_id FROM runs WHERE run_id = ?", (run_id,)
                    ).fetchone()
                    if run:
                        rows = [dict(r) for r in db.execute(
                            "SELECT * FROM experiments WHERE exp_id = ?",
                            (run["exp_id"],)
                        ).fetchall()]
                        if rows:
                            payload[table] = rows

            except Exception as e:
                logger.warning(f"  collect {table} for run {run_id}: {e}")

    if not payload:
        logger.warning(f"push_run_to_central: no data for run_id={run_id}")
        return False

    headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{CENTRAL_API_URL}/sync/push-run",
                json={"run_id": run_id, "tables": payload},
                headers=headers
            )
            r.raise_for_status()
            logger.info(f"  ✓ pushed run {run_id} to central")
            return True
    except Exception as e:
        # Local data is safe — push can be retried
        logger.error(f"  ✗ push run {run_id} failed: {e}")
        return False


# ── SSE broadcast: notify all connected browser clients ---------------

async def broadcast_run_complete(run_id: int, subscribers: dict) -> None:
    """
    Push run_complete event to all SSE subscribers.
    Called after run is written to SQLite.
    subscribers: the _subscribers dict from server.py.
    Frontend invalidates TanStack Query cache on receipt.
    """
    if not subscribers:
        return

    # Read run summary for the broadcast payload
    with _local_db() as db:
        run = db.execute("""
            SELECT r.run_id, r.workflow_type,
                   ROUND(r.pkg_energy_uj / 1e6, 3) AS energy_j,
                   r.experiment_valid,
                   e.task_name, e.model_name
            FROM runs r
            JOIN experiments e ON e.exp_id = r.exp_id
            WHERE r.run_id = ?
        """, (run_id,)).fetchone()

    if not run:
        logger.warning(f"broadcast_run_complete: run_id={run_id} not found")
        return

    run = dict(run)
    payload = json.dumps({
        "event":    "run_complete",
        "run_id":   run_id,
        "energy_j": run.get("energy_j"),
        "workflow": run.get("workflow_type"),
        "task":     run.get("task_name"),
        "model":    run.get("model_name"),
        "valid":    bool(run.get("experiment_valid")),
    })

    # Push to all connected SSE clients, clean up dead ones
    dead = []
    for cid, q in subscribers.items():
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(cid)   # Queue full or client disconnected

    for cid in dead:
        subscribers.pop(cid, None)

    logger.info(
        f"  ✓ broadcast run_complete run_id={run_id} "
        f"to {len(subscribers)} clients"
    )
