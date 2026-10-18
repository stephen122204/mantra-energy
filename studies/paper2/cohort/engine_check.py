"""Checks run against a freshly started server before any measured step (not measured themselves).

1. forced decoding: a request with ``vllm_xargs.forced_tokens`` returns exactly those ids;
2. batching: two concurrent requests are both running in the engine at the same time
   (``vllm:num_requests_running`` >= 2 observed while they are in flight);
3. prefix cache: the same long prompt sent twice reports cached prompt tokens the second time;
4. agent request: the exact streaming body agent sessions send (``client.completion_request``, sampled
   decoding) returns tokens and a finish reason, with no error event;
5. long context: a ~1300-token passage with one fact, greedy, must answer it. Catches silent model-config
   misreads (e.g. vLLM 0.10.2 under transformers 5 drops rope_theta and positions degrade with length).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from urllib.parse import urlparse

from .client import completion_request, stream_completion
from .forcing import encode_forced
from .telemetry import fetch_metrics, parse_prometheus


def _post(base_url: str, payload: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(f"{base_url}/v1/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


LONG_PASSAGE = ("The city library opened a new reading room this spring. Volunteers sorted donated books by subject, "
                "repaired worn covers, and built shelves along the east wall. Children's story hours now run on Saturday "
                "mornings, and a small cafe serves tea near the entrance. ")


def long_context_check(base_url: str, model: str, reps: int = 25) -> dict:
    q = LONG_PASSAGE * reps + "\n\nQuestion: on which day do the children's story hours run? Answer in one short sentence."
    req = urllib.request.Request(f"{base_url}/v1/chat/completions", headers={"Content-Type": "application/json"},
                                 data=json.dumps(dict(model=model, messages=[{"role": "user", "content": q}],
                                                      temperature=0.0, max_tokens=40)).encode())
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read())
    answer = out["choices"][0]["message"]["content"] or ""
    return dict(ok="saturday" in answer.lower(), prompt_tokens=out["usage"]["prompt_tokens"], answer=answer[:120])


def run_checks(base_url: str, model: str, prompt_ids: list, forced_ids: list, sampling: dict = None) -> dict:
    out: dict = {}
    try:
        out["long_context"] = long_context_check(base_url, model)
    except Exception as exc:
        out["long_context"] = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
    sampling = sampling or dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0)
    try:
        u = urlparse(base_url)
        _, ids, finish, usage, _ = stream_completion(u.hostname, u.port, completion_request(model, prompt_ids, 32, sampling), 600)
        out["agent_request"] = dict(ok=bool(ids) and finish in ("stop", "length"), tokens=len(ids), finish=finish,
                                    completion_tokens=usage.get("completion_tokens"))
    except Exception as exc:
        out["agent_request"] = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
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
    from .guards import cache_probe
    first = cache_probe(base_url, model, long_prompt)
    second = cache_probe(base_url, model, long_prompt, expected="warm") if first["ok"] else None
    out["prefix_cache"] = dict(ok=bool(first["ok"] and second and second["ok"]),
                               priming=first, warm=second,
                               cached_tokens=second.get("delta_h") if second else None,
                               first_cached=first.get("cached_tokens"))
    out["ok"] = all(v.get("ok") for v in out.values() if isinstance(v, dict))
    return out
