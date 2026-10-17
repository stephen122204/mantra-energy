"""Device-hour budget for a main run from measured pilot durations (no assumed speedups).

    python -m studies.paper2.cohort.budget --pilot PILOT_OUT --matrix MATRIX.json [--available-h H]

MATRIX: {"contingency": 0.25, "export_h": 1.0,
         "cells": [{"config": "devstral-w4a16", "step": "n4", "repeats": 5}, ...],
         "server_loads_per_config": 5}
Each cell's duration is the slowest measured duration of that (config, step) in the pilot; a
cell whose step was never measured is reported as unmeasured instead of extrapolated. Verifier
time (CPU, after intervals) is summed separately from GPU-interval time.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def measured(pilot: Path) -> dict:
    ev = [json.loads(l) for l in (pilot / "driver-events.jsonl").read_text().splitlines() if l.strip()]
    steps = {e["step"]: e["seconds"] for e in ev if e["kind"] == "step_done"}
    loads = {e["config"]["name"]: e["started"].get("load_s") for e in ev if e["kind"] == "server_started"}
    verify_s: dict = {}
    for summ in pilot.glob("cohorts/*/*/cohort-summary.json"):
        cohort = summ.parent
        total = 0.0
        for v in cohort.glob("sessions/*/verification.json"):
            d = json.loads(v.read_text())
            total += max(0.0, d.get("t_end", 0) - d.get("t_start", 0))
        verify_s[cohort.name] = round(total, 1)
    skipped = [dict(step=e["step"], reason=e["reason"]) for e in ev if e["kind"] == "step_skipped"]
    return dict(steps=steps, loads=loads, verify_s=verify_s, skipped=skipped)


def budget(m: dict, matrix: dict, available_h: float = None) -> dict:
    rows, unmeasured, gpu_s, verify_s = [], [], 0.0, 0.0
    for c in matrix["cells"]:
        key = f"{c['config']}-{c['step']}"
        if key not in m["steps"]:
            unmeasured.append(key)
            continue
        s = m["steps"][key] * c["repeats"]
        v = m["verify_s"].get(key, 0.0) * c["repeats"]
        gpu_s += s
        verify_s += v
        rows.append(dict(cell=key, repeats=c["repeats"], cohort_s=m["steps"][key], total_h=round(s / 3600, 2),
                         verify_h=round(v / 3600, 2)))
    loads = sum((m["loads"].get(cfg) or 0) for cfg in {c["config"] for c in matrix["cells"]}) * matrix.get("server_loads_per_config", 1)
    total_h = (gpu_s + verify_s + loads) / 3600 * (1 + matrix.get("contingency", 0.25)) + matrix.get("export_h", 1.0)
    out = dict(cells=rows, unmeasured=unmeasured, gpu_interval_h=round(gpu_s / 3600, 2), verify_cpu_h=round(verify_s / 3600, 2),
               server_load_h=round(loads / 3600, 2), contingency=matrix.get("contingency", 0.25),
               export_h=matrix.get("export_h", 1.0), total_reserved_h=round(total_h, 2))
    if available_h is not None:
        out["available_h"] = available_h
        out["fits"] = total_h <= available_h and not unmeasured
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=Path, required=True)
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--available-h", type=float)
    a = ap.parse_args(argv)
    m = measured(a.pilot)
    print(json.dumps(dict(measured=m, budget=budget(m, json.loads(a.matrix.read_text()), a.available_h)), indent=1))


if __name__ == "__main__":
    main()
