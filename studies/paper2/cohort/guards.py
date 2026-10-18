"""Cohort boundary guards: verified cold prefix cache, server drain before an interval closes, and
removal of task containers left behind by forcibly terminated sessions.

- ``verified_cache_reset``: vLLM's ``POST /reset_prefix_cache`` (needs VLLM_SERVER_DEV_MODE=1) does
  not report success, so a probe prompt is sent twice (the second must hit the cache), the cache is
  reset, and the probe must then report zero cached tokens; the cache is reset once more so the probe
  itself leaves nothing behind. The probe starts with a different token after BOS than every agent
  prompt (no system prompt), so it shares no full cache block with task prompts.
- ``wait_drained``: polls /metrics until no request is running or waiting, so engine work started by
  a session that has already been stopped is still inside the measured interval.
- ``leftover_containers``: lists (and removes) containers with the session prefix; run after the
  interval so a container cannot carry work into the next cohort.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
import urllib.request

from .telemetry import fetch_metrics, parse_prometheus

PROBE_TEXT = ("Cache probe. " + " ".join(f"item{i}" for i in range(120)))


def _post(base_url: str, path: str, body=None, timeout: float = 120):
    req = urllib.request.Request(f"{base_url}{path}", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else b"")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


COUNTER_TIMEOUT_S = 10.0
CACHE_BLOCK_SIZE = 16  # pinned vLLM configuration; do not infer this from usage omission
CACHE_COUNTERS = ("vllm:prefix_cache_queries_total", "vllm:prefix_cache_hits_total")


def _cache_counters(base_url):
    metrics = parse_prometheus(fetch_metrics(base_url))
    values = {k: metrics.get(k) for k in CACHE_COUNTERS}
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0
           for v in values.values()):
        raise ValueError("missing or invalid prefix-cache counters")
    return values


def cache_probe(base_url: str, model: str, probe_ids: list, *, expected=None) -> dict:
    """Prove an isolated lookup from cumulative counters, including servers omitting zero usage.

    No other client may submit during the probe. A drained boundary plus an observed query
    increment is required; missing usage alone never establishes a cold cache. Metrics may
    lag responses, so wait boundedly for this lookup's query count to become visible.
    """
    rec = dict(ok=False, probe_tokens=len(probe_ids), full_block_tokens=len(probe_ids)//CACHE_BLOCK_SIZE*CACHE_BLOCK_SIZE,
               cached_tokens=None, before=None, after=None, delta_q=None, delta_h=None)
    try:
        if rec["full_block_tokens"] < CACHE_BLOCK_SIZE:
            raise ValueError("cache probe must contain at least one full block")
        rec["drain_before"] = wait_drained(base_url)
        if rec["drain_before"].get("drained") is not True:
            raise ValueError("server not drained before cache probe")
        before = rec["before"] = _cache_counters(base_url)
        status, response = _post(base_url, "/v1/completions", dict(model=model, prompt=probe_ids, max_tokens=1, temperature=0.0))
        if status != 200:
            raise ValueError("cache probe request failed")
        usage = ((response or {}).get("usage") or {}).get("prompt_tokens_details") or {}
        cached = rec["cached_tokens"] = usage.get("cached_tokens")
        if "cached_tokens" in usage and (not isinstance(cached, (int, float)) or isinstance(cached, bool)
                                  or not math.isfinite(cached) or cached < 0):
            raise ValueError("invalid cached-token usage")
        rec["drain_after"] = wait_drained(base_url)
        if rec["drain_after"].get("drained") is not True:
            raise ValueError("server not drained after cache probe")
        deadline = time.monotonic() + COUNTER_TIMEOUT_S
        previous = before
        while True:
            after = rec["after"] = _cache_counters(base_url)
            if any(after[k] < previous[k] for k in CACHE_COUNTERS):
                raise ValueError("prefix-cache counter decreased")
            previous = after
            dq, dh = (after[k] - before[k] for k in CACHE_COUNTERS)
            rec.update(delta_q=dq, delta_h=dh)
            if dq >= rec["full_block_tokens"]:
                break
            if time.monotonic() >= deadline:
                raise ValueError("prefix-cache counters did not prove the lookup")
            time.sleep(0.1)
        if dh > dq:
            raise ValueError("cache hits exceed cache queries")
        if cached is not None and cached != dh:
            raise ValueError("cached-token usage disagrees with counter delta")
        if expected == "warm" and dh < CACHE_BLOCK_SIZE:
            raise ValueError("warm probe did not reuse a full cache block")
        if expected == "cold" and dh != 0:
            raise ValueError("cold probe reused cached tokens")
        rec["ok"] = True
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def verified_cache_reset(base_url: str, model: str, probe_ids: list) -> dict:
    rec = dict(ok=False, probe_tokens=len(probe_ids), probes={})
    try:
        for name, expected in (("priming", None), ("warm", "warm"), ("cold", "cold")):
            if name == "cold":
                status, _ = _post(base_url, "/reset_prefix_cache")
                rec["reset_status"] = status
                if status != 200:
                    raise ValueError("first cache reset failed")
            probe = rec["probes"][name] = cache_probe(base_url, model, probe_ids, expected=expected)
            if not probe["ok"]:
                raise ValueError(f"{name}: {probe.get('error')}")
        status, _ = _post(base_url, "/reset_prefix_cache")
        rec["final_reset_status"] = status
        if status != 200:
            raise ValueError("final cache reset failed")
        rec.update(ok=True, cached_before_reset=rec["probes"]["warm"]["delta_h"],
                   cached_after_reset=rec["probes"]["cold"]["delta_h"])
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def wait_drained(base_url: str, timeout_s: float = 120.0, poll_s: float = 0.25) -> dict:
    t0 = time.monotonic()
    last = {}
    while True:
        try:
            m = parse_prometheus(fetch_metrics(base_url))
            last = {k: m.get(k) for k in ("vllm:num_requests_running", "vllm:num_requests_waiting")}
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v == 0
                   for v in last.values()):
                return dict(drained=True, drain_s=round(time.monotonic() - t0, 3), last=last)
        except Exception as exc:
            last = dict(error=f"{type(exc).__name__}: {exc}")
        if time.monotonic() - t0 > timeout_s:
            return dict(drained=False, drain_s=round(time.monotonic() - t0, 3), last=last)
        time.sleep(poll_s)


def leftover_containers(docker: str = "docker", prefix: str = "p2-", remove: bool = True) -> dict:
    try:
        p = subprocess.run([docker, "ps", "-aq", "--filter", f"name=^{prefix}"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(checked=False, error=f"{type(exc).__name__}: {exc}")
    ids = p.stdout.split()
    removed = []
    if remove and ids:
        r = subprocess.run([docker, "rm", "-f", *ids], capture_output=True, text=True, timeout=300)
        removed = r.stdout.split()
    return dict(checked=p.returncode == 0, leftover=ids, removed=removed)


def require_clean_boundary(summary: dict) -> None:
    """Do not carry unfinished server or tool work into another measured cell."""
    if (summary.get("drain") or {}).get("drained") is not True:
        raise RuntimeError("server drain was not established; stopping before another measurement")
    cleanup = summary.get("container_cleanup")
    if cleanup is not None and (not cleanup.get("checked") or cleanup.get("leftover")):
        raise RuntimeError("task container boundary was not clean; stopping before another measurement")
