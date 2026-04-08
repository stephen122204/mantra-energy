# metric_engine.py v2
# Fixes: lru_cache, per-request memo, param validation,
#        cycle detection, SELECT-only, standardized output, explicit errors.

import ast
import operator
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.USub: operator.neg,
}

def _safe_eval(expr: str, context: Dict[str, float]) -> float:
    tree = ast.parse(expr, mode="eval")
    def _eval(node):
        if isinstance(node, ast.Expression): return _eval(node.body)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)): raise ValueError(f"Non-numeric: {node.value}")
            return float(node.value)
        elif isinstance(node, ast.Name):
            if node.id not in context: raise ValueError(f"Unknown variable: '{node.id}'")
            return float(context[node.id])
        elif isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op: raise ValueError(f"Unsupported op: {type(node.op).__name__}")
            l, r = _eval(node.left), _eval(node.right)
            return 0.0 if op == operator.truediv and r == 0 else op(l, r)
        elif isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op: raise ValueError(f"Unsupported unary: {type(node.op).__name__}")
            return op(_eval(node.operand))
        raise ValueError(f"Unsupported node: {type(node).__name__}")
    return _eval(tree)

# ── Registry — cached, one I/O per process ────────────────────────────────────
@lru_cache(maxsize=1)
def _load_registry_cached(path: str) -> Dict[str, dict]:
    p = Path(path)
    if not p.exists(): return {}
    with open(p) as f: data = yaml.safe_load(f) or {}
    return {m["id"]: m for m in data.get("metrics", [])}

def load_metric_registry(path: Path) -> Dict[str, dict]:
    return _load_registry_cached(str(path))

def invalidate_registry_cache() -> None:
    _load_registry_cached.cache_clear()

# ── Helpers ───────────────────────────────────────────────────────────────────
def _validate_params(metric: dict, params: dict) -> None:
    for r in metric.get("required_params", []):
        if r not in params:
            raise ValueError(f"Metric '{metric['id']}' requires param '{r}'")

def _validate_sql(sql: str, mid: str) -> None:
    if not sql.strip().lower().startswith("select"):
        raise ValueError(f"Metric '{mid}': only SELECT allowed")

def _meta(m: dict) -> dict:
    return {k: m.get(k,"") for k in ["unit","type","provenance","description","formula_latex","significance","layer"]}

def _ok(mid, m, value, data, extra={}):
    return {"metric_id": mid, "value": value, "data": data, "meta": _meta(m), **extra}

def _err(mid, m, error):
    return {"metric_id": mid, "value": None, "data": [], "meta": _meta(m), "error": error}

# ── Core ──────────────────────────────────────────────────────────────────────
def compute_metric(metric_id, params, registry, q_fn, q1_fn, visited=None, cache=None):
    if visited is None: visited = set()
    if cache   is None: cache   = {}

    ckey = f"{metric_id}:{sorted(params.items())}"
    if ckey in cache: return cache[ckey]

    if metric_id in visited:
        raise ValueError(f"Circular dependency: '{metric_id}'")
    visited = visited | {metric_id}

    m = registry.get(metric_id)
    if not m: raise KeyError(f"Metric '{metric_id}' not in registry")

    try: _validate_params(m, params)
    except ValueError as e:
        r = _err(metric_id, m, str(e)); cache[ckey] = r; return r

    # SQL metric
    if "sql" in m:
        sql = m["sql"].strip()
        try: _validate_sql(sql, metric_id)
        except ValueError as e:
            r = _err(metric_id, m, str(e)); cache[ckey] = r; return r
        needed = set(re.findall(r':(\w+)', sql))
        safe_p = {**{p: None for p in needed}, **params}
        try: rows = q_fn(sql, safe_p)
        except Exception as e:
            r = _err(metric_id, m, f"SQL error: {e}"); cache[ckey] = r; return r
        value = None
        if rows and "value" in rows[0] and rows[0]["value"] is not None:
            try: value = float(rows[0]["value"])
            except (TypeError, ValueError): pass
        r = _ok(metric_id, m, value, rows); cache[ckey] = r; return r

    # Derived metric
    if "depends_on" in m and "formula" in m:
        ctx, dep_vals, errs = {}, {}, []
        for did in m["depends_on"]:
            try:
                dep = compute_metric(did, params, registry, q_fn, q1_fn, visited, cache)
                if "error" in dep: errs.append(f"{did}: {dep['error']}"); continue
                if dep.get("value") is None: errs.append(f"{did}: None"); continue
                ctx[did] = dep["value"]; dep_vals[did] = dep["value"]
            except Exception as e: errs.append(f"{did}: {e}")
        if errs:
            r = _err(metric_id, m, f"Dep errors: {'; '.join(errs)}"); cache[ckey] = r; return r
        try: value = _safe_eval(m["formula"], ctx)
        except Exception as e:
            r = _err(metric_id, m, f"Formula error: {e}"); cache[ckey] = r; return r
        r = _ok(metric_id, m, value, [{"value": value}], {"dependencies": dep_vals})
        cache[ckey] = r; return r

    r = _err(metric_id, m, "Needs 'sql' or 'depends_on'+'formula'")
    cache[ckey] = r; return r

def compute_batch(metric_ids, params, registry, q_fn, q1_fn,
                  filter_significance=None, filter_layer=None):
    """Compute multiple metrics sharing one cache. Explicit error per metric."""
    cache, results = {}, {}
    ids = metric_ids or list(registry.keys())
    for mid in ids:
        m = registry.get(mid, {})
        if filter_significance and m.get("significance") != filter_significance: continue
        if filter_layer and m.get("layer") != filter_layer: continue
        try:
            results[mid] = compute_metric(mid, params, registry, q_fn, q1_fn, None, cache)
        except Exception as e:
            results[mid] = _err(mid, m, str(e))
    return results
