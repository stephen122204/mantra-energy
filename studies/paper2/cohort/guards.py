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


def _cached(base_url: str, model: str, probe_ids: list) -> int:
    _, out = _post(base_url, "/v1/completions", dict(model=model, prompt=probe_ids, max_tokens=1, temperature=0.0))
    cached = ((out.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens")
    if not isinstance(cached, (int, float)) or isinstance(cached, bool) or not math.isfinite(cached) or cached < 0:
        raise ValueError("missing or invalid cached-token telemetry")
    return cached


def verified_cache_reset(base_url: str, model: str, probe_ids: list) -> dict:
    try:
        _cached(base_url, model, probe_ids)
        warm = _cached(base_url, model, probe_ids)
        status, _ = _post(base_url, "/reset_prefix_cache")
        cold = _cached(base_url, model, probe_ids)
        status2, _ = _post(base_url, "/reset_prefix_cache")
        ok = status == 200 and status2 == 200 and warm >= 16 and cold == 0
        return dict(ok=ok, probe_tokens=len(probe_ids), cached_before_reset=warm, cached_after_reset=cold)
    except Exception as exc:
        return dict(ok=False, error=f"{type(exc).__name__}: {exc}")


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
