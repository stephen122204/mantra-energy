"""Replay recorded live sessions against a (possibly different-precision) server.

Every cell of the crossed design is a replay, including source precision == executing precision.
A replayed session submits, turn by turn, the exact recorded prompt token ids, forces the exact
recorded output tokens (``forcing.ForcedTokens`` via ``vllm_xargs``), and then waits the recorded
agent-side gap (tool execution + harness time between the end of response k and the submit of
request k+1) before the next turn. The next turn always follows completion of the previous
replayed response, so dependencies hold even when replay runs slower or faster than live.
Tools are NOT executed: their time is emulated by the recorded delay (energy boundary label
``tools_emulated_by_delay``). Replay measures the serving cost of fixed work; it says nothing
about whether the executing precision would have produced that work or succeeded.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .forcing import encode_forced
from .records import EventLog, write_manifest


@dataclass
class ReplayTurn:
    prompt_ids: list
    output_ids: list
    gap_after_s: float     # recorded wait before the next turn (0 for the last turn)


@dataclass
class ReplaySession:
    source_session_id: str
    task_id: str
    turns: list = field(default_factory=list)


def load_live_session(session_dir: Path) -> ReplaySession:
    """Rebuild full prompts from the delta-encoded request log of a live session."""
    session_dir = Path(session_dir)
    recs = [json.loads(l) for l in (session_dir / "requests.jsonl").read_text().splitlines() if l.strip()]
    spec = json.loads((session_dir / "spec.json").read_text())
    prev: list = []
    full = []
    for r in recs:
        if "prompt_suffix_ids" not in r:
            continue  # failed before rendering: nothing was sent
        prompt = prev[: r["prefix_same_as_prev"]] + r["prompt_suffix_ids"]
        if len(prompt) != r["prompt_len"]:
            raise ValueError(f"{session_dir.name} turn {r['turn']}: prompt reconstruction length mismatch")
        prev = prompt
        if r.get("finish_reason") == "context_exhausted" or "output_ids" not in r:
            continue  # never reached the server
        full.append((r, prompt))
    turns = []
    for i, (r, prompt) in enumerate(full):
        gap = 0.0
        if i + 1 < len(full):
            gap = max(0.0, (full[i + 1][0]["t_submit_ns"] - r["t_done_ns"]) / 1e9)
        turns.append(ReplayTurn(prompt, list(r["output_ids"]), gap))
    return ReplaySession(spec["session_id"], spec["task_id"], turns)


class _Client:
    def __init__(self, base_url: str, served_model: str):
        self.u, self.model = urlparse(base_url), served_model

    def forced(self, prompt_ids, output_ids, timeout=1800):
        payload = dict(model=self.model, prompt=prompt_ids, max_tokens=len(output_ids), temperature=0.0,
                       ignore_eos=True, stream=True, stream_options=dict(include_usage=True), return_token_ids=True,
                       vllm_xargs=dict(forced_tokens=encode_forced(output_ids)))
        from .client import stream_completion
        t_submit = time.monotonic_ns()
        first, ids, _, usage, _ = stream_completion(self.u.hostname, self.u.port, payload, timeout)
        return dict(t_submit_ns=t_submit, t_first_ns=first, t_done_ns=time.monotonic_ns(), output_ids_match=ids == list(output_ids),
                    completion_tokens=len(ids), cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    prompt_tokens=usage.get("prompt_tokens"))


def run_replay(cohort_id: str, sessions: list, base_url: str, served_model: str, out_root: Path, *, admission_limit: int,
               measurement=None, poller=None, delay_scale: float = 1.0, labels: Optional[dict] = None,
               drain_timeout_s: float = 120.0) -> dict:
    """Closed-loop replay cohort; same admission semantics as the live fixed mode."""
    root = Path(out_root) / cohort_id
    root.mkdir(parents=True, exist_ok=False)
    events = EventLog(root / "events.jsonl")
    events.append("replay_start", cohort_id=cohort_id, n_sessions=len(sessions), admission_limit=admission_limit,
                  delay_scale=delay_scale, energy_boundary="tools_emulated_by_delay", labels=labels or {})
    client = _Client(base_url, served_model)
    sem = threading.Semaphore(admission_limit)
    results: dict = {}
    lock = threading.Lock()

    def worker(rs: ReplaySession):
        with sem:
            out = dict(source_session_id=rs.source_session_id, task_id=rs.task_id, turns=[], error=None)
            events.append("replay_admitted", source_session_id=rs.source_session_id)
            try:
                for k, t in enumerate(rs.turns):
                    res = client.forced(t.prompt_ids, t.output_ids)
                    res["turn"] = k
                    out["turns"].append(res)
                    if t.gap_after_s > 0:
                        time.sleep(t.gap_after_s * delay_scale)
            except Exception as exc:
                out["error"] = f"{type(exc).__name__}: {exc}"
            events.append("replay_terminal", source_session_id=rs.source_session_id,
                          outcome="replayed" if not out["error"] else "infra_failed", error=out["error"],
                          mismatched_turns=sum(1 for r in out["turns"] if not r["output_ids_match"]))
            with lock:
                results[rs.source_session_id] = out

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in sessions]
    if poller:
        poller.start()
    if measurement:
        measurement.start_goal()
    t0 = time.monotonic()
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    finally:
        from .guards import wait_drained
        drain = wait_drained(base_url, timeout_s=drain_timeout_s)
        events.append("drained", **drain)
        t1 = time.monotonic()
        artifacts = measurement.finish_goal() if measurement else None
        if poller:
            poller.stop()
    energy = None
    if artifacts is not None:
        from .energy import cohort_energy_summary
        energy = cohort_energy_summary(artifacts)
        (root / "measurement.json").write_text(json.dumps(artifacts.to_dict(), default=str))
    (root / "replay-results.json").write_text(json.dumps(results, indent=1))
    usage_cache = [t.get("cached_tokens") for r in results.values() for t in r["turns"]]
    summary = dict(cohort_id=cohort_id, interval_s=round(t1 - t0, 3), energy=energy, sessions=len(sessions), drain=drain,
                   failed=sum(1 for r in results.values() if r["error"]),
                   mismatched_turns=sum(1 for r in results.values() for t in r["turns"] if not t["output_ids_match"]),
                   prompt_tokens=sum((t.get("prompt_tokens") or 0) for r in results.values() for t in r["turns"]),
                   cached_tokens=sum(usage_cache) if usage_cache and all(v is not None for v in usage_cache) else None,
                   cached_tokens_source="request_usage" if usage_cache and all(v is not None for v in usage_cache) else "incomplete request usage; use interval counter evidence")
    (root / "replay-summary.json").write_text(json.dumps(summary, indent=1))
    events.append("replay_end", **{k: v for k, v in summary.items() if k != "energy"})
    events.close()
    write_manifest(root)
    return summary
