"""Frozen campaign plan -> node_batches specification (deterministic; no run-time decisions).

    python -m studies.energy_diagnosis.diagnostics.campaign_plan --plan plan.json --output node-spec.json
    python -m studies.energy_diagnosis.diagnostics.campaign_plan --plan plan.json --windows 6

Each batch is one goal: (repetition block, task, arm). Within every block and task the arm order
is a seeded permutation recorded in the spec, so the same plan always yields the same batches and
node_batches can resume without duplicates. The plan's sha256 is recorded in the node spec (plan_sha256).
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import random

OPTIONAL = {"blocks", "repetition_args"}
REQUIRED = {"campaign_id", "node", "cutoff_utc", "maintenance", "host_condition", "warm", "required_domains",
            "base_args", "families", "arms", "repetitions", "seed", "batch_seconds", "estimated_batch_seconds", "expected"}
EXPECTED = {"repository_revision", "build_manifest", "build_manifest_sha256", "backend_python", "weights_manifest",
            "weights_manifest_sha256", "tool_python", "tool_python_freeze_sha256", "networkx_source", "networkx_commit",
            "cpu_power", "min_free_gib", "lease_end_utc"}
NODE = {"host", "remote_repository", "remote_python", "remote_directory", "node_output", "lock",
        "identity_file", "known_hosts"}
HOST = {"cpu_affinity", "keep_awake_cpus", "tool_cpus", "supervisor_cpus", "idle_cpus"}


def load(path):
    plan = json.loads(Path(path).read_text())
    if set(plan) - OPTIONAL != REQUIRED or set(plan["node"]) != NODE or set(plan["host_condition"]) != HOST \
            or set(plan["expected"]) != EXPECTED:
        raise ValueError("plan fields differ from the frozen plan schema")
    blocks = plan.get("blocks", [0, plan["repetitions"]])
    if not (isinstance(blocks, list) and len(blocks) == 2 and all(type(b) is int for b in blocks)
            and 0 <= blocks[0] < blocks[1] <= plan["repetitions"]):
        raise ValueError("blocks must be [first, stop) within the repetitions")
    if type(plan["repetitions"]) is not int or not 1 <= plan["repetitions"] <= 100:
        raise ValueError("repetitions must be 1..100")
    if not plan["arms"] or not plan["families"]:
        raise ValueError("arms and families are required")
    for flag in ("--output", "--cpu-affinity", "--keep-awake-cpus", "--tool-cpus"):
        if flag in plan["base_args"]:
            raise ValueError(f"{flag} is derived from the plan, not given in base_args")
    # Each batch runs one planned run (--repeats 1), so its planned_run_id and therefore its per-turn sampling
    # seeds are the same in every repetition; sampled repetitions need explicit per-repetition arguments.
    reps = plan.get("repetition_args")
    if reps is not None:
        if not (isinstance(reps, list) and len(reps) == plan["repetitions"]
                and all(isinstance(r, list) and all(isinstance(x, str) for x in r) for r in reps)):
            raise ValueError("repetition_args must hold one argument list per repetition")
        reserved = {"--output", "--cpu-affinity", "--keep-awake-cpus", "--tool-cpus", "--task", "--task-pack",
                    "--task-pack-assets", "--repeats", "--max-runs", "--config", "--policies"}
        if any(x.split("=", 1)[0] in reserved for r in reps for x in r):
            raise ValueError("repetition_args may set decoding and seeds only, not task, arm or output arguments")
    if "--decoding" in " ".join(plan["base_args"]) and reps is None and "sampled" in plan["base_args"]:
        raise ValueError("sampled decoding in base_args would repeat identical seeds; use repetition_args")
    if "--campaign-exit" not in plan["base_args"]:
        raise ValueError("campaign runs require --campaign-exit")
    for family in plan["families"].values():
        for task in family["tasks"]:
            if "task_pack_assets" in task:
                assets = task["task_pack_assets"]
                if not isinstance(assets, str) or not assets.strip():
                    raise ValueError("task_pack_assets must be a nonempty frozen asset directory")
                for args in (plan["base_args"], family["args"], *plan["arms"].values()):
                    if any(arg.split("=", 1)[0] == "--task-pack-assets" for arg in args):
                        raise ValueError("task_pack_assets cannot be overridden by run arguments")
    return plan


def batches(plan):
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    host = plan["host_condition"]
    node = plan["node"]
    py = node["remote_python"]
    out = []
    rng = random.Random(plan["seed"])
    first, stop = plan.get("blocks", [0, plan["repetitions"]])
    for rep in range(stop):
        for family, spec in sorted(plan["families"].items()):
            for task in spec["tasks"]:
                arms = sorted(plan["arms"])
                rng.shuffle(arms)  # drawn for every block so a stage keeps the full plan's orders
                if rep < first:
                    continue
                for arm in arms:
                    ident = f"r{rep:02d}-{family}-{task['short']}-{arm}"
                    run = [py, "-m", "studies.energy_diagnosis.moe.run", *plan["base_args"], *spec["args"],
                           "--task-pack", task["task_pack"], "--task", task["task"],
                           *(["--task-pack-assets", task["task_pack_assets"]] if "task_pack_assets" in task else []),
                           *plan["arms"][arm],
                           *(plan["repetition_args"][rep] if "repetition_args" in plan else []),
                           "--cpu-affinity", host["cpu_affinity"],
                           # An empty keep_awake_cpus declares no keep-awake condition (flag omitted).
                           *(["--keep-awake-cpus", host["keep_awake_cpus"]] if host["keep_awake_cpus"] else []),
                           "--tool-cpus", host["tool_cpus"]]
                    argv = [py, "-m", "studies.energy_diagnosis.diagnostics.campaign_batch",
                            "--root", node["remote_directory"], "--id", ident,
                            "--seconds", str(plan["batch_seconds"]), "--cutoff-utc", plan["cutoff_utc"],
                            "--lock", node["lock"], "--supervisor-cpus", host["supervisor_cpus"],
                            "--idle-cpus", host["idle_cpus"],
                            *[x for w in plan["warm"] for x in ("--warm", w)],
                            *[x for d in plan["required_domains"] for x in ("--required-domain", d)],
                            "--", *run]
                    out.append(dict(id=ident, argv=argv, status=f"{ident}/job/status.json", log=f"logs/{ident}.log",
                                    block=rep, family=family, task=task["task"], arm=arm,
                                    repetition_args=plan["repetition_args"][rep] if "repetition_args" in plan else []))
    return digest, out


def node_spec(plan):
    digest, items = batches(plan)
    node = plan["node"]
    return dict(
        host=node["host"], identity_file=node["identity_file"], known_hosts=node["known_hosts"],
        remote_directory=node["remote_directory"], remote_repository=node["remote_repository"],
        remote_python=node["remote_python"], node_output=node["node_output"], cutoff_utc=plan["cutoff_utc"],
        retry_seconds=60, first_poll_delay_seconds=60,
        minimum_batch_seconds=plan["batch_seconds"] + 180,  # wrapper timeout plus warm-up (~20 s) and audit
        maintenance=plan["maintenance"], plan_sha256=digest,
        batches=[{k: b[k] for k in ("id", "argv", "status", "log")} for b in items],
        schedule=[{k: b[k] for k in ("id", "block", "family", "task", "arm", "repetition_args")} for b in items])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--output")
    p.add_argument("--windows", type=int, help="Print the next N maintenance windows (UTC) and exit")
    a = p.parse_args(argv)
    plan = load(a.plan)
    if a.windows:
        from .batch_coordinator import maintenance_windows
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        inside, start, end = maintenance_windows(dict(maintenance=plan["maintenance"]), now)
        period = plan["maintenance"]["period_seconds"]
        for i in range(a.windows):
            s, e = start + i * period, end + i * period
            print(dt.datetime.fromtimestamp(s, dt.timezone.utc).isoformat(), "->",
                  dt.datetime.fromtimestamp(e, dt.timezone.utc).isoformat(), "(now inside)" if inside and i == 0 else "")
        return 0
    spec = node_spec(plan)
    from .batch_coordinator import validate
    validate(spec)
    Path(a.output).write_text(json.dumps(spec, indent=2) + "\n")
    hours = len(spec["batches"]) * plan["estimated_batch_seconds"] / 3600
    print(json.dumps(dict(batches=len(spec["batches"]), plan_sha256=spec["plan_sha256"],
                          estimated_hours_excluding_windows=round(hours, 1))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
