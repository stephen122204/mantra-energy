"""Bounded pilot / campaign driver: frozen plan in, checksummed result tree out.

    python -m studies.paper2.cohort.pilot --plan PLAN.json --out OUT --budget-s 10800 --cutoff-utc ISO

The plan names server configurations (one persistent server per precision block), the task
specifications, and per-block steps:
  {"live": {"name", "admission_limit", "task_ids", "mode", "arrival_offsets_s"?, "est_s"}}
  {"replay": {"name", "source": "<live step>" | "<config>/<live step>", "admission_limit", "est_s"}}
  {"idle": {"name", "seconds"}}                                                   # loaded, no requests
``"blocks"`` is one pass over the precision blocks; ``"passes": [{"blocks": ...}, ...]`` runs several
(e.g. live cohorts first, then crossed replay of any precision's traces on every precision, all on
this GPU). A replay source without a config prefix is the same block's live step. Each pass runs its
blocks in an order drawn from ``block_seed`` + pass index (recorded). A pass marked ``"atomic": true``
starts only if all of its blocks (server loads + step estimates, raised to measured durations) fit
the remaining budget; otherwise the whole pass is skipped, so its comparison stays paired. A step starts only if its
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

from studies.energy_diagnosis.agent_protocol import CHAT_PROTOCOLS

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


# Counter samples must stay closer together than the energy integrator's gap limit (energy.integrate_samples).
MAX_SAMPLE_PERIOD_S = 20.0
MEASUREMENT_PROTOCOL = "cohort-polling-v2"  # idle steps now honor the telemetry switch


def measurement_mode(plan: dict, step: dict) -> dict:
    """Counter sampling period and server-telemetry polling for one step (defaults: 0.1 s, on)."""
    period = float(step.get("sample_period_s", plan.get("sample_period_s", 0.1)))
    telemetry = step.get("telemetry", plan.get("telemetry", True))
    if not 0 < period <= MAX_SAMPLE_PERIOD_S or not isinstance(telemetry, bool):
        raise ValueError(f"step {step.get('name')}: sample_period_s must be in (0, {MAX_SAMPLE_PERIOD_S}] "
                         "and telemetry a boolean")
    return dict(sample_period_s=period, telemetry=telemetry)


def make_measurement(gpu_index: int, revision: str, allocation: str, isolation: str, sample_period_s: float = 0.1):
    from studies.energy_diagnosis.runtime.node_measurement import NodeCounterReader, NodeMeasurement, environment_identity
    reader = NodeCounterReader(gpu_index=gpu_index)
    return NodeMeasurement(reader, environment_identity(revision, allocation, isolation), sample_period_s=sample_period_s)


def run_idle(seconds: float, *, measurement=None, poller=None) -> dict:
    """Poll throughout the idle energy interval, using the live/replay boundary order."""
    artifacts = None
    try:
        if poller:
            poller.start()
        if measurement:
            measurement.start_goal()
        try:
            time.sleep(seconds)
        finally:
            if measurement:
                artifacts = measurement.finish_goal()
    finally:
        if poller:
            poller.stop()
    result = dict(idle_s=seconds, measurement_protocol=MEASUREMENT_PROTOCOL,
                  telemetry_started=poller is not None)
    if artifacts is not None:
        from .energy import cohort_energy_summary
        result["energy"] = cohort_energy_summary(artifacts)
    return result


def _order(configs, ps, seed, log, pass_index):
    names = [c.name for c in configs]
    if ps.get("order"):  # planner-assigned (balanced rotation across rounds)
        if sorted(ps["order"]) != sorted(ps["blocks"]):
            raise ValueError(f"pass {pass_index} order {ps['order']} does not match its blocks")
        order = [names.index(n) for n in ps["order"]]
        log.append("block_order", order=list(ps["order"]), seed=None, pass_index=pass_index, assigned=True)
        return order
    order = [i for i in range(len(configs)) if names[i] in ps["blocks"]]
    random.Random(seed).shuffle(order)
    log.append("block_order", order=[names[i] for i in order], seed=seed, pass_index=pass_index)
    return order


def check_qualified(catalog_path: Path, rows: list) -> None:
    """A prepared external catalogue (SWE-bench) is used only with a qualification report next to it in
    which every instance qualified (gold resolves, no-op genuinely fails, both with valid harness reports)."""
    q = catalog_path.parent / "qualification.json"
    if not q.exists():
        raise SystemExit(f"{catalog_path}: no qualification.json next to the catalogue")
    status = {r["instance_id"]: r for r in json.loads(q.read_text())}
    def valid(q):
        gold, noop = q.get("gold") or {}, q.get("noop") or {}
        return (q.get("qualified") is True and q.get("controls_valid") is True
                and gold.get("passed") is True and gold.get("reason") == "resolved"
                and noop.get("passed") is False and noop.get("reason") == "not resolved"
                and not gold.get("infrastructure") and not noop.get("infrastructure"))
    bad = [r["task_id"] for r in rows if not valid(status.get(r["task_id"]) or {})]
    if bad:
        raise SystemExit(f"{catalog_path}: instances not qualified: {bad}")


def _tail(path: Path, n: int = 40) -> list:
    try:
        return path.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budget-s", type=float, required=True)
    ap.add_argument("--cutoff-utc", required=True)
    ap.add_argument("--retry-of", help="output directory of the interrupted run this one replaces")
    ap.add_argument("--retry-reason", help="required with --retry-of: the infrastructure cause (e.g. 'infra: ssh lost')")
    ap.add_argument("--fixture-server", action="store_true", help="tests only: no vLLM, no counters")
    ap.add_argument("--dry-run", action="store_true", help="validate and prepare tasks; never start a server or measurement")
    a = ap.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    passes = plan.get("passes") or [dict(blocks=plan["blocks"])]
    for ps in passes:
        for block in ps.get("blocks", {}).values():
            for step in block.get("steps", []):
                for body in step.values():
                    measurement_mode(plan, body)  # reject an invalid measurement mode before anything runs
    if a.retry_of and not (a.retry_reason or "").startswith("infra:"):
        raise SystemExit("--retry-of needs --retry-reason 'infra: <cause>'; configuration failures are outcomes, not retried")
    protocol = plan.get("protocol", "chat-tools-v2")  # one parsing policy for every precision of the plan
    if protocol not in CHAT_PROTOCOLS:
        raise SystemExit(f"unknown agent protocol {protocol!r}")
    out = a.out
    out.mkdir(parents=True, exist_ok=False)
    (out / "plan.json").write_text(json.dumps(plan, indent=1))
    log = EventLog(out / "driver-events.jsonl")
    t_start = time.monotonic()
    cutoff = dt.datetime.fromisoformat(a.cutoff_utc.replace("Z", "+00:00")).timestamp()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    log.append("driver_start", revision=revision, dirty=bool(dirty), budget_s=a.budget_s, cutoff_utc=a.cutoff_utc,
               retry_of=a.retry_of, retry_reason=a.retry_reason, campaign=plan.get("campaign"), protocol=protocol,
               measurement_protocol=MEASUREMENT_PROTOCOL,
               energy_metric=(plan.get("binding") or {}).get("energy_metric", "cpu_package+gpu_board"))
    if plan.get("campaign", {}).get("commit") not in (None, revision):
        raise SystemExit("checkout does not match the campaign execution commit")
    if dirty and not a.fixture_server:
        raise SystemExit("refusing to measure from a dirty checkout")

    # Task preparation happens before any server or energy interval. A frozen asset snapshot
    # (plan.prepared_assets) makes identical task ids identical task instances across rounds and nodes;
    # plan.expected_tasks (task id -> asset sha256) is checked either way.
    catalog = prepare_tasks(plan["task_specs"], out / "prep", prepared_assets=plan.get("prepared_assets"))
    for extra in plan.get("extra_catalogs", []):  # e.g. SWE-bench instances prepared by swebench_workload
        rows = json.loads(Path(extra).read_text())
        check_qualified(Path(extra), rows)
        catalog += rows
    expected = plan.get("expected_tasks") or {}
    have = {c["task_id"]: c.get("asset_sha256") for c in catalog}
    wrong = {t: (h, have.get(t)) for t, h in expected.items() if have.get(t) != h}
    if wrong:
        raise SystemExit(f"task assets differ from the frozen catalogue: {dict(list(wrong.items())[:5])}")
    log.append("tasks_prepared", n=len(catalog), frozen=bool(plan.get("prepared_assets")), checked_against_expected=len(expected))
    configs = [ServerConfig(**c) for c in plan["configs"]]
    measured: dict = {}

    def fits(step_name, est):
        remaining = a.budget_s - (time.monotonic() - t_start)
        need = max(est, measured.get(step_name, 0))
        if need > remaining or time.time() + need > cutoff - plan.get("export_reserve_s", 900):
            return False, f"needs ~{need:.0f}s, {remaining:.0f}s budget left"
        return True, ""

    results = []
    live_dirs = {}  # "<config>/<step>" -> cohort dir, across passes and blocks of this run
    blocks_run = [(pi, position, configs[bi]) for pi, ps in enumerate(passes)
                  for position, bi in enumerate(_order(configs, ps, plan["block_seed"] + pi, log, pi))]
    skipped_passes = set()
    started_passes = set()
    for pass_index, position, cfg in blocks_run:
        if pass_index in skipped_passes:
            continue
        ps = passes[pass_index]
        if pass_index not in started_passes:
            started_passes.add(pass_index)
            if ps.get("atomic") or a.dry_run:
                # measured durations replace estimates once a step (or a server load) has run
                need = sum(measured.get("server-load", plan.get("load_est_s", 600)) +
                           sum(measured.get(next(iter(st.values()))["name"], next(iter(st.values())).get("est_s", 0))
                               for st in b["steps"])
                           for b in ps["blocks"].values())
                ok, why = (False, "dry run: no servers or measurements") if a.dry_run else fits(f"pass-{pass_index}", need)
                if not ok:
                    log.append("pass_skipped", pass_index=pass_index, reason=why, need_s=round(need))
                    skipped_passes.add(pass_index)
                    continue
        block = ps["blocks"][cfg.name]
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
            server = VllmServer(cfg, port=plan.get("port", 8100), log_path=out / "servers" / f"{cfg.name}-p{pass_index}.log",
                                gpu_uuid=gpu_uuid)
            try:
                started = server.start()
            except Exception as exc:  # e.g. the configuration does not fit: an outcome of that configuration
                log.append("server_start_failed", config=cfg.name, pass_index=pass_index, outcome="configuration",
                           error=f"{type(exc).__name__}: {exc}", log_tail=_tail(server.log_path))
                continue
            base_url = server.base_url
        log.append("server_started", config=cfg.to_dict(), started=started)
        if started.get("load_s"):
            measured["server-load"] = max(measured.get("server-load", 0), started["load_s"])
        checks = {"ok": True, "fixture": True}
        if not a.fixture_server:
            from .client import MistralRenderer
            from .engine_check import run_checks
            r = MistralRenderer(plan["tekken"][cfg.name])
            prompt = r.encode([dict(role="user", content="Engine check: count from one to twenty.")], [])
            checks = run_checks(base_url, cfg.name, prompt, r.inner.encode(" one two three four five", bos=False, eos=False),
                                sampling=plan["sampling"])
        log.append("engine_check", config=cfg.name, **checks)
        from .client import MistralRenderer as _R
        from .guards import PROBE_TEXT, verified_cache_reset
        probe_ids = _R(plan["tekken"][cfg.name]).encode([dict(role="user", content=PROBE_TEXT)], [])
        bad = [k for k in ("agent_request", "long_context") if not checks.get(k, {"ok": True}).get("ok")]
        if bad:  # agent sessions would get errors or degenerate completions: not a measurement of the configuration
            log.append("block_skipped", config=cfg.name, pass_index=pass_index,
                       reason=f"engine check failed: {', '.join(bad)} ({ {k: checks[k] for k in bad} })")
            if not a.fixture_server:
                log.append("server_stopped", config=cfg.name, returncode=server.stop())
            continue
        server_dead = False
        try:
            for step in block["steps"]:
                kind, s = next(iter(step.items()))
                name = f"{cfg.name}-{s['name']}"
                if s.get("first_block_only") and position > 0:
                    log.append("step_skipped", step=name, reason="first block only")
                    continue
                if kind == "replay" and not checks.get("forced_decoding", {"ok": True}).get("ok"):
                    log.append("step_skipped", step=name, reason="forced decoding failed the engine check")
                    continue
                ok, why = fits(s["name"], s.get("est_s", 0))
                if not ok:
                    log.append("step_skipped", step=name, reason=why)
                    continue
                if kind in ("live", "replay") and plan.get("cache_start", "cold") == "cold":
                    reset = verified_cache_reset(base_url, cfg.name, probe_ids)  # outside the interval
                    log.append("cache_reset", step=name, **reset)
                    if not reset.get("ok"):
                        log.append("step_skipped", step=name, reason=f"cold prefix cache not verified: {reset}")
                        continue
                mode = measurement_mode(plan, s)
                log.append("measurement_mode", step=name, **mode)
                meas = None if a.fixture_server else make_measurement(gidx, revision, plan["allocation"], plan["isolation"],
                                                                      mode["sample_period_s"])
                poller = None
                if not a.fixture_server and mode["telemetry"]:
                    from .telemetry import MetricsPoller
                    poller = MetricsPoller(base_url, out / "cohorts" / name / "metrics.jsonl")
                t0 = time.monotonic()
                if kind == "idle":
                    res = run_idle(s["seconds"], measurement=meas, poller=poller)
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
                                      labels=dict(config=cfg.name, step=s["name"]), task_options=plan.get("task_options", {}),
                                      protocol=protocol)
                    res = run_cohort(spec, out / "cohorts" / name, measurement=meas, poller=poller)
                    live_dirs[f"{cfg.name}/{s['name']}"] = out / "cohorts" / name / name
                elif kind == "replay":
                    from .replay import load_live_session, run_replay
                    src = live_dirs.get(s["source"] if "/" in s["source"] else f"{cfg.name}/{s['source']}")
                    if src is None:
                        log.append("step_skipped", step=name, reason=f"source {s['source']} not run")
                        continue
                    sessions = [load_live_session(p) for p in sorted((src / "sessions").iterdir())]
                    res = run_replay(name, sessions, base_url, cfg.name, out / "cohorts", admission_limit=s["admission_limit"],
                                     measurement=meas, poller=poller, labels=dict(config=cfg.name, source=s["source"]))
                    res["source"] = s["source"]
                else:
                    raise ValueError(f"unknown step kind {kind}")
                took = time.monotonic() - t0
                server_dead = (not a.fixture_server) and server.proc.poll() is not None
                if server_dead:
                    log.append("server_died", config=cfg.name, pass_index=pass_index, step=name, returncode=server.proc.returncode,
                               outcome="configuration", log_tail=_tail(server.log_path))
                measured[s["name"]] = max(measured.get(s["name"], 0), took)
                log.append("step_done", step=name, step_kind=kind, seconds=round(took, 1))
                results.append(dict(step=name, kind=kind, pass_index=pass_index, seconds=round(took, 1), measurement=mode,
                                    measurement_protocol=MEASUREMENT_PROTOCOL,
                                    **{k: res.get(k) for k in ("outcomes", "verified_pass", "joules_per_verified_success",
                                                               "interval_s", "mismatched_turns", "failed", "source") if k in res},
                                    energy_j=(res.get("energy") or {}).get("cpu_plus_gpu_j"),
                                    gpu_board_j=(res.get("energy") or {}).get("gpu_board_j"),
                                    server_died=server_dead))
                if server_dead:
                    break  # remaining steps of this block are not run on a dead server (recorded below)
                if res.get("infrastructure_fault") or res.get("infra_invalid"):
                    reason = "agent workspace fault" if res.get("infrastructure_fault") else "cohort infrastructure invalid"
                    log.append("infrastructure_abort", step=name, reason=reason,
                               **(res.get("infrastructure_fault") or {}))
                    raise RuntimeError(f"{name}: {reason}; stopping before another measurement")
                if kind in ("live", "replay"):
                    from .guards import require_clean_boundary
                    try:
                        require_clean_boundary(res)
                    except RuntimeError as exc:
                        log.append("infrastructure_abort", step=name, reason=str(exc))
                        raise
            if server_dead:
                for rest in block["steps"][block["steps"].index(step) + 1:]:
                    log.append("step_skipped", step=f"{cfg.name}-{next(iter(rest.values()))['name']}",
                               reason="server died during this block (configuration outcome)")
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
