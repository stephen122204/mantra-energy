#!/usr/bin/env python3
"""Generate planning records only. Never connects to hardware or executes workloads."""

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def task_inventory(cfg):
    result = defaultdict(list)
    for family in cfg["task_families"]:
        for split in ("pilot", "development", "heldout"):
            for number in range(1, family[f"{split}_instances"] + 1):
                result[split].append((f"{family['id']}_{split}_{number:03d}", family["id"]))
    return result


def readiness(cfg, inventory):
    missing = []
    for group in ("runtime", "hardware", "protocol"):
        for key, value in cfg[group].items():
            if value is None or value is False or value == "" or value == "TO_BE_VALIDATED":
                missing.append(f"{group}.{key}")
    assets = cfg["task_assets"]
    for split_tasks in inventory.values():
        for task_id, _ in split_tasks:
            absent = [key for key in cfg["task_asset_required_fields"] if not assets.get(task_id, {}).get(key)]
            if absent:
                missing.append(f"task_assets.{task_id}: {', '.join(absent)}")
    return missing


def make_plan(cfg, inventory):
    rng = random.Random(cfg["randomization_seed"])
    rows = []
    candidates = {item["id"]: item for item in cfg["candidates"]}
    if len(candidates) != len(cfg["candidates"]):
        raise ValueError("Candidate IDs must be unique")
    if cfg["reference_candidate"] not in candidates:
        raise ValueError("Reference candidate is missing")

    def stage(name, split, variants, repetitions, mode):
        for rep in range(1, repetitions + 1):
            tasks = list(inventory[split])
            rng.shuffle(tasks)
            for task_id, family in tasks:
                order = list(variants)
                rng.shuffle(order)
                for variant in order:
                    # Query order within an adaptive selector must remain sequential.
                    queries = range(1, cfg["profiling_queries_per_selector"] + 1) if mode == "profile" else [0]
                    for query in queries:
                        cid = variant if mode in ("replay", "capture") else "UNRESOLVED"
                        candidate = candidates.get(cid, {})
                        rows.append({
                            "run_id": f"planned_{len(rows) + 1:05d}",
                            "stage": name, "mode": mode, "split": split,
                            "task_id": task_id, "family": family,
                            "session_slot": f"{name}_r{rep}",
                            "block_id": f"{name}_{task_id}_r{rep}",
                            "repetition": rep, "variant": variant,
                            "query_index": query or "", "candidate_id": cid,
                            "tool_concurrency": candidate.get("tool_concurrency", ""),
                            "workers_per_tool": candidate.get("workers_per_tool", ""),
                            "reference_trace_id": "" if mode in ("capture", "live") else f"trace_{task_id}",
                            "status": "planned", "actual_reservation_id": "",
                            "actual_execution_id": ""
                        })

    ref = [cfg["reference_candidate"]]
    rep = cfg["repetitions"]
    stage("pilot_capture", "pilot", ref, 1, "capture")
    stage("pilot_replay", "pilot", list(candidates), rep, "replay")
    stage("development_capture", "development", ref, 1, "capture")
    stage("development_replay", "development", list(candidates), rep, "replay")
    stage("heldout_capture", "heldout", ref, 1, "capture")
    stage("decision_profile", "heldout", cfg["budgeted_selectors"], 1, "profile")
    stage("reference_replay", "heldout", list(candidates), rep, "replay")
    stage("live_verification", "heldout", cfg["live_policies"], rep, "live")
    return rows


def validate_plan(cfg, inventory, rows):
    """Check scientific scheduling invariants, not empirical validity."""
    ids = [row["run_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate run IDs")
    all_tasks = [task for group in inventory.values() for task, _ in group]
    if len(all_tasks) != len(set(all_tasks)):
        raise ValueError("Task IDs overlap between splits/families")
    blocks = defaultdict(list)
    for row in rows:
        blocks[row["block_id"]].append(row)
        if row["mode"] in ("profile", "live") and row["candidate_id"] != "UNRESOLVED":
            raise ValueError("Planner must not fabricate adaptive decisions")
        if row["status"] != "planned" or row["actual_execution_id"]:
            raise ValueError("Planning records must not assert execution")
    required = Counter(c["id"] for c in cfg["candidates"])
    for block in blocks.values():
        if block[0]["mode"] == "replay" and Counter(r["candidate_id"] for r in block) != required:
            raise ValueError("Replay block is not a complete candidate comparison")
        if block[0]["mode"] == "profile":
            for selector in cfg["budgeted_selectors"]:
                queries = [r["query_index"] for r in block if r["variant"] == selector]
                if queries != list(range(1, cfg["profiling_queries_per_selector"] + 1)):
                    raise ValueError("Adaptive profiling query order/budget is invalid")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("campaign.json"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("generated"))
    parser.add_argument("--require-ready", action="store_true", help="Fail on missing declaration fields; still never executes anything")
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    cfg = json.loads(raw)
    inventory = task_inventory(cfg)
    rows = make_plan(cfg, inventory)
    validate_plan(cfg, inventory, rows)
    missing = readiness(cfg, inventory)
    report = {
        "artifact_type": "planning_only_no_experimental_results",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "randomization_seed": cfg["randomization_seed"],
        "planned_executions": len(rows),
        "counts_by_stage": dict(Counter(r["stage"] for r in rows)),
        "task_counts": {split: len(tasks) for split, tasks in inventory.items()},
        "assumed_mean_minutes": cfg["planning_mean_minutes_per_execution"],
        "estimated_active_node_hours": round(len(rows) * cfg["planning_mean_minutes_per_execution"] / 60, 2),
        "excluded_work": cfg["excluded_from_primary_count"],
        "schedule_integrity_checks": "passed",
        "declaration_fields_complete": not missing,
        "missing_declaration_fields": missing,
        "limits": "Field presence does not verify assets, hashes, reservations, permissions, statistical power, scientific gates, or actual runtime readiness. Session slots require mapping to real sessions. Adaptive decisions are unresolved."
    }
    if args.require_ready and missing:
        print(json.dumps({"ready": False, "missing_count": len(missing), "reason": "Manifest remains a planning template"}, indent=2))
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "run-plan.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "planning-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("planned_executions", "counts_by_stage", "estimated_active_node_hours", "schedule_integrity_checks", "declaration_fields_complete")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
