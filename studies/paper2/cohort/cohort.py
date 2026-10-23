"""Cohort supervisor: N independent agent sessions sharing one persistent server.

One cohort = a fixed, finite list of task attempts executed against one already-running server
under one admission rule, inside ONE CPU-package + GPU-board energy interval that starts before
the first offer and ends when the last attempt is terminal (failures, timeouts and drain
included; no filler work). Two load modes:

* ``fixed``: every attempt is offered at t=0; at most ``admission_limit`` run at once.
* ``arrivals``: attempt i is offered at ``arrival_offsets_s[i]``; it waits (counted from its
  offer) until fewer than ``admission_limit`` sessions run.

Each session is a separate process (own workspace, own process group). Hard caps cancel a
session at ``deadline_s + grace_s`` and the whole cohort at ``cohort_deadline_s``; cancelled
and never-admitted attempts get explicit terminal outcomes. Research verification runs after
the interval is sealed. An interrupted cohort is never resumed into the same interval: rerun
marks its open attempts ``infra_failed`` and starts a new cohort id with ``retry_of``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from studies.energy_diagnosis.agent_protocol import CHAT_PROTOCOLS

from .records import EventLog, new_id, reconcile, write_manifest, TERMINAL

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CohortSpec:
    cohort_id: str
    config_id: str
    served_model: str
    base_url: str
    max_model_len: int
    tekken: str
    tasks: list                      # [{"task_id", "task_pickle", "task_kind", "pair_key"}] in offer order
    mode: str = "fixed"              # fixed | arrivals
    admission_limit: int = 1
    arrival_offsets_s: Optional[list] = None
    limits: dict = field(default_factory=lambda: dict(max_turns=250, max_tool_calls=500, max_total_output_tokens=65536,
                                                      max_tokens=4096, deadline_s=1800, verify_timeout_s=900))
    sampling: dict = field(default_factory=lambda: dict(mode="greedy"))
    grace_s: float = 120.0
    cohort_deadline_s: float = 4 * 3600
    tool_cpus: Optional[str] = None
    session_cpus: Optional[str] = None
    retry_of: Optional[str] = None
    labels: dict = field(default_factory=dict)
    drain_timeout_s: float = 120.0
    task_options: dict = field(default_factory=dict)   # e.g. {"swebench": {"cpus": "4", "memory": "16g"}}
    protocol: str = "chat-tools-v2"                    # agent protocol of every session (agent_protocol.CHAT_PROTOCOLS)

    def validate(self):
        if self.mode not in ("fixed", "arrivals"):
            raise ValueError("mode must be fixed or arrivals")
        if self.protocol not in CHAT_PROTOCOLS:
            raise ValueError(f"unknown agent protocol {self.protocol!r}")
        if self.admission_limit < 1:
            raise ValueError("admission_limit must be >= 1")
        if self.mode == "arrivals":
            if not self.arrival_offsets_s or len(self.arrival_offsets_s) != len(self.tasks):
                raise ValueError("arrivals mode needs one offset per task")
            if any(b < a for a, b in zip(self.arrival_offsets_s, self.arrival_offsets_s[1:])):
                raise ValueError("arrival offsets must be non-decreasing")
        if len({t["pair_key"] for t in self.tasks}) != len(self.tasks):
            raise ValueError("each attempt needs a distinct pair_key")


class _Session:
    def __init__(self, spec: CohortSpec, item: dict, root: Path, events: EventLog):
        self.item, self.events = item, events
        self.attempt_id = new_id("att")
        self.session_id = f"{spec.cohort_id}-{item['pair_key']}"
        self.dir = root / "sessions" / self.session_id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.spec_path = self.dir / "spec.json"
        self.spec_path.write_text(json.dumps(dict(
            session_id=self.session_id, attempt_id=self.attempt_id, cohort_id=spec.cohort_id, config_id=spec.config_id,
            task_id=item["task_id"], task_pickle=item["task_pickle"], task_kind=item["task_kind"], pair_key=item["pair_key"],
            server=dict(base_url=spec.base_url, served_model=spec.served_model, max_model_len=spec.max_model_len),
            tekken=spec.tekken, limits=spec.limits, sampling=spec.sampling, tool_cpus=spec.tool_cpus,
            protocol=spec.protocol, tool_call_format="mistral", **spec.task_options), indent=1))
        self.proc: Optional[subprocess.Popen] = None
        self.offered = self.admitted = self.ended = None
        self.outcome: Optional[str] = None
        self.stopped: Optional[str] = None  # outcome we imposed by signalling the session (deadline / cancel)
        self.stop_signal: Optional[int] = None

    def start(self, python: str, session_cpus: Optional[str]):
        cmd = [python, "-m", "studies.paper2.cohort.session", "--spec", str(self.spec_path)]
        if session_cpus:
            cmd = ["taskset", "-c", session_cpus] + cmd
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        self.log = open(self.dir / "session.log", "w")
        self.proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                     start_new_session=True)

    def kill(self, sig=signal.SIGTERM, *, outcome=None):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                return False
            self.stop_signal = int(sig)
            if outcome is not None:
                self.stopped = outcome
            return True
        return False

    def finish(self, forced: Optional[str]) -> str:
        if forced:
            return forced
        try:
            out = json.loads((self.dir / "outcome.json").read_text())
            return out["outcome"]
        except (OSError, ValueError, KeyError):
            return "infra_failed"


def run_cohort(spec: CohortSpec, out_root: Path, *, measurement=None, poller=None, python: str = sys.executable,
               poll_s: float = 0.2, clock=time.monotonic) -> dict:
    """Execute one cohort. ``measurement`` is a NodeMeasurement (None only in fixture tests)."""
    spec.validate()
    root = Path(out_root) / spec.cohort_id
    if (root / "events.jsonl").exists():
        raise FileExistsError(f"{root} exists; interrupted cohorts are closed with close_interrupted() and rerun under a new id")
    root.mkdir(parents=True)
    (root / "cohort-spec.json").write_text(json.dumps(asdict(spec), indent=1))
    events = EventLog(root / "events.jsonl")
    events.append("cohort_start", cohort_id=spec.cohort_id, config_id=spec.config_id, mode=spec.mode,
                  admission_limit=spec.admission_limit, n_tasks=len(spec.tasks), retry_of=spec.retry_of, labels=spec.labels)
    pending = [_Session(spec, item, root, events) for item in spec.tasks]
    offsets = spec.arrival_offsets_s if spec.mode == "arrivals" else [0.0] * len(pending)
    waiting: list[_Session] = []
    running: list[_Session] = []
    done: list[_Session] = []
    if poller:
        poller.start()
    if measurement:
        measurement.start_goal()
    t0 = clock()
    events.append("interval_start", t0_mono=t0)
    cohort_cancelled = False
    cancel_reason = "cohort deadline before admission"
    infrastructure_fault = None
    try:
        while pending or waiting or running:
            now = clock() - t0
            while pending and offsets[len(spec.tasks) - len(pending)] <= now:
                s = pending.pop(0)
                s.offered = now
                waiting.append(s)
                events.append("offered", attempt_id=s.attempt_id, task_id=s.item["task_id"], session_id=s.session_id,
                              offset_s=round(now, 3), retry_of=None)
            if now >= spec.cohort_deadline_s and not cohort_cancelled:
                cohort_cancelled = True
                for s in running:
                    s.kill(outcome="cancelled")
            while waiting and len(running) < spec.admission_limit and not cohort_cancelled:
                s = waiting.pop(0)
                s.admitted = clock() - t0
                s.start(python, spec.session_cpus)
                running.append(s)
                events.append("admitted", attempt_id=s.attempt_id, task_id=s.item["task_id"], pid=s.proc.pid,
                              queue_wait_s=round(s.admitted - s.offered, 3), active_after=len(running))
            if cohort_cancelled:
                for s in waiting + pending:
                    s.offered = s.offered if s.offered is not None else now
                    if s in pending:
                        events.append("offered", attempt_id=s.attempt_id, task_id=s.item["task_id"],
                                      session_id=s.session_id, offset_s=round(now, 3), retry_of=None)
                    events.append("terminal", attempt_id=s.attempt_id, task_id=s.item["task_id"], outcome="cancelled",
                                  reason=cancel_reason)
                    s.outcome = "cancelled"
                    done.append(s)
                waiting.clear()
                pending.clear()
            for s in list(running):
                age = clock() - t0 - s.admitted
                if s.proc.poll() is None:
                    if age > spec.limits["deadline_s"] + spec.grace_s:
                        s.kill(outcome="timed_out")
                        try:
                            s.proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            s.kill(signal.SIGKILL)
                            s.proc.wait(timeout=15)
                    elif cohort_cancelled and age > 0:
                        try:
                            s.proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            s.kill(signal.SIGKILL)
                            s.proc.wait(timeout=15)
                    else:
                        continue
                s.ended = clock() - t0
                # a session that exits from our signal before it is polled is still ours to label, not infra
                imposed = s.stopped if s.stop_signal and s.proc.returncode == -s.stop_signal else None
                forced = None if s.proc.returncode == 0 else (imposed or "infra_failed")
                s.outcome = s.finish(forced)
                s.log.close()
                running.remove(s)
                done.append(s)
                events.append("terminal", attempt_id=s.attempt_id, task_id=s.item["task_id"], outcome=s.outcome,
                              returncode=s.proc.returncode, scheduler_stop=s.stopped, stop_signal=s.stop_signal,
                              latency_from_offer_s=round(s.ended - s.offered, 3),
                              service_s=round(s.ended - s.admitted, 3), active_after=len(running))
                fault = workspace_fault(s.dir) if s.outcome == "infra_failed" else None
                if fault and infrastructure_fault is None:
                    # A broken agent workspace makes the whole cohort unusable: stop admitting, stop the
                    # running sessions, and drain; every attempt keeps its records and an explicit outcome.
                    infrastructure_fault = dict(session_id=s.session_id, error=fault)
                    events.append("infrastructure_stop", session_id=s.session_id, error=fault[:300])
                    cohort_cancelled = True
                    cancel_reason = f"infrastructure fault in {s.session_id}"
                    for other in running:
                        other.kill(outcome="cancelled")
            time.sleep(poll_s)
    except BaseException as exc:
        for s in running:
            s.kill(signal.SIGKILL)
        events.append("cohort_aborted", reason=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # engine work left by stopped sessions stays inside the interval: wait for the server to drain
        from .guards import wait_drained
        drain = wait_drained(spec.base_url, timeout_s=spec.drain_timeout_s)
        events.append("drained", **drain)
        t1 = clock()
        artifacts = measurement.finish_goal() if measurement else None
        if poller:
            poller.stop()
        events.append("interval_end", t1_mono=t1, interval_s=round(t1 - t0, 3))
    if any(item.get("task_kind") == "swebench" for item in spec.tasks):
        from .guards import leftover_containers
        events.append("container_cleanup", **leftover_containers())
    energy = None
    if artifacts is not None:
        from .energy import cohort_energy_summary
        energy = cohort_energy_summary(artifacts)
        (root / "measurement.json").write_text(json.dumps(artifacts.to_dict(), default=str))
    # Research verification: after the interval is sealed, never inside it.
    verdicts = {}
    for s in done:
        if s.outcome == "completed":
            p = subprocess.run([python, "-m", "studies.paper2.cohort.session", "--spec", str(s.spec_path), "--verify"],
                               cwd=REPO_ROOT, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT)), capture_output=True, text=True)
            try:
                v = json.loads((s.dir / "verification.json").read_text())
            except (OSError, ValueError):
                v = dict(verdict="unavailable", reason=f"verifier exited {p.returncode}: {p.stderr[-300:]}")
        else:
            v = dict(verdict="not_run", reason=f"agent outcome {s.outcome}")
        verdicts[s.attempt_id] = v
        events.append("verified", attempt_id=s.attempt_id, task_id=s.item["task_id"], verdict=v.get("verdict"),
                      reason=str(v.get("reason", ""))[:300])
    summary = summarize(spec, done, verdicts, energy, list(events.read()))
    summary["infrastructure_fault"] = infrastructure_fault
    (root / "cohort-summary.json").write_text(json.dumps(summary, indent=1, default=str))
    events.append("cohort_end", reconciled=summary["reconciliation"]["reconciled"])
    events.close()
    write_manifest(root)
    return summary


def workspace_fault(session_dir: Path):
    """The session's WorkspaceFault error, if a permitted workspace write (or the workspace copy) failed."""
    try:
        error = json.loads((Path(session_dir) / "outcome.json").read_text()).get("error") or ""
    except (OSError, ValueError):
        return None
    return error if error.startswith(("WorkspaceFault:", "infrastructure_failure: WorkspaceFault:")) else None


def summarize(spec: CohortSpec, done, verdicts, energy, events) -> dict:
    rec = reconcile(events)
    passed = sum(1 for v in verdicts.values() if v.get("verdict") == "pass")
    joules = energy["cpu_plus_gpu_j"] if energy else None
    sessions = [dict(attempt_id=s.attempt_id, task_id=s.item["task_id"], session_id=s.session_id, outcome=s.outcome,
                     verdict=verdicts.get(s.attempt_id, {}).get("verdict"), offered_s=s.offered, admitted_s=s.admitted,
                     ended_s=s.ended) for s in done]
    infra = sum(1 for s in done if s.outcome == "infra_failed")
    verification_invalid = any(v.get("verdict") == "unavailable" or (v.get("detail") or {}).get("infrastructure")
                               for v in verdicts.values())
    return dict(cohort_id=spec.cohort_id, config_id=spec.config_id, mode=spec.mode, admission_limit=spec.admission_limit,
                offered=len(done), outcomes=rec["outcomes"], verified_pass=passed, reconciliation=rec,
                energy=energy, joules_per_verified_success=(joules / passed) if (joules is not None and passed) else None,
                infra_invalid=infra > 0 or verification_invalid, sessions=sessions,
                drain=next(({k: e.get(k) for k in ("drained", "drain_s", "last")} for e in events if e.get("kind") == "drained"), None),
                container_cleanup=next(({k: e.get(k) for k in ("checked", "leftover", "removed")} for e in events
                                        if e.get("kind") == "container_cleanup"), None),
                note="joules_per_verified_success is undefined (None) with zero passes or missing energy")


def close_interrupted(cohort_root: Path, reason: str = "supervisor interrupted") -> dict:
    """Give every open attempt of an interrupted cohort an explicit infra_failed outcome. Files are kept."""
    events = EventLog(Path(cohort_root) / "events.jsonl")
    rec = reconcile(events.read())
    for aid in rec["open"]:
        events.append("terminal", attempt_id=aid, outcome="infra_failed", reason=reason)
    events.append("cohort_interrupted_closed", reason=reason, closed=len(rec["open"]))
    out = reconcile(events.read())
    events.close()
    return out
