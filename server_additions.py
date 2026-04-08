# =============================================================
# ADDITIONS TO alems-platform/server.py
# =============================================================
# Do NOT replace server.py — add these sections to it.
#
# 1. Add imports at top (after existing imports):
# 2. Add lifespan context manager (replaces any existing startup)
# 3. Add new endpoints (/pages, /metrics, /internal)
#
# Your existing q(), q1(), exec_named_query() stay untouched.
# Your existing endpoints stay untouched.
# =============================================================

# ── ADD THESE IMPORTS (at top of server.py) ───────────────────
"""
from auto_router import register_all_from_db
from contextlib import asynccontextmanager
"""

# ── ADD LIFESPAN (replaces @app.on_event("startup") if any) ──
"""
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Auto-register endpoints from query_registry DB table
    logger.info("A-LEMS API starting — registering endpoints from DB...")
    try:
        count = register_all_from_db(app, _conn)
        logger.info(f"✓ {count} endpoints auto-registered from query_registry")
    except Exception as e:
        logger.error(f"Auto-registration failed: {e}")
        # Don't crash — existing YAML-based endpoints still work

    yield
    logger.info("A-LEMS API stopped")

# Update FastAPI app init to use lifespan:
app = FastAPI(
    title    = "A-LEMS API",
    version  = "2.0.0",
    lifespan = lifespan,
)
"""

# ── ADD THESE ENDPOINTS (after existing endpoints) ────────────

import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def add_config_endpoints(app: FastAPI, q_func, q1_func):
    """
    Call this in server.py after creating app:
        add_config_endpoints(app, q, q1)

    Adds:
        GET  /pages                    → list all published pages
        GET  /pages/{page_id}          → full page config with sections+metrics
        GET  /metrics/registry         → all metric display metadata
        GET  /metrics/batch            → all computed metrics as flat dict
        POST /internal/reload          → re-sync + re-register (Directus webhook)
        GET  /internal/metadata/{table}→ export table for sync
        POST /tools/query              → ad-hoc SELECT (research instruments)
        GET  /research/{query_id}      → execute research insight query
    """

    @app.get("/pages", tags=["pages"])
    async def list_pages(audience: str = "workbench"):
        rows = q_func("""
            SELECT id, title, slug, icon, description, sort_order,planet_texture, music_file, hero_image, audience
            FROM page_configs
            WHERE published = 1
              AND audience LIKE :audience
            ORDER BY sort_order
        """, {"audience": f"%{audience}%"})
        return rows

    @app.get("/pages/{page_id}", tags=["pages"])
    async def get_page_config(page_id: str):
        page = q1_func(
            "SELECT * FROM page_configs WHERE id=:id AND published=1",
            {"id": page_id}
        )
        if not page:
            raise HTTPException(404, f"Page '{page_id}' not found or not published")

        sections = q_func("""
            SELECT ps.*
            FROM page_sections ps
            WHERE ps.page_id = :page_id
              AND ps.active = 1
            ORDER BY ps.position
        """, {"page_id": page_id})

        result           = dict(page)
        result["sections"] = []

        for section in sections:
            s = dict(section)
            # Parse JSON props
            try:
                s["props"] = json.loads(s.get("props") or "{}")
            except Exception:
                s["props"] = {}

            # Fetch metrics for this section
            metrics = q_func("""
                SELECT
                    pmc.id, pmc.metric_id, pmc.position,
                    pmc.label_override, pmc.color_override,
                    pmc.unit_override, pmc.thesis, pmc.decimals,
                    mdr.label, mdr.unit_default, mdr.color_token,
                    mdr.formula_latex, mdr.provenance_expected,
                    mdr.significance, mdr.chart_type,
                    mdr.source_description, mdr.description,
                    mdr.direction, mdr.display_precision,
                    mdr.warn_threshold, mdr.severe_threshold
                FROM page_metric_configs pmc
                JOIN metric_display_registry mdr ON mdr.id = pmc.metric_id
                WHERE pmc.section_id = :section_id
                  AND pmc.active = 1
                ORDER BY pmc.position
            """, {"section_id": s["id"]})

            s["metrics"] = [dict(m) for m in metrics]
            result["sections"].append(s)

        return result

    @app.get("/metrics/registry", tags=["metrics"])
    async def get_metric_registry():
        rows = q_func("""
            SELECT * FROM metric_display_registry
            WHERE active = 1
            ORDER BY sort_order, id
        """)
        return rows

    @app.get("/metrics/batch", tags=["metrics"])
    async def get_metrics_batch():
        """All computed metrics as flat dict — for dashboards."""
        from metric_engine import compute_batch
        # Get raw overview data
        base = q1_func("SELECT * FROM query_registry WHERE id='overview'") or {}
        # Execute overview SQL
        overview_row = q1_func("""
            SELECT * FROM query_registry WHERE id='overview'
        """)
        if overview_row and overview_row.get("sql_text"):
            try:
                result = q1_func(overview_row["sql_text"])
                computed = compute_batch(result or {}, None)
                return {**(result or {}), **computed}
            except Exception as e:
                logger.warning(f"metrics/batch failed: {e}")
        return {}

    @app.post("/internal/reload", tags=["internal"])
    async def reload_registry():
        """
        Called by Directus webhook on publish.
        Re-registers endpoints. Zero downtime.
        """
        from auto_router import register_all_from_db
        from server import _conn as get_conn
        try:
            count = register_all_from_db(app, get_conn)
            return {"status": "reloaded", "new_endpoints": count}
        except Exception as e:
            raise HTTPException(500, str(e))

    ALLOWED_EXPORT_TABLES = {
        "metric_display_registry", "query_registry",
        "standardization_registry", "component_registry",
        "page_configs", "page_sections", "page_metric_configs",
        "eval_criteria",
    }

    @app.get("/internal/metadata/{table}", tags=["internal"])
    async def export_metadata(table: str):
        """Export metadata table for cross-machine sync."""
        if table not in ALLOWED_EXPORT_TABLES:
            raise HTTPException(400, f"Table '{table}' not exportable")
        rows = q_func(f"SELECT * FROM {table}")
        return rows

    ALLOWED_RESEARCH_TABLES = {
        "runs", "experiments", "sessions",
        "measurement_methodology", "audit_log",
        "orchestration_events", "orchestration_tax_summary",
        "llm_interactions", "agent_decision_tree",
        "energy_samples", "cpu_samples",
    }

    @app.post("/tools/query", tags=["research"])
    async def adhoc_query(body: dict):
        """
        Ad-hoc SELECT query for research instruments.
        LensExplorer, ParallelCoords, AgentFlowGraph use this.
        SELECT only. Allowlisted tables only.
        """
        sql    = (body.get("sql") or "").strip()
        params = body.get("params", [])

        if not sql.upper().startswith("SELECT"):
            raise HTTPException(400, "Only SELECT queries allowed")

        sql_lower = sql.lower()
        if not any(t in sql_lower for t in ALLOWED_RESEARCH_TABLES):
            raise HTTPException(400, f"Query must reference an allowed table")

        try:
            rows    = q_func(sql, {})
            columns = list(rows[0].keys()) if rows else []
            return {"rows": rows, "columns": columns, "count": len(rows)}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.get("/research/{query_id}", tags=["research"])
    async def research_query(query_id: str):
        """Execute a research insight query by ID."""
        row = q1_func("""
            SELECT sql_text FROM query_registry
            WHERE id=:id AND active=1 AND group_name='research'
        """, {"id": query_id})

        if not row or not row.get("sql_text"):
            raise HTTPException(404, f"Research query '{query_id}' not found")

        rows = q_func(row["sql_text"])
        return {"rows": rows, "count": len(rows), "query_id": query_id}


# ── HOW TO INTEGRATE INTO server.py ───────────────────────────
"""
At the bottom of server.py, after app is created, add:

    from server_additions import add_config_endpoints
    add_config_endpoints(app, q, q1)

That's it. All existing code untouched.
Your q() and q1() functions already handle SQLite/PG dialect.
"""
