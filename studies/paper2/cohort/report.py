"""Per-cohort table for a driver output directory (pilot or campaign round); descriptive only.

    python -m studies.paper2.cohort.report OUT [--json OUT/report.json] [--md OUT/report.md]

For each cohort: configuration, step, admission limit, offered tasks, outcomes, verified passes,
energy interval, CPU-package / GPU-board / total joules, joules per verified pass (null without a
pass), wall time per session, server token counts and prefix-cache hit rate over the interval
(differences of the 1 s /metrics samples), preemptions, peak KV-cache usage and peak running /
waiting requests. A paired table lists each task's verdict per configuration for steps that ran on
more than one configuration with the same task ids.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def _metrics(path: Path) -> dict:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    rows = [r["metrics"] for r in rows if r.get("metrics")]
    if not rows:
        return {}

    def delta(k):
        vals = [r[k] for r in rows if k in r]
        return (vals[-1] - vals[0]) if len(vals) >= 2 else None

    def peak(k):
        vals = [r[k] for r in rows if k in r]
        return max(vals) if vals else None

    q, h = delta("vllm:prefix_cache_queries_total"), delta("vllm:prefix_cache_hits_total")
    return dict(prompt_tokens=delta("vllm:prompt_tokens_total"), generation_tokens=delta("vllm:generation_tokens_total"),
                prefix_hit_rate=round(h / q, 3) if q else None, preemptions=delta("vllm:num_preemptions_total"),
                peak_kv_usage=peak("vllm:kv_cache_usage_perc"), peak_running=peak("vllm:num_requests_running"),
                peak_waiting=peak("vllm:num_requests_waiting"), samples=len(rows))


def cohort_rows(out: Path) -> list:
    rows = []
    for summ in sorted(out.glob("cohorts/*/*/cohort-summary.json")):
        s = json.loads(summ.read_text())
        spec = json.loads((summ.parent / "cohort-spec.json").read_text()) if (summ.parent / "cohort-spec.json").exists() else {}
        labels = spec.get("labels", {})
        e = s.get("energy") or {}
        dur = [x["ended_s"] - x["admitted_s"] for x in s["sessions"] if x.get("ended_s") is not None and x.get("admitted_s") is not None]
        rows.append(dict(cohort=s["cohort_id"], config=labels.get("config"), step=labels.get("step"),
                         admission=s.get("admission_limit"), offered=s.get("offered"), outcomes=s.get("outcomes"),
                         verified_pass=s.get("verified_pass"), interval_s=round(e.get("interval_s") or 0, 1),
                         cpu_j=_r(e.get("cpu_package_j")), gpu_j=_r(e.get("gpu_board_j")), total_j=_r(e.get("cpu_plus_gpu_j")),
                         j_per_pass=_r(s.get("joules_per_verified_success")),
                         session_s_median=round(statistics.median(dur), 1) if dur else None,
                         session_s_max=round(max(dur), 1) if dur else None,
                         verdicts={x["task_id"]: x.get("verdict") for x in s["sessions"]},
                         **_metrics(summ.parent.parent / "metrics.jsonl")))
    for summ in sorted(out.glob("cohorts/*/replay-summary.json")) + sorted(out.glob("cohorts/*/*/replay-summary.json")):
        s = json.loads(summ.read_text())
        rows.append(dict(cohort=s.get("cohort_id", summ.parent.name), kind="replay", mismatched_turns=s.get("mismatched_turns"),
                         interval_s=round((s.get("energy") or {}).get("interval_s") or 0, 1),
                         total_j=_r((s.get("energy") or {}).get("cpu_plus_gpu_j"))))
    return rows


def _r(x):
    return None if x is None else round(x)


def paired(rows: list) -> dict:
    by_step: dict = {}
    for r in rows:
        if r.get("step") and r.get("verdicts"):
            by_step.setdefault(r["step"], {})[r["config"]] = r["verdicts"]
    return {step: {t: {c: v.get(t) for c, v in cfgs.items()} for t in sorted(set().union(*cfgs.values()))}
            for step, cfgs in by_step.items() if len(cfgs) > 1}


def markdown(rows: list) -> str:
    cols = ["config", "step", "admission", "offered", "verified_pass", "interval_s", "cpu_j", "gpu_j", "total_j",
            "j_per_pass", "session_s_median", "generation_tokens", "prefix_hit_rate", "preemptions", "peak_kv_usage",
            "peak_running", "peak_waiting"]
    lines = ["| " + " | ".join(cols + ["outcomes"]) + " |", "|" + "---|" * (len(cols) + 1)]
    for r in rows:
        if r.get("kind") == "replay":
            continue
        cells = [str(r.get(c) if not isinstance(r.get(c), float) else round(r[c], 3)) for c in cols]
        lines.append("| " + " | ".join(cells + [json.dumps(r.get("outcomes"))]) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args(argv)
    rows = cohort_rows(a.out)
    rep = dict(out=str(a.out), cohorts=rows, paired=paired(rows))
    (a.json or a.out / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    (a.md or a.out / "report.md").write_text(markdown(rows))
    print(markdown(rows))


if __name__ == "__main__":
    main()
