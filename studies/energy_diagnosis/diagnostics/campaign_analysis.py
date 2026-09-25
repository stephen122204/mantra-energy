"""Frozen campaign analysis (every attempt retained; nothing excluded by outcome).

    python -m studies.energy_diagnosis.diagnostics.campaign_analysis --stage NODE_SPEC.json RESULTS_DIR [--stage ...]

Several collection stages (e.g. a pre-specified stage 2 with its own spec and results root) are
analysed together as one schedule.

Unit: one batch = one attempt of (repetition block, task, arm). Validity is the protocol-only
acceptance (campaign_batch acceptance.json); invalid attempts are counted and listed, never
dropped silently, and excluded only from contrasts and energy-per-success.

Per task and arm: attempts, valid attempts, successes (independent verifier pass), success rate with
a Wilson 95% interval, mean time and energy per valid attempt (outer goal window; per domain and the
sum of the non-overlapping CPU-package and GPU-board domains), and energy per successful goal
(EpSG) = total energy of all valid attempts / successes, so failed attempts are charged to the
successes they did not produce. EpSG is undefined (None, with the reason) when there are zero
successes; it is never imputed.

Paired contrasts: for each repetition block r and task t, d = Y(arm) - Y(A) for both-valid pairs,
also relative to Y(A). Per task: mean, SD, n and a t-based 95% interval (df = n - 1). Family: the
mean of task means with SE = sqrt(sum s_t^2 / n_t) / T and Welch-Satterthwaite df. This is
inference about these fixed tasks under this configuration, not about a population of workloads.
Pairs whose model requests differ from A (live divergence) are flagged; the primary estimate uses
fixed-work pairs and an all-pairs estimate is reported alongside.
"""
import argparse
import json
import math
from pathlib import Path

DOMAINS = ("PACKAGE_SOCKET_0", "PACKAGE_SOCKET_1", "GPU_BOARD_0")
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000}


def t975(df):
    """Two-sided 95% Student t quantile (table with conservative lookup: nearest lower df)."""
    if df is None or df < 1:
        return None
    keys = sorted(k for k in T975 if k <= df)
    return T975[keys[-1]] if keys else None


def wilson(successes, n, z=1.96):
    if n == 0:
        return None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def summary(values):
    n = len(values)
    if n == 0:
        return dict(n=0, mean=None, sd=None, ci95=None)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else None
    q = t975(n - 1)
    half = q * sd / math.sqrt(n) if sd is not None and q else None
    return dict(n=n, mean=mean, sd=sd, ci95=[mean - half, mean + half] if half is not None else None,
                half_width=half)


def family(task_summaries):
    rows = [s for s in task_summaries if s["n"] > 1 and s["sd"] is not None]
    dropped = sorted(s.get("task") for s in task_summaries if s not in rows)
    if not rows:
        return dict(tasks=0, mean=None, ci95=None, half_width=None, dropped_tasks=dropped)
    T = len(rows)
    mean = sum(s["mean"] for s in rows) / T
    var_terms = [s["sd"] ** 2 / s["n"] for s in rows]
    se = math.sqrt(sum(var_terms)) / T
    denom = sum(v * v / (s["n"] - 1) for v, s in zip(var_terms, rows))
    df = (sum(var_terms) ** 2 / denom) if denom > 0 else None
    q = t975(math.floor(df)) if df else None
    half = q * se if q else None
    return dict(tasks=T, mean=mean, se=se, df=df, ci95=[mean - half, mean + half] if half else None,
                half_width=half, dropped_tasks=dropped,
                scope="these fixed tasks under this configuration; not a workload population")


def outcome_counts(rows):
    """Verifier outcome by execution status, e.g. unavailable after context exhaustion vs a crash."""
    keys = sorted({(r.get("verifier_outcome"), r.get("execution_status")) for r in rows}, key=str)
    return [dict(verifier=v, execution=e, count=sum(1 for r in rows
                 if (r.get("verifier_outcome"), r.get("execution_status")) == (v, e))) for v, e in keys]


def load_attempt(batch_dir):
    acc_path = batch_dir / "acceptance.json"
    acc = json.loads(acc_path.read_text()) if acc_path.exists() else {}
    job_path = batch_dir / "job/status.json"
    job = json.loads(job_path.read_text()).get("status") if job_path.exists() else None
    records = list((batch_dir / "campaign/goals").glob("*/record.json"))
    row = dict(protocol_valid=bool(acc.get("protocol_valid")) and job == "completed"
               and not (batch_dir / "recovery.json").exists(),
               present=bool(records), job_status=job, recovered=(batch_dir / "recovery.json").exists())
    if len(records) != 1:
        row.update(protocol_valid=False, reason="missing or multiple goal records")
        return row
    goal = records[0].parent
    rec = json.loads(records[0].read_text())
    energy = {m["domain_id"]: m["energy_j"] for m in rec["measurements"]
              if m.get("status") == "valid" and m.get("energy_j") is not None}
    calls = json.loads((goal / "model-calls.json").read_text()) if (goal / "model-calls.json").exists() else []
    row.update(success=rec["verifier"]["outcome"] == "pass", verifier_outcome=rec["verifier"]["outcome"],
               execution_status=rec["execution_status"],
               seconds=(rec["ended_ns"] - rec["started_ns"]) / 1e9,
               energy_j={d: energy.get(d) for d in DOMAINS},
               total_j=sum(energy[d] for d in DOMAINS) if all(d in energy for d in DOMAINS) else None,
               requests=[json.dumps(c.get("request"), sort_keys=True) for c in calls])
    if row["total_j"] is None:
        row.update(protocol_valid=False, reason="missing energy domain")
    return row


def analyze(spec, results=None, stages=None):
    """stages: [(spec, results_root), ...]; (spec, results) is a single stage."""
    stages = stages or [(spec, results)]
    schedule = {}
    for stage_spec, root in stages:
        for s in stage_spec["schedule"]:
            if s["id"] in schedule:
                raise ValueError(f"batch {s['id']} appears in more than one stage")
            schedule[s["id"]] = (s, root)
    attempts = {}
    for ident, (meta, root) in schedule.items():
        batch = Path(root) / ident
        row = dict(meta, finished=batch.exists())
        if batch.exists():
            row.update(load_attempt(batch))
        attempts[ident] = row
    by_cell = {}
    for row in attempts.values():
        by_cell.setdefault((row["task"], row["arm"]), []).append(row)
    cells = []
    for (task, arm), rows in sorted(by_cell.items()):
        done = [r for r in rows if r["finished"]]
        valid = [r for r in done if r.get("protocol_valid")]
        successes = sum(1 for r in valid if r.get("success"))
        total = sum(r["total_j"] for r in valid)
        cells.append(dict(
            task=task, arm=arm, planned=len(rows), attempts=len(done), valid=len(valid),
            invalid=[r["id"] for r in done if not r.get("protocol_valid")],
            successes=successes, success_rate=successes / len(valid) if valid else None,
            success_rate_wilson95=wilson(successes, len(valid)),
            time_per_attempt_s=summary([r["seconds"] for r in valid]),
            energy_per_attempt_j=summary([r["total_j"] for r in valid]),
            energy_per_attempt_by_domain_j={d: summary([r["energy_j"][d] for r in valid]) for d in DOMAINS},
            energy_per_successful_goal_j=(total / successes) if successes else None,
            energy_per_successful_goal_note=None if successes else
            ("no valid attempts" if not valid else "zero successes: undefined, not imputed"),
            energy_of_failed_attempts_j=sum(r["total_j"] for r in valid if not r.get("success")),
            outcomes=outcome_counts(valid)))
    contrasts = {}
    arms = sorted({r["arm"] for r in attempts.values()} - {"A"})
    tasks = sorted({r["task"] for r in attempts.values()})
    families = {}
    for r in attempts.values():
        families.setdefault(r["family"], set()).add(r["task"])
    for arm in arms:
        for metric in ("total_j", "seconds"):
            per_task, per_task_all = [], []
            for task in tasks:
                fixed, every, absolute = [], [], []
                for block in sorted({r["block"] for r in attempts.values()}):
                    a = next((r for r in attempts.values() if (r["task"], r["arm"], r["block"]) == (task, "A", block)), None)
                    b = next((r for r in attempts.values() if (r["task"], r["arm"], r["block"]) == (task, arm, block)), None)
                    if not (a and b and a.get("protocol_valid") and b.get("protocol_valid")):
                        continue
                    rel = 100.0 * (b[metric] - a[metric]) / a[metric]
                    every.append(rel)
                    if a["requests"] == b["requests"]:
                        fixed.append(rel)
                        absolute.append(b[metric] - a[metric])
                s = dict(summary(fixed), task=task, pairs_all=len(every), live_divergent=len(every) - len(fixed),
                         absolute=summary(absolute))
                per_task.append(s)
                per_task_all.append(dict(summary(every), task=task))
            fam = {f: family([s for s in per_task if s["task"] in ts]) for f, ts in families.items()}
            fam_all = {f: family([s for s in per_task_all if s["task"] in ts]) for f, ts in families.items()}
            contrasts[f"{arm}-A:{metric}"] = dict(unit="percent of A", per_task_fixed_work=per_task,
                                                  per_task_all_pairs=per_task_all, family_fixed_work=fam,
                                                  family_all_pairs=fam_all)
    return dict(attempts_planned=len(attempts), attempts_finished=sum(r["finished"] for r in attempts.values()),
                cells=cells, contrasts=contrasts,
                invalid_attempts=sorted(r["id"] for r in attempts.values() if r["finished"] and not r.get("protocol_valid")))


def precision_gate(analysis, per_task_limit=1.0, family_limit=0.5, metric="total_j"):
    """Stage-2 rule (precision only, never the sign or size of an effect): True if any primary energy
    contrast has a per-task 95% half-width above per_task_limit or a family half-width above
    family_limit (percent of A), or cannot be computed."""
    reasons = []
    for name, c in analysis["contrasts"].items():
        if not name.endswith(metric):
            continue
        for s in c["per_task_fixed_work"]:
            if s.get("half_width") is None or s["half_width"] > per_task_limit:
                reasons.append(f"{name} {s['task']}: half-width {s.get('half_width')}")
        for fam, f in c["family_fixed_work"].items():
            if f.get("half_width") is None or f["half_width"] > family_limit:
                reasons.append(f"{name} family {fam}: half-width {f.get('half_width')}")
    return dict(extend=bool(reasons), reasons=reasons)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", nargs=2, action="append", required=True, metavar=("NODE_SPEC", "RESULTS_DIR"))
    p.add_argument("--output")
    a = p.parse_args(argv)
    result = analyze(None, stages=[(json.loads(Path(sp).read_text()), root) for sp, root in a.stage])
    result["stage2_precision_gate"] = precision_gate(result)
    text = json.dumps(result, indent=1)
    if a.output:
        Path(a.output).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
