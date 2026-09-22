"""One bounded native/fixture campaign using ALEMS measurement and durable ledger."""
from dataclasses import asdict
import argparse
import hashlib
import json
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
from .control import Lifecycle, Policy
from .workloads import create_tasks, WorkloadRuntime, VERSION

EXECUTION_PROTOCOL = "planned-body-initialized-window-v1"


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
    if query_assets:
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
    policies = [
        Policy(
            name,
            0 if name == "demand" else args.byte_budget,
            bytes_per_second=args.bytes_per_second,
            expected_pause_seconds=args.expected_pause_seconds,
        )
        for name in args.policies.split(",")
    ]
    if len({p.name for p in policies}) != len(policies):
        raise ValueError("duplicate policy")
    fingerprint = digest(
        dict(
            config=config,
            policies=[asdict(p) for p in policies],
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            deadline=args.deadline,
            mode=args.mode,
            execution_protocol=EXECUTION_PROTOCOL,
            query_engine=args.query_engine if query_assets else None,
        )
    )
    by_setting = {f"C00-{p.name}-{digest(asdict(p))[:12]}": p for p in policies}
    verifier_hash = hashlib.sha256(verifier_source.read_bytes()).hexdigest()
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
                    workload_version,
                    verifier_hash,
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
    schedule = CampaignSchedule.build(blocks, seed=args.seed)
    manifest = dict(
        mode=args.mode,
        config=config,
        source_revision=revision,
        fingerprint=fingerprint,
        execution_protocol=EXECUTION_PROTOCOL,
        policies={sid: asdict(p) for sid, p in by_setting.items()},
        schedule=schedule.to_dict(),
        query_engine=args.query_engine if query_assets else None,
        task_catalog=[dict(task_id=t.task_id, family=t.family, lineage=t.lineage,
                           asset_sha256=t.asset_sha256, workload_version=workload_version,
                           verifier_sha256=verifier_hash) for t in tasks],
        measurement_scope="CPU-package and GPU-board only; includes backend startup, tools, transfers, cleanup and verification",
    )
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
                backend = ProcessBackend(
                    config,
                    python=args.backend_python or sys.executable,
                    mode=args.mode,
                    log_path=root
                    / "backend-logs"
                    / (request.lease.execution_id + ".log"),
                    timeout=args.deadline,
                )
                lifecycle = Lifecycle(
                    backend, by_setting[request.scheduled_run.planned_run.setting_id]
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
                    initialized_model_window=True,
                    workload_runtime=QueryRuntime(args.fixture_case if simulated else None, args.query_engine) if query_assets else WorkloadRuntime(
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
    p.add_argument("--task", default="all")
    p.add_argument("--query-assets", help="Use the optional prepared TLC SQL task instead of the default five-task catalog")
    p.add_argument("--query-engine", choices=["duckdb", "sqlite"], default="duckdb")
    p.add_argument("--max-runs", type=int, default=4)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--max-steps", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--deadline", type=float, default=120)
    p.add_argument("--seed", type=int, default=7)
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
        ],
    )
    args = p.parse_args(argv)
    if (
        not 0 < args.deadline <= 600
        or min(args.max_runs, args.max_steps, args.repeats, args.max_tokens) < 1
    ):
        p.error("invalid bounded run/step/time budget")
    if args.mode == "native" and args.byte_budget == 128 and args.policies != "demand":
        p.error(
            "native preparation requires an explicit expert-byte budget (fixture default is only 128 bytes)"
        )
    result = run(args)
    if not result["validation"]["valid"]:
        raise SystemExit(2)
    # A structurally valid ledger alone is not a successful native smoke test.
    if args.mode == "native" and any(
        row["successful"] < row["attempts"] or row["invalid_energy_attempts"]
        for row in result["summary"]["settings"].values()
    ):
        raise SystemExit(3)
    if args.mode == "native":
        if not result["window_audit"]["audit_passed"] or not all(
            row.get("all_domains_measured") and row.get("owned_work_terminated")
            and not row.get("simulated", True)
            for row in result["window_audit"]["results"]
        ):
            raise SystemExit(5)
        for setting, row in result["summary"]["settings"].items():
            if (
                any(f"-{name}-" in setting for name in ("fixed", "history"))
                and not row["completed_preparation_bytes"]
            ):
                print(
                    "Native control smoke incomplete: no expert preparation completed. Inspect residency and budget in raw events.",
                    file=sys.stderr,
                )
                raise SystemExit(4)


if __name__ == "__main__":
    main()
