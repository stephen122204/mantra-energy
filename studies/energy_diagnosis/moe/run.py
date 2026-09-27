"""One bounded native/fixture campaign using ALEMS measurement and durable ledger."""
from dataclasses import asdict
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid

from studies.energy_diagnosis.local_run import GoalExecutor, digest
from studies.energy_diagnosis.campaign import PlannedRun, RunLedger
from studies.energy_diagnosis.campaign.runner import (
    BoundedCampaignRunner,
    CampaignSchedule,
    ScheduleBlock,
)
from studies.energy_diagnosis.runtime.node_measurement import (
    NodeMeasurement,
    NodeCounterReader,
    FixtureCounterReader,
    environment_identity,
)
from .backend import ProcessBackend, BackendAdapter
from .control import PAUSE_POLICIES, Lifecycle, Policy
from .workloads import create_tasks, WorkloadRuntime, VERSION

EXECUTION_PROTOCOL = "planned-body-initialized-window-v1"


def policy_backend_config(config, policy, *, simulated=False):
    # The pinned backend has not demonstrated native builtin-prefetch activity.
    # Do not silently run a demand-only implementation under a builtin label.
    if policy.name == "builtin" and not simulated:
        raise ValueError("builtin prefetch is not qualified on the pinned native backend")
    return dict(config, builtin_prefetch=policy.name == "builtin")


class CampaignInterrupted(BaseException):
    """SIGTERM/SIGINT: unwind through every cleanup block without being treated
    as an ordinary goal failure. The claimed attempt stays `running` for the
    guarded recovery command; owned worker and tool processes are terminated."""


def _interrupt(signum, frame):
    raise CampaignInterrupted(f"campaign received signal {signum}")


def parse_cpu_list(text):
    """Linux cpu-list syntax ("64-71,80") -> sorted unique CPU ids."""
    cpus = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        lo, hi = int(lo), int(hi or lo)
        if lo < 0 or hi < lo:
            raise ValueError(f"invalid CPU range: {part!r}")
        cpus.update(range(lo, hi + 1))
    if not cpus:
        raise ValueError("empty CPU list")
    return sorted(cpus)


def apply_cpu_affinity(cpus):
    """Pin this process before any worker/sampler starts so every child inherits it.

    Placement alone does not fix the launch-bound decode rate (see cpu_power_state); it makes the
    CPUs whose power state is recorded, and any keep-awake or idle-state setting, well defined.
    MoE-Infinity still hard-pins two scheduler threads to fixed CPUs regardless of this mask."""
    if not hasattr(os, "sched_getaffinity"):
        if cpus:
            raise ValueError("CPU affinity is not supported on this platform")
        return None
    if cpus:
        os.sched_setaffinity(0, cpus)
        if sorted(os.sched_getaffinity(0)) != list(cpus):
            raise RuntimeError("requested CPU affinity was not applied")
    return dict(pinned=bool(cpus), cpus=sorted(os.sched_getaffinity(0)))


KEEP_AWAKE_LOOP = "import os,sys\nos.sched_setaffinity(0, {int(sys.argv[1])})\nwhile True:\n    pass\n"


class KeepAwake:
    """Declared keep-awake condition: one owned busy process per listed CPU.

    Without root, this is the explicit way to hold cores out of deep idle; it runs for the whole
    campaign process (every goal window sees the same condition) and its power is inside the
    measured CPU-package domain, so its cost is never free. Recorded in the manifest."""

    def __init__(self, cpus, python=sys.executable):
        self.cpus, self.python, self.processes = list(cpus or []), python, []

    def __enter__(self):
        for cpu in self.cpus:
            self.processes.append(subprocess.Popen([self.python, "-c", KEEP_AWAKE_LOOP, str(cpu)],
                                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL))
        return self

    def record(self):
        # No PIDs: the manifest must be identical when a campaign is resumed.
        return dict(cpus=self.cpus, method="owned python busy loop per CPU") if self.cpus else None

    def __exit__(self, *exc):
        for process in self.processes:
            process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return False


def cpu_power_state(cpus, root=Path("/sys/devices/system/cpu")):
    """Read-only record of the frequency governor and idle states of the run's CPUs.

    The native worker is host launch-bound (~10k thread handoffs per token); when its cores enter
    deep idle states between handoffs, decode slowed ~2x on both development nodes. This setting
    therefore changes the measured quantity and must be recorded with every run."""
    if not cpus or not root.is_dir():
        return None

    def read(path):
        try:
            return path.read_text().strip()
        except OSError:
            return None

    states = {}
    for cpu in cpus:
        base = root / f"cpu{cpu}"
        idle = []
        for state in sorted((base / "cpuidle").glob("state*"), key=lambda p: int(p.name[5:])):
            idle.append(dict(name=read(state / "name"), exit_latency_us=read(state / "latency"),
                             disabled=read(state / "disable")))
        key = json.dumps(dict(governor=read(base / "cpufreq/scaling_governor"),
                              min_khz=read(base / "cpufreq/scaling_min_freq"),
                              max_khz=read(base / "cpufreq/scaling_max_freq"),
                              idle=idle), sort_keys=True)
        states.setdefault(key, []).append(cpu)
    return [dict(json.loads(key), cpus=group) for key, group in states.items()]


def run(args):
    simulated = args.mode == "fixture"
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = (
        json.loads(Path(args.config).read_text())
        if args.config
        else {"fixture_case": args.fixture_case}
    )
    if not simulated and (not args.config or not args.allocation_id):
        raise ValueError("native execution needs config and assigned allocation ID")
    if (
        not simulated
        and subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    ):
        raise ValueError("native execution requires a clean reviewed checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    query_assets = getattr(args, "query_assets", None)
    pack_path = getattr(args, "task_pack", None)
    prepared_assets = getattr(args, "task_pack_assets", None)
    pack = None
    if prepared_assets and not pack_path:
        raise ValueError("task-pack-assets requires task-pack specifications")
    if pack_path and query_assets:
        raise ValueError("task-pack and query-assets are mutually exclusive")
    if pack_path:
        from .task_pack import prepare
        specifications = json.loads(Path(pack_path).read_text(encoding="utf-8"))
        pack = prepare(root / "assets", specifications, prepared_assets=prepared_assets)
        tasks = pack.tasks
    elif query_assets:
        from .query_workload import load_task, QueryRuntime, VERSION as query_version
        tasks = (load_task(query_assets, allow_fixture=simulated, engine=args.query_engine),)
        workload_version = query_version
        verifier_source = Path(__file__).with_name("query_workload.py")
    else:
        tasks = create_tasks(root / "assets")
        workload_version = VERSION
        verifier_source = Path(__file__).with_name("workloads.py")
    if args.task != "all":
        tasks = tuple(t for t in tasks if t.task_id == args.task)
    if not tasks:
        raise ValueError("unknown task")
    from .expert_profile import load as load_policy_data
    policy_data = {}
    for item in getattr(args, "policy_data", None) or []:
        name, _, path = item.partition("=")
        if name not in {"static", "future"} or not path or name in policy_data:
            raise ValueError("--policy-data takes static=PATH or future=PATH once each")
        policy_data[name] = load_policy_data(path)
        expected_kind = "static-profile-v1" if name == "static" else "future-trace-v2"
        if policy_data[name][0].get("kind") != expected_kind:
            raise ValueError(f"{name} requires {expected_kind}; rebuild policy data from recorded goals")
    policies = [
        Policy(
            name,
            0 if name in {"demand", "builtin"} else args.byte_budget,
            bytes_per_second=args.bytes_per_second,
            expected_pause_seconds=args.expected_pause_seconds,
            seed=getattr(args, "random_seed", 0) if name == "random" else 0,
            timing=getattr(args, "preparation_timing", "during") if name in PAUSE_POLICIES else "during",
            data_sha256=policy_data[name][1] if name in policy_data else None,
        )
        for name in args.policies.split(",")
    ]
    if len({p.name for p in policies}) != len(policies):
        raise ValueError("duplicate policy")
    backend_configs = {p.name: policy_backend_config(config, p, simulated=simulated) for p in policies}
    comparison_order = getattr(args, "comparison_order", "random")
    if comparison_order not in {"random", "balanced-pairs"}:
        raise ValueError("unknown comparison order")
    fingerprint = digest(
        dict(
            config=config,
            policies=[asdict(p) for p in policies],
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            deadline=args.deadline,
            agent=_agent_settings(args),
            mode=args.mode,
            execution_protocol=EXECUTION_PROTOCOL,
            comparison_order=comparison_order,
            query_engine=args.query_engine if query_assets else None,
        )
    )
    by_setting = {f"C00-{p.name}-{digest(asdict(p))[:12]}": p for p in policies}
    if pack is not None:
        catalog = {row["task_id"]: row for row in pack.catalog()}
    else:
        verifier_hash = hashlib.sha256(verifier_source.read_bytes()).hexdigest()
        catalog = {t.task_id: dict(task_id=t.task_id, family=t.family, lineage=t.lineage,
                    asset_sha256=t.asset_sha256, workload_version=workload_version,
                    verifier_sha256=verifier_hash) for t in tasks}
    blocks = []
    for repeat in range(args.repeats):
        for task in tasks:
            plans = tuple(
                PlannedRun(
                    f"{task.task_id}-r{repeat}-{sid}",
                    i + 1,
                    task.task_id,
                    sid,
                    False,
                    1,
                    revision,
                    task.asset_sha256,
                    digest(config),
                    catalog[task.task_id]["workload_version"],
                    catalog[task.task_id]["verifier_sha256"],
                    simulated=simulated,
                )
                for i, sid in enumerate(by_setting)
            )
            blocks.append(
                ScheduleBlock(
                    f"{task.task_id}-r{repeat}",
                    args.allocation_id or "fixture",
                    fingerprint,
                    plans,
                )
            )
    schedule = CampaignSchedule.build(blocks, seed=args.seed, balanced_pairs=comparison_order == "balanced-pairs")
    manifest = dict(
        mode=args.mode,
        config=config,
        source_revision=revision,
        fingerprint=fingerprint,
        execution_protocol=EXECUTION_PROTOCOL,
        comparison_order=comparison_order,
        limits=dict(goal_seconds=args.deadline, max_steps=args.max_steps, max_output_tokens=args.max_tokens),
        agent=_agent_settings(args),
        policies={sid: asdict(p) for sid, p in by_setting.items()},
        schedule=schedule.to_dict(),
        query_engine=args.query_engine if query_assets else None,
        task_catalog=[catalog[t.task_id] for t in tasks],
        measurement_scope="CPU-package and GPU-board only; includes backend startup, tools, transfers, cleanup and verification",
        cpu_affinity=getattr(args, "applied_cpu_affinity", None),
        keep_awake=getattr(args, "keep_awake_record", None),
        tool_cpus=getattr(args, "tool_cpus", None),
        cpu_power=cpu_power_state(sorted(set((getattr(args, "applied_cpu_affinity", None) or {}).get("cpus") or [])
                                         | set((getattr(args, "keep_awake_record", None) or {}).get("cpus") or [])) or None),
    )
    if config.get("diagnostic"):
        # Profiling/observation switches perturb execution: never campaign evidence.
        manifest["diagnostic"] = config["diagnostic"]
    if pack is not None:
        manifest["task_pack"] = json.loads((pack.root / "task-pack.json").read_text())
    path = root / "moe-manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError("campaign manifest changed; use a new output directory")
    else:
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    reader = (
        FixtureCounterReader(missing_gpu=args.fixture_case == "missing_telemetry")
        if simulated
        else NodeCounterReader(args.gpu_index)
    )
    device = {"uuid": "SIMULATED"} if simulated else reader.device_identity()
    environment = environment_identity(
        revision,
        args.allocation_id or "SIMULATED",
        "SIMULATED" if simulated else args.isolation,
        devices=(device["uuid"],),
    )
    ledger = RunLedger(root / "ledger.sqlite", artifact_root=root)
    runner = BoundedCampaignRunner(ledger, schedule, root / "state")
    count = 0
    try:
        for _ in range(args.max_runs):
            measurement = NodeMeasurement(
                reader,
                environment,
                session_id=("fixture-" if simulated else "") + str(uuid.uuid4()),
            )
            if simulated:
                measurement.clock_domain = "fixture:" + measurement.clock_domain
                measurement.session.clock_domain = measurement.clock_domain
            started = measurement.start_goal()

            def execute(request):
                policy = by_setting[request.scheduled_run.planned_run.setting_id]
                backend = ProcessBackend(
                    # Only the builtin arm enables the backend's own prefetcher.
                    backend_configs[policy.name],
                    python=args.backend_python or sys.executable,
                    mode=args.mode,
                    log_path=root
                    / "backend-logs"
                    / (request.lease.execution_id + ".log"),
                    timeout=args.deadline,
                    deadline_ns=request.lease.started_ns + int(args.deadline * 1e9),
                )
                lifecycle = Lifecycle(
                    backend, policy,
                    data=policy_data[policy.name][0] if policy.name in policy_data else None,
                )
                executor = GoalExecutor(
                    {t.task_id: t for t in tasks},
                    BackendAdapter(backend, args.max_tokens),
                    measurement,
                    root,
                    max_steps=args.max_steps,
                    timeout_seconds=args.deadline,
                    simulated=simulated,
                    lifecycle=lifecycle,
                    protocol=args.agent_protocol,
                    sampling=_agent_settings(args)["sampling"],
                    max_tool_calls=args.max_tool_calls,
                    max_output_tokens=args.max_total_output_tokens,
                    initialized_model_window=True,
                    workload_runtime=pack.runtime(root) if pack is not None else QueryRuntime(args.fixture_case if simulated else None, args.query_engine) if query_assets else WorkloadRuntime(
                        root, args.fixture_case if simulated else None
                    ),
                )
                try:
                    return executor(request)
                finally:
                    backend.end_goal()

            try:
                lease = runner.run_next(
                    session_id=measurement.session_id,
                    started_ns=started,
                    clock_domain=measurement.clock_domain,
                    executor=execute,
                )
            finally:
                if measurement.artifacts is None:
                    measurement.finish_goal()
            if lease is None:
                break
            count += 1
    finally:
        paths = runner.export(root / "exports")
        ledger.close()
        reader.close()
    report = json.loads(paths["campaign_validation"].read_text())
    from .summary import summarize
    from .audit_windows import audit

    analysis = summarize(root)
    window_audit = audit(root)
    (root / "window-audit.json").write_text(
        json.dumps(window_audit, indent=2, allow_nan=False) + "\n"
    )
    (root / "summary.json").write_text(
        json.dumps(analysis, indent=2, allow_nan=False) + "\n"
    )
    result = dict(
        mode=args.mode,
        executed=count,
        validation=report,
        summary=analysis,
        window_audit=window_audit,
        output=str(root),
    )
    print(json.dumps(result, indent=2))
    return result


def _agent_settings(args):
    sampling = (dict(mode="sampled", temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
                     min_p=args.min_p, seed=args.sampling_seed)
                if args.decoding == "sampled" else dict(mode="greedy"))
    return dict(protocol=args.agent_protocol, sampling=sampling, max_turns=args.max_steps,
                max_tool_calls=args.max_tool_calls, max_total_output_tokens=args.max_total_output_tokens,
                max_output_tokens_per_turn=args.max_tokens)

def native_windows_acceptable(window_audit):
    """Every attempt measured in all domains, with owned work terminated and not simulated. An attempt classified
    by explicit recovery (reconcile) has no complete window by design; the audit validates its provenance
    separately (audit_recovered) and it is excluded here, so a resumed run is not rejected for it."""
    return window_audit["audit_passed"] and all(
        row.get("all_domains_measured") and row.get("owned_work_terminated") and not row.get("simulated", True)
        for row in window_audit["results"] if not row.get("recovered"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["fixture", "native"], required=True)
    p.add_argument("--config")
    p.add_argument("--output", required=True)
    p.add_argument("--backend-python")
    p.add_argument("--allocation-id")
    p.add_argument("--isolation", default="unverified")
    p.add_argument("--gpu-index", type=int, default=0)
    p.add_argument("--policies", default="demand,fixed")
    p.add_argument("--byte-budget", type=int, default=128)
    p.add_argument("--bytes-per-second", type=float)
    p.add_argument("--expected-pause-seconds", type=float)
    p.add_argument("--policy-data", action="append", metavar="NAME=PATH",
                   help="static=profile.json or future=trace.json from moe/expert_profile.py; hashed into the setting")
    p.add_argument("--random-seed", type=int, default=0, help="Seed for the random matched-budget policy")
    p.add_argument("--preparation-timing", choices=["during", "after"], default="during",
                   help="after: diagnostic control admitting the pause batch only once the tool returns")
    p.add_argument("--cpu-affinity", type=parse_cpu_list, metavar="CPULIST",
                   help="Pin the campaign process tree (worker, sampler, tools), e.g. 64-71; recorded in the manifest")
    p.add_argument("--keep-awake-cpus", type=parse_cpu_list, metavar="CPULIST",
                   help="Declared keep-awake condition: an owned busy process pinned to each listed CPU for the whole run "
                        "(its power is inside the CPU-package domain); must not overlap --cpu-affinity")
    p.add_argument("--tool-cpus", type=parse_cpu_list, metavar="CPULIST",
                   help="CPU set for workload test/tool subprocesses that honour ALEMS_TOOL_CPUS (repository repair); "
                        "must not overlap --cpu-affinity or --keep-awake-cpus; recorded in the manifest")
    p.add_argument("--campaign-exit", action="store_true",
                   help="Exit 0 when measurement is valid even if goals fail (campaign data); exit 3 only for invalid energy or crashed attempts")
    p.add_argument("--task", default="all")
    p.add_argument("--query-assets", help="Use the optional prepared TLC SQL task instead of the default five-task catalog")
    p.add_argument("--task-pack", help="JSON specifications for the numerical/business/ETL task pack")
    p.add_argument("--task-pack-assets", help="Frozen prepared task-pack assets to copy and verify, preserving private challenges across model arms")
    p.add_argument("--query-engine", choices=["duckdb", "sqlite"], default="duckdb")
    p.add_argument("--max-runs", type=int, default=4)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--max-steps", "--max-turns", dest="max_steps", type=int, default=5,
                   help="Model responses per goal, including the answer")
    p.add_argument("--agent-protocol", choices=["chat-tools-v1", "chat-tools-v2", "legacy-json-v1"], default="chat-tools-v1",
                   help="chat-tools-v1: native multi-turn chat and tool calls; chat-tools-v2: v1 plus an unclosed final "
                        "tool_call parsed as vLLM's hermes parser does and feedback that names the fix; legacy-json-v1 reproduces V6")
    p.add_argument("--decoding", choices=["greedy", "sampled"], default="greedy")
    p.add_argument("--temperature", type=float, default=0.7, help="Sampled decoding only (model card value)")
    p.add_argument("--top-p", type=float, default=0.8)
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--min-p", type=float, default=0.0)
    p.add_argument("--sampling-seed", type=int, default=0, help="Base seed; each turn's seed is shared by both arms of a pair")
    p.add_argument("--max-tool-calls", type=int, help="Total tool calls per goal (default: unlimited within turns)")
    p.add_argument("--max-total-output-tokens", type=int, help="Total generated tokens per goal (default: unlimited within turns)")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--deadline", type=float, default=120, help="Whole-goal seconds including model startup, up to 1800; also use a bounded batch supervisor")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--comparison-order", choices=["random", "balanced-pairs"], default="random", help="Balanced pairs require exactly two policies and even repetitions; same task/configuration appears first equally often")
    p.add_argument(
        "--fixture-case",
        default="success",
        choices=[
            "success",
            "wrong_prediction",
            "wrong_answer",
            "locked",
            "broken_ack",
            "cancel_failure",
            "drain_failure",
            "dropped",
            "model_failure",
            "model_timeout",
            "missing_telemetry",
            "tool_failure",
            "tool_timeout",
            "truncated_output",
            "no_action",
            "unclosed_submit",
        ],
    )
    args = p.parse_args(argv)
    if (
        not 0 < args.deadline <= 1800
        or min(args.max_runs, args.max_steps, args.repeats, args.max_tokens) < 1
    ):
        p.error("invalid bounded run/step/time budget")
    if args.decoding == "sampled" and not (
        math.isfinite(args.temperature) and args.temperature > 0 and 0 < args.top_p <= 1 and args.top_k >= 1 and 0 <= args.min_p < 1
    ):
        p.error("invalid sampling parameters")
    if any(v is not None and v < 1 for v in (args.max_tool_calls, args.max_total_output_tokens)):
        p.error("tool-call and output-token budgets must be positive")
    if args.agent_protocol == "legacy-json-v1" and (args.decoding != "greedy" or args.max_tool_calls or args.max_total_output_tokens):
        p.error("legacy-json-v1 reproduces V6 and supports only greedy decoding and turn/output-per-call limits")
    if args.comparison_order == "balanced-pairs" and (args.repeats % 2 or len(set(args.policies.split(","))) != 2):
        p.error("balanced pairs require two distinct policies and even repetitions")
    if args.mode == "native" and args.byte_budget == 128 and args.policies != "demand":
        p.error(
            "native preparation requires an explicit expert-byte budget (fixture default is only 128 bytes)"
        )
    try:
        args.applied_cpu_affinity = apply_cpu_affinity(args.cpu_affinity)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    import signal

    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _interrupt)
    if args.keep_awake_cpus and set(args.keep_awake_cpus) & set((args.applied_cpu_affinity or {}).get("cpus") or []):
        p.error("keep-awake CPUs must not overlap the campaign CPU affinity")
    if args.tool_cpus:
        if set(args.tool_cpus) & (set((args.applied_cpu_affinity or {}).get("cpus") or []) if args.cpu_affinity else set()) \
                or set(args.tool_cpus) & set(args.keep_awake_cpus or []):
            p.error("tool CPUs must not overlap the campaign CPU affinity or keep-awake CPUs")
        os.environ["ALEMS_TOOL_CPUS"] = ",".join(map(str, args.tool_cpus))
    if args.keep_awake_cpus and not hasattr(os, "sched_setaffinity"):
        p.error("keep-awake CPUs require Linux affinity support")
    try:
        with KeepAwake(args.keep_awake_cpus) as keeper:
            args.keep_awake_record = keeper.record()
            result = run(args)
    except CampaignInterrupted as exc:
        print(f"{exc}; owned work terminated, ledger exported, claimed attempt left for recovery", file=sys.stderr)
        raise SystemExit(130)
    if not result["validation"]["valid"]:
        raise SystemExit(2)
    rows = result["summary"]["settings"].values()
    if args.campaign_exit:
        # Campaign data: model outcomes (wrong answer, budget/context/deadline exhaustion) are
        # results, not errors. Stop only for invalid energy or an infrastructure crash.
        # Statuses come from the ledger export (summary), not goal files: an attempt classified by explicit
        # recovery may have no record.json, and its unknown energy is expected, not a new measurement failure.
        crashed = sum(row["crashed_attempts"] for row in rows)
        unexplained_invalid = sum(row["invalid_energy_attempts"] - row["recovered_attempts"] for row in rows)
        if unexplained_invalid > 0 or crashed:
            raise SystemExit(3)
    # A structurally valid ledger alone is not a successful native smoke test.
    elif args.mode == "native" and any(
        row["successful"] < row["attempts"] or row["invalid_energy_attempts"]
        for row in rows
    ):
        raise SystemExit(3)
    if args.mode == "native":
        if not native_windows_acceptable(result["window_audit"]):
            raise SystemExit(5)
        for setting, row in result["summary"]["settings"].items():
            if (
                not args.campaign_exit  # campaign: incomplete preparation is a measured outcome
                and any(f"-{name}-" in setting for name in ("fixed", "history"))
                and not row["completed_preparation_bytes"]
            ):
                print(
                    "Native control smoke incomplete: no expert preparation completed. Inspect residency and budget in raw events.",
                    file=sys.stderr,
                )
                raise SystemExit(4)


if __name__ == "__main__":
    main()
