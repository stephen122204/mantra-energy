"""Bounded pilot / campaign driver: frozen plan in, checksummed result tree out.

    python -m studies.paper2.cohort.pilot --plan PLAN.json --out OUT --budget-s 10800 --cutoff-utc ISO

The plan names server configurations (one persistent server per precision block), the task
specifications, and per-block steps:
  {"live": {"name", "admission_limit", "task_ids", "mode", "arrival_offsets_s"?, "est_s"}}
  {"replay": {"name", "source": "<live step name>", "admission_limit", "est_s"}}  # same server, same GPU
  {"idle": {"name", "seconds"}}                                                   # loaded, no requests
Precision blocks run in an order drawn from ``block_seed`` (recorded). A step starts only if its
declared ``est_s`` (or the slowest measured comparable step, if larger) fits in the remaining
budget and before the cutoff; otherwise it is recorded as skipped with the reason. Nothing else
may use the GPU: the driver refuses to start a server if the device already has compute processes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import subprocess
import sys
import time
from pathlib import Path

from .cohort import CohortSpec, run_cohort
from .records import EventLog, write_manifest
from .server import ServerConfig, VllmServer
from .taskprep import cohort_items, prepare_tasks


def gpu_index_for(uuid: str) -> int:
    import pynvml
    pynvml.nvmlInit()
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            u = pynvml.nvmlDeviceGetUUID(pynvml.nvmlDeviceGetHandleByIndex(i))
            if (u.decode() if isinstance(u, bytes) else u) == uuid:
                return i
    finally:
        pynvml.nvmlShutdown()
    raise ValueError(f"GPU {uuid} not found")


def gpu_busy(index: int) -> int:
    import pynvml
    pynvml.nvmlInit()
    try:
        return len(pynvml.nvmlDeviceGetComputeRunningProcesses(pynvml.nvmlDeviceGetHandleByIndex(index)))
    finally:
        pynvml.nvmlShutdown()


def make_measurement(gpu_index: int, revision: str, allocation: str, isolation: str):
    from studies.energy_diagnosis.runtime.node_measurement import NodeCounterReader, NodeMeasurement, environment_identity
    reader = NodeCounterReader(gpu_index=gpu_index)
    return NodeMeasurement(reader, environment_identity(revision, allocation, isolation))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budget-s", type=float, required=True)
    ap.add_argument("--cutoff-utc", required=True)
    ap.add_argument("--fixture-server", action="store_true", help="tests only: no vLLM, no counters")
    a = ap.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    out = a.out
    out.mkdir(parents=True, exist_ok=False)
    (out / "plan.json").write_text(json.dumps(plan, indent=1))
    log = EventLog(out / "driver-events.jsonl")
    t_start = time.monotonic()
    cutoff = dt.datetime.fromisoformat(a.cutoff_utc.replace("Z", "+00:00")).timestamp()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    log.append("driver_start", revision=revision, dirty=bool(dirty), budget_s=a.budget_s, cutoff_utc=a.cutoff_utc)
    if dirty and not a.fixture_server:
        raise SystemExit("refusing to measure from a dirty checkout")

    # Task preparation happens before any server or energy interval.
    catalog = prepare_tasks(plan["task_specs"], out / "prep")
    log.append("tasks_prepared", n=len(catalog))
    configs = [ServerConfig(**c) for c in plan["configs"]]
    order = list(range(len(configs)))
    random.Random(plan["block_seed"]).shuffle(order)
    log.append("block_order", order=[configs[i].name for i in order], seed=plan["block_seed"])
    measured: dict = {}

    def fits(step_name, est):
        remaining = a.budget_s - (time.monotonic() - t_start)
        need = max(est, measured.get(step_name, 0))
        if need > remaining or time.time() + need > cutoff - plan.get("export_reserve_s", 900):
            return False, f"needs ~{need:.0f}s, {remaining:.0f}s budget left"
        return True, ""

    results = []
    for bi in order:
        cfg = configs[bi]
        block = plan["blocks"][cfg.name]
        if not fits(f"load-{cfg.name}", plan.get("load_est_s", 600))[0]:
            log.append("block_skipped", config=cfg.name, reason="no budget for server load")
            continue
        gpu_uuid = plan["gpu_uuid"]
        server = None
        if a.fixture_server:
            from .client import MistralRenderer
            from .fake_server import FakeVllm
            server = FakeVllm(MistralRenderer(plan["tekken"][cfg.name]), served_model=cfg.name, delay_s=0.05)
            server.__enter__()
            base_url, started, gidx = server.base_url, {"fixture": True}, None
        else:
            gidx = gpu_index_for(gpu_uuid)
            if gpu_busy(gidx):
                raise SystemExit(f"GPU {gpu_uuid} already has compute processes")
            server = VllmServer(cfg, port=plan.get("port", 8100), log_path=out / "servers" / f"{cfg.name}.log",
                                gpu_uuid=gpu_uuid)
            started = server.start()
            base_url = server.base_url
        log.append("server_started", config=cfg.to_dict(), started=started)
        try:
            live_dirs = {}
            for step in block["steps"]:
                kind, s = next(iter(step.items()))
                name = f"{cfg.name}-{s['name']}"
                ok, why = fits(s["name"], s.get("est_s", 0))
                if not ok:
                    log.append("step_skipped", step=name, reason=why)
                    continue
                meas = None if a.fixture_server else make_measurement(gidx, revision, plan["allocation"], plan["isolation"])
                poller = None
                if not a.fixture_server:
                    from .telemetry import MetricsPoller
                    poller = MetricsPoller(base_url, out / "cohorts" / name / "metrics.jsonl")
                t0 = time.monotonic()
                if kind == "idle":
                    if meas:
                        meas.start_goal()
                    time.sleep(s["seconds"])
                    res = dict(idle_s=s["seconds"])
                    if meas:
                        from .energy import cohort_energy_summary
                        res["energy"] = cohort_energy_summary(meas.finish_goal())
                    (out / "cohorts" / name).mkdir(parents=True, exist_ok=True)
                    (out / "cohorts" / name / "idle-summary.json").write_text(json.dumps(res, indent=1, default=str))
                elif kind == "live":
                    (out / "cohorts" / name).mkdir(parents=True, exist_ok=True)
                    spec = CohortSpec(cohort_id=name, config_id=cfg.config_id(), served_model=cfg.name, base_url=base_url,
                                      max_model_len=cfg.max_model_len, tekken=plan["tekken"][cfg.name],
                                      tasks=cohort_items(catalog, s["task_ids"], repeat_tag=s["name"]),
                                      mode=s.get("mode", "fixed"), admission_limit=s["admission_limit"],
                                      arrival_offsets_s=s.get("arrival_offsets_s"), limits=plan["limits"],
                                      sampling=dict(plan["sampling"], seed=s.get("seed", plan["sampling"].get("seed", 0))),
                                      cohort_deadline_s=s.get("cohort_deadline_s", plan.get("cohort_deadline_s", 3600)),
                                      tool_cpus=plan.get("tool_cpus"), session_cpus=plan.get("session_cpus"),
                                      labels=dict(config=cfg.name, step=s["name"]))
                    res = run_cohort(spec, out / "cohorts" / name, measurement=meas, poller=poller)
                    live_dirs[s["name"]] = out / "cohorts" / name / name
                elif kind == "replay":
                    from .replay import load_live_session, run_replay
                    src = live_dirs.get(s["source"])
                    if src is None:
                        log.append("step_skipped", step=name, reason=f"source {s['source']} not run")
                        continue
                    sessions = [load_live_session(p) for p in sorted((src / "sessions").iterdir())]
                    res = run_replay(name, sessions, base_url, cfg.name, out / "cohorts", admission_limit=s["admission_limit"],
                                     measurement=meas, poller=poller, labels=dict(config=cfg.name, source=s["source"]))
                else:
                    raise ValueError(f"unknown step kind {kind}")
                took = time.monotonic() - t0
                measured[s["name"]] = max(measured.get(s["name"], 0), took)
                log.append("step_done", step=name, step_kind=kind, seconds=round(took, 1))
                results.append(dict(step=name, kind=kind, seconds=round(took, 1),
                                    **{k: res.get(k) for k in ("outcomes", "verified_pass", "joules_per_verified_success",
                                                               "interval_s", "mismatched_turns", "failed") if k in res},
                                    energy_j=(res.get("energy") or {}).get("cpu_plus_gpu_j")))
        finally:
            if a.fixture_server:
                server.__exit__(None, None, None)
            else:
                log.append("server_stopped", config=cfg.name, returncode=server.stop())
    (out / "pilot-results.json").write_text(json.dumps(results, indent=1, default=str))
    log.append("driver_end", elapsed_s=round(time.monotonic() - t_start, 1), steps=len(results))
    log.close()
    write_manifest(out)
    print(json.dumps(dict(steps=len(results), out=str(out))))


if __name__ == "__main__":
    sys.exit(main())
