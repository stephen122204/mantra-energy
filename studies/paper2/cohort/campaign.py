"""Main-run campaign across several nodes: shard a frozen matrix, bind shards to nodes, collect.

    python -m studies.paper2.cohort.campaign shard --base-plan PILOT_PLAN --matrix MATRIX.json \\
        --pilot GPU_CLASS=PILOT_OUT [--pilot ...] --nodes NODES.json --out CAMPAIGN
    python -m studies.paper2.cohort.campaign bind --campaign CAMPAIGN --node NAME --node-report REPORT.json \\
        --allocation LEASE [--gpu-uuid UUID] --out BOUND
    python -m studies.paper2.cohort.campaign collect --campaign CAMPAIGN --results DIR [DIR ...] --out COVERAGE.json

Every node runs every precision configuration on its own GPU (the core comparisons are within one
GPU). Each GPU class (e.g. A100-SXM4-80GB, H100) gets the full matrix of repeats of its own; repeats
are split only among nodes of the same class, never by precision and never across classes. A round
is one driver run on one node: pass 0 = the round's live cohorts on every configuration, pass 1 =
replay of those traces (diagonal and crossed) on every configuration. Block order rotates across a
node's rounds (each configuration first equally often). Paired repeats share task ids, sampling
seeds and pair keys across configurations.

Step durations come only from pilot runs on the same GPU class (``budget.measured``); a class
without its own pilot, or a cell without a measured duration, stops the planner. Evaluation cells
may not contain task ids used by the pilot. Bound plans carry the energy metric the node can
measure (``cpu_package+gpu_board`` or ``gpu_board``); results with different metrics are not pooled.

MATRIX: {"campaign_id", "seed", "contingency": 0.25, "equal_kv": false,
         "task_specs": [...], "extra_catalogs": [...],          # evaluation tasks, added to the base plan's
         "cells": [{"name": "n4", "kind": "live", "admission_limit": 4, "task_ids": [...], "repeats": 6,
                    "measure_as": "n4", "seed": 101, "mode": "fixed", "calibration": false},
                   # optional per cell: "repeats_by_class": {"H100-PCIe": 4}
                   {"name": "xr4", "kind": "replay", "source_cell": "n4", "repeats": 2,
                    "admission_limit": 4, "measure_as": "replay-n4"}]}
NODES: [{"name": "uc-a100-a", "gpu_class": "A100-SXM4-80GB", "available_h": 40}]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from . import budget as budget_mod
from .records import verify_manifest, write_manifest

UNBOUND = "UNBOUND"
BLOCK_SIZE = 16  # vLLM CUDA default KV block size (tokens per block)


def canonical_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def unbound(plan: dict) -> dict:
    p = copy.deepcopy(plan)
    p["gpu_uuid"], p["allocation"] = UNBOUND, UNBOUND
    p.pop("binding", None)
    return p


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=Path(__file__).parent).strip()
    except Exception:
        return "unknown"


def _measurements(pilots: list) -> dict:
    steps, loads, blocks = {}, {}, {}
    for d in pilots:
        m = budget_mod.measured(Path(d))
        for k, v in m["steps"].items():
            steps[k] = max(v, steps.get(k, 0))
        for k, v in m["loads"].items():
            if v is not None:
                loads[k] = max(v, loads.get(k, 0))
        for line in (Path(d) / "driver-events.jsonl").read_text().splitlines():
            e = json.loads(line) if line.strip() else {}
            if e.get("kind") == "server_started":
                st = e.get("started") or {}
                n = st.get("gpu_blocks") or (st.get("kv_cache_tokens") or 0) // BLOCK_SIZE or None
                if n:
                    blocks[e["config"]["name"]] = min(n, blocks.get(e["config"]["name"], n))
    return dict(steps=steps, loads=loads, kv_blocks=blocks)


def _pilot_task_ids(base: dict) -> set:
    ids = set()
    for b in base.get("blocks", {}).values():
        for step in b["steps"]:
            ids.update(next(iter(step.values())).get("task_ids", []))
    for ps in base.get("passes", []):
        for b in ps["blocks"].values():
            for step in b["steps"]:
                ids.update(next(iter(step.values())).get("task_ids", []))
    return ids


def _estimate(meas: dict, config: str, measure_as: str, base_config: str):
    for cfg, how in ((config, "measured"), (base_config, "measured on base config")):
        v = meas["steps"].get(f"{cfg}-{measure_as}")
        if v is not None:
            return v, how
    others = [v for k, v in meas["steps"].items() if k.endswith(f"-{measure_as}")]
    if others:
        return max(others), "slowest measured on another config"
    return None, "unmeasured"


def _rotation(names: list, seed: int, j: int) -> list:
    base = list(names)
    random.Random(seed).shuffle(base)
    k = j % len(base)
    return base[k:] + base[:k]


def shard(base: dict, matrix: dict, meas_by_class: dict, nodes: list, commit: str) -> dict:
    classes = sorted({n["gpu_class"] for n in nodes})
    missing = [c for c in classes if c not in meas_by_class]
    if missing:
        raise SystemExit(f"cannot shard: no pilot measured on GPU class {missing}; each class needs its own pilot")
    out = None
    for gpu_class in classes:
        part = _shard_class(base, matrix, meas_by_class[gpu_class], [n for n in nodes if n["gpu_class"] == gpu_class],
                            commit, gpu_class)
        if out is None:
            out = dict(part, estimate_provenance={}, configs_by_class={}, nodes={})
            out.pop("configs")
        out["estimate_provenance"][gpu_class] = part["estimate_provenance"]
        out["configs_by_class"][gpu_class] = part["configs"]
        out["nodes"].update(part["nodes"])
    return out


def _shard_class(base: dict, matrix: dict, meas: dict, nodes: list, commit: str, gpu_class: str) -> dict:
    matrix = dict(matrix, cells=[dict(c, repeats=c.get("repeats_by_class", {}).get(gpu_class, c["repeats"]))
                                 for c in matrix["cells"]])
    configs = [dict(c) for c in base["configs"]]
    if matrix.get("equal_kv"):
        names = [c["name"] for c in configs]
        missing = [n for n in names if n not in meas["kv_blocks"]]
        if missing:
            raise SystemExit(f"equal-KV control needs measured KV capacity for {missing}")
        common = min(meas["kv_blocks"][n] for n in names)
        configs += [dict(c, name=f"{c['name']}-eqkv", num_gpu_blocks_override=common) for c in configs[:len(names)]]
    base_of = {c["name"]: c["name"].removesuffix("-eqkv") for c in configs}
    tekken = {c["name"]: base["tekken"][base_of[c["name"]]] for c in configs}
    contingency = matrix.get("contingency", 0.25)

    calib = _pilot_task_ids(base)
    problems, provenance = [], {}
    cells = {c["name"]: c for c in matrix["cells"]}
    for c in matrix["cells"]:
        if c.get("kind", "live") == "live" and not c.get("calibration"):
            leaked = sorted(set(c["task_ids"]) & calib)
            if leaked:
                problems.append(f"cell {c['name']}: evaluation cell uses pilot task ids {leaked[:5]}")
        if c.get("kind") == "replay":
            src = cells.get(c["source_cell"])
            if not src or src.get("kind", "live") != "live":
                problems.append(f"cell {c['name']}: source_cell {c['source_cell']} is not a live cell")
            elif c["repeats"] > src["repeats"]:
                problems.append(f"cell {c['name']}: more replay repeats than source repeats")
        for cfg in configs:
            v, how = _estimate(meas, cfg["name"], c["measure_as"], base_of[cfg["name"]])
            provenance[f"{cfg['name']}-{c['name']}"] = how
            if v is None:
                problems.append(f"cell {c['name']}: no measured duration for {cfg['name']}-{c['measure_as']}")
    if problems:
        raise SystemExit(f"cannot shard {gpu_class}:\n  " + "\n  ".join(problems))

    def est(cfg_name, cell):
        return _estimate(meas, cfg_name, cell["measure_as"], base_of[cfg_name])[0] * (1 + contingency)

    load_s = {c["name"]: meas["loads"].get(base_of[c["name"]], base.get("load_est_s", 600)) for c in configs}
    names = [c["name"] for c in configs]
    live = [c for c in matrix["cells"] if c.get("kind", "live") == "live"]
    replays = [c for c in matrix["cells"] if c.get("kind") == "replay"]

    # greedy: each (cell, repeat) unit goes to the node with the lowest committed fraction of its hours
    unit_cost = {c["name"]: sum(est(n, c) for n in names) for c in live}
    load = {n["name"]: 0.0 for n in nodes}
    assign = {n["name"]: [] for n in nodes}
    units = sorted(((c["name"], k) for c in live for k in range(c["repeats"])), key=lambda u: (u[1], u[0]))
    for cell_name, k in units:
        cost = unit_cost[cell_name] + sum(sum(est(n, r) for n in names) * len(names)
                                          for r in replays if r["source_cell"] == cell_name and k < r["repeats"])
        node = min(nodes, key=lambda n: ((load[n["name"]] + cost) / (3600 * n["available_h"]), n["name"]))
        load[node["name"]] += cost
        assign[node["name"]].append((cell_name, k))

    common = {k: base[k] for k in ("isolation", "limits", "sampling", "task_options", "load_est_s", "export_reserve_s",
                                   "cohort_deadline_s", "port", "tool_cpus", "session_cpus") if k in base}
    task_specs = list(base["task_specs"]) + list(matrix.get("task_specs", []))
    catalogs = list(base.get("extra_catalogs", [])) + list(matrix.get("extra_catalogs", []))
    out_nodes = {}
    for node in nodes:
        rounds = []
        per_cell: dict = {}
        for cell_name, k in assign[node["name"]]:
            per_cell.setdefault(cell_name, []).append(k)
        n_rounds = max((len(v) for v in per_cell.values()), default=0)
        for j in range(n_rounds):
            members = [(cn, ks[j]) for cn, ks in sorted(per_cell.items()) if j < len(ks)]
            live_steps, replay_steps, est_s = {n: [] for n in names}, {n: [] for n in names}, 0.0
            for cn, k in members:
                c = cells[cn]
                for n in names:
                    step = dict(name=f"{cn}-r{k}", admission_limit=c["admission_limit"], task_ids=c["task_ids"],
                                mode=c.get("mode", "fixed"), seed=c.get("seed", 0) * 1000 + k, est_s=round(est(n, c)))
                    for opt in ("arrival_offsets_s", "cohort_deadline_s"):
                        if opt in c:
                            step[opt] = c[opt]
                    live_steps[n].append({"live": step})
                    est_s += est(n, c)
                for r in replays:
                    if r["source_cell"] != cn or k >= r["repeats"]:
                        continue
                    for target in names:
                        for src in names:
                            replay_steps[target].append({"replay": dict(
                                name=f"{r['name']}-{src}-r{k}", source=f"{src}/{cn}-r{k}",
                                admission_limit=r.get("admission_limit", c["admission_limit"]), est_s=round(est(target, r)))})
                            est_s += est(target, r)
            seed = int(canonical_sha([matrix.get("seed", 0), node["name"]])[:8], 16)
            passes = [dict(blocks={n: dict(steps=live_steps[n]) for n in names}, order=_rotation(names, seed, j))]
            if any(replay_steps.values()):
                passes.append(dict(blocks={n: dict(steps=replay_steps[n]) for n in names}, order=_rotation(names, seed + 1, j)))
            est_s += sum(load_s.values()) * len(passes)
            plan = dict(common, version="paper2-campaign-v1", gpu_uuid=UNBOUND, allocation=UNBOUND, block_seed=seed,
                        configs=configs, passes=passes, tekken=tekken, task_specs=task_specs, extra_catalogs=catalogs,
                        campaign=dict(campaign_id=matrix["campaign_id"], node=node["name"], gpu_class=node["gpu_class"],
                                      round=j, units=[f"{cn}-r{k}" for cn, k in members], commit=commit))
            rounds.append(dict(plan=plan, est_h=round(est_s / 3600, 2)))
        total = round(sum(r["est_h"] for r in rounds) + matrix.get("export_h", 1.0), 2)
        out_nodes[node["name"]] = dict(gpu_class=node["gpu_class"], available_h=node["available_h"], rounds=rounds,
                                       est_total_h=total, fits=total <= node["available_h"])
    return dict(campaign_id=matrix["campaign_id"], commit=commit, matrix_sha256=canonical_sha(matrix),
                configs=[c["name"] for c in configs], estimate_provenance=provenance, contingency=contingency,
                nodes=out_nodes)


def cmd_shard(a) -> int:
    base = json.loads(a.base_plan.read_text())
    matrix = json.loads(a.matrix.read_text())
    nodes = json.loads(a.nodes.read_text())
    by_class: dict = {}
    for item in a.pilot:
        gpu_class, _, d = item.partition("=")
        if not d:
            raise SystemExit(f"--pilot expects GPU_CLASS=DIR, got {item}")
        by_class.setdefault(gpu_class, []).append(d)
    meas = {c: _measurements(ds) for c, ds in by_class.items()}
    res = shard(base, matrix, meas, nodes, a.commit or _git_head())
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "matrix.json").write_text(json.dumps(matrix, indent=1))
    (a.out / "nodes.json").write_text(json.dumps(nodes, indent=1))
    (a.out / "measured.json").write_text(json.dumps(meas, indent=1))
    manifest = {k: v for k, v in res.items() if k != "nodes"}
    manifest["nodes"] = {}
    for name, nd in res["nodes"].items():
        (a.out / name).mkdir()
        rows = []
        for r in nd["rounds"]:
            f = a.out / name / f"round-{r['plan']['campaign']['round']:02d}.json"
            f.write_text(json.dumps(r["plan"], indent=1))
            rows.append(dict(file=f.relative_to(a.out).as_posix(), plan_sha256=canonical_sha(r["plan"]), est_h=r["est_h"],
                             units=r["plan"]["campaign"]["units"]))
        manifest["nodes"][name] = dict({k: v for k, v in nd.items() if k != "rounds"}, rounds=rows)
    (a.out / "campaign-manifest.json").write_text(json.dumps(manifest, indent=1))
    write_manifest(a.out)
    print(json.dumps({n: dict(rounds=len(v["rounds"]), est_total_h=v["est_total_h"], available_h=v["available_h"],
                              fits=v["fits"]) for n, v in manifest["nodes"].items()}, indent=1))
    return 0 if all(v["fits"] for v in manifest["nodes"].values()) else 2


def _load_campaign(path: Path) -> dict:
    problems = verify_manifest(path)
    if problems:
        raise SystemExit(f"campaign directory altered: {problems}")
    return json.loads((path / "campaign-manifest.json").read_text())


def bind(manifest: dict, campaign: Path, node: str, report: dict, allocation: str, gpu_uuid: str = None) -> tuple:
    nd = manifest["nodes"][node]
    devices = (report.get("gpus") or {}).get("devices", []) if isinstance(report.get("gpus"), dict) else []
    match = [d for d in devices if nd["gpu_class"].lower() in str(d.get("name", "")).lower()]
    if gpu_uuid:
        match = [d for d in match if d.get("uuid") == gpu_uuid]
    if len(match) != 1:
        raise SystemExit(f"node {node}: need exactly one {nd['gpu_class']} GPU (found {[d.get('name') for d in devices]}); "
                         "pass --gpu-uuid on multi-GPU nodes")
    dev = match[0]
    verdict = report.get("verdict", {})
    if not verdict.get("gpu_energy_counter"):
        raise SystemExit(f"node {node}: GPU energy counter not advancing")
    cpu = bool(verdict.get("cpu_package_counters"))
    metric = "cpu_package+gpu_board" if cpu else "gpu_board"
    warnings = [] if cpu else ["no readable CPU-package counters: results are labelled gpu_board energy"]
    report_sha = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    bound = []
    for row in nd["rounds"]:
        plan = json.loads((campaign / row["file"]).read_text())
        if canonical_sha(plan) != row["plan_sha256"]:
            raise SystemExit(f"{row['file']} does not match the campaign manifest")
        plan["gpu_uuid"], plan["allocation"] = dev["uuid"], allocation
        plan["binding"] = dict(plan_sha256=row["plan_sha256"], node_report_sha256=report_sha, host=report.get("host"),
                               gpu_name=dev.get("name"), energy_metric=metric, warnings=warnings)
        bound.append((Path(row["file"]).name, plan))
    return bound, warnings


def cmd_bind(a) -> int:
    manifest = _load_campaign(a.campaign)
    bound, warnings = bind(manifest, a.campaign, a.node, json.loads(a.node_report.read_text()), a.allocation, a.gpu_uuid)
    a.out.mkdir(parents=True, exist_ok=False)
    for fname, plan in bound:
        (a.out / fname).write_text(json.dumps(plan, indent=1))
    write_manifest(a.out)
    print(json.dumps(dict(node=a.node, rounds=len(bound), warnings=warnings, out=str(a.out))))
    return 0


def collect(manifest: dict, results: list) -> dict:
    expected = {}
    for node, nd in manifest["nodes"].items():
        for row in nd["rounds"]:
            expected[row["plan_sha256"]] = dict(node=node, file=row["file"], runs=[])
    stray = []
    for d in map(Path, results):
        rec = dict(dir=str(d), problems=[])
        if not (d / "SHA256SUMS").exists():
            rec["problems"].append("no SHA256SUMS (run did not finish)")
        else:
            rec["problems"] += verify_manifest(d)
        plan = json.loads((d / "plan.json").read_text())
        sha = (plan.get("binding") or {}).get("plan_sha256")
        if sha not in expected or canonical_sha(unbound(plan)) != sha:
            stray.append(dict(rec, reason="plan is not a round of this campaign"))
            continue
        ev = [json.loads(l) for l in (d / "driver-events.jsonl").read_text().splitlines() if l.strip()]
        start = next((e for e in ev if e["kind"] == "driver_start"), {})
        if start.get("revision") != manifest["commit"]:
            rec["problems"].append(f"ran commit {start.get('revision')}, campaign frozen at {manifest['commit']}")
        if start.get("dirty"):
            rec["problems"].append("dirty checkout")
        if start.get("retry_of") and not str(start.get("retry_reason") or "").startswith("infra:"):
            rec["problems"].append("retry without an infrastructure reason")
        rec.update(complete=any(e["kind"] == "driver_end" for e in ev), retry_of=start.get("retry_of"),
                   retry_reason=start.get("retry_reason"), energy_metric=start.get("energy_metric"),
                   configuration_failures=[dict(kind=e["kind"], config=e["config"], step=e.get("step"), error=e.get("error"),
                                                returncode=e.get("returncode"))
                                           for e in ev if e["kind"] in ("server_start_failed", "server_died")],
                   done=sorted(e["step"] for e in ev if e["kind"] == "step_done"),
                   skipped=[dict(step=e["step"], reason=e["reason"]) for e in ev if e["kind"] == "step_skipped"],
                   blocks_skipped=[e["config"] for e in ev if e["kind"] == "block_skipped"])
        expected[sha]["runs"].append(rec)
    rounds = []
    for sha, x in expected.items():
        good = [r for r in x["runs"] if r.get("complete") and not r["problems"]]
        status = "missing" if not x["runs"] else "ok" if len(good) == 1 else "conflict" if len(good) > 1 else "incomplete"
        if status == "ok" and (good[0]["skipped"] or good[0]["blocks_skipped"]):
            status = "partial"
        rounds.append(dict(x, plan_sha256=sha, status=status, counted=good[0]["dir"] if len(good) == 1 else None))
    summary = {s: sum(r["status"] == s for r in rounds) for s in ("ok", "partial", "incomplete", "conflict", "missing")}
    metrics: dict = {}
    for r in rounds:
        if r["counted"]:
            run = next(x for x in r["runs"] if x["dir"] == r["counted"])
            metrics.setdefault(manifest["nodes"][r["node"]]["gpu_class"], set()).add(run["energy_metric"])
    return dict(campaign_id=manifest["campaign_id"], summary=summary, rounds=rounds, stray=stray,
                energy_metric_by_class={k: sorted(v) for k, v in metrics.items()},
                mixed_energy_metrics=[k for k, v in metrics.items() if len(v) > 1],
                note="checksums establish integrity against the recorded manifests, not correctness of the experiment")


def cmd_collect(a) -> int:
    manifest = _load_campaign(a.campaign)
    cov = collect(manifest, a.results)
    a.out.write_text(json.dumps(cov, indent=1))
    print(json.dumps(cov["summary"]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--base-plan", type=Path, required=True)
    s.add_argument("--matrix", type=Path, required=True)
    s.add_argument("--pilot", action="append", required=True, help="GPU_CLASS=PILOT_OUT (repeatable)")
    s.add_argument("--nodes", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--commit", help="commit the nodes will run (default: this checkout's HEAD)")
    b = sub.add_parser("bind")
    b.add_argument("--campaign", type=Path, required=True)
    b.add_argument("--node", required=True)
    b.add_argument("--node-report", type=Path, required=True)
    b.add_argument("--allocation", required=True)
    b.add_argument("--gpu-uuid")
    b.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("collect")
    c.add_argument("--campaign", type=Path, required=True)
    c.add_argument("--results", type=Path, nargs="+", required=True)
    c.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    return dict(shard=cmd_shard, bind=cmd_bind, collect=cmd_collect)[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
