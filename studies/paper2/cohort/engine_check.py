"""Checks run against a freshly started server before any measured step (not measured themselves).

1. forced decoding: a request with ``vllm_xargs.forced_tokens`` returns exactly those ids;
2. batching: two concurrent requests are both running in the engine at the same time
   (``vllm:num_requests_running`` >= 2 observed while they are in flight);
3. prefix cache: the same long prompt sent twice reports cached prompt tokens the second time.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from .forcing import encode_forced
from .telemetry import fetch_metrics, parse_prometheus


def _post(base_url: str, payload: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(f"{base_url}/v1/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_checks(base_url: str, model: str, prompt_ids: list, forced_ids: list) -> dict:
    out: dict = {}
    try:
        r = _post(base_url, dict(model=model, prompt=prompt_ids, max_tokens=len(forced_ids), temperature=0.0,
                                 ignore_eos=True, return_token_ids=True, vllm_xargs=dict(forced_tokens=encode_forced(forced_ids))))
        got = r["choices"][0].get("token_ids")
        out["forced_decoding"] = dict(ok=got == forced_ids, n=len(forced_ids), got_head=(got or [])[:8])
    except Exception as exc:
        out["forced_decoding"] = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
    peak = [0.0]
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            try:
                peak[0] = max(peak[0], parse_prometheus(fetch_metrics(base_url)).get("vllm:num_requests_running", 0))
            except Exception:
                pass
            time.sleep(0.05)
    w = threading.Thread(target=watch, daemon=True)
    w.start()
    body = dict(model=model, prompt=prompt_ids, max_tokens=256, temperature=0.0, ignore_eos=True)
    ts = [threading.Thread(target=_post, args=(base_url, body)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    stop.set()
    w.join()
    out["batching"] = dict(ok=peak[0] >= 2, peak_running=peak[0])
    long_prompt = (prompt_ids * max(1, 2048 // max(1, len(prompt_ids))))[:2048]
    first = _post(base_url, dict(model=model, prompt=long_prompt, max_tokens=1, temperature=0.0))
    second = _post(base_url, dict(model=model, prompt=long_prompt, max_tokens=1, temperature=0.0))
    cached = ((second.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens")
    out["prefix_cache"] = dict(ok=bool(cached and cached >= 1024), cached_tokens=cached,
                               first_cached=((first.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens"))
    out["ok"] = all(v.get("ok") for v in out.values() if isinstance(v, dict))
    return out
