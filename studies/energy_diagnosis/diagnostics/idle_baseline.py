"""Idle power baseline per energy domain (upstream A-LEMS protocol: repeated windows, 2-sigma filter).

Reads the same counters as goal measurement (RAPL packages and DRAM where exposed, NVML GPU board)
through NodeCounterReader, so baselines and goals share domains and units. Each window is the counter
difference over ``--seconds``; the reported baseline per domain is the mean of windows whose total
power lies within 2 standard deviations of the mean total.

Conditions:
  node idle           nothing started (default)
  model loaded, idle  ``--hold-cmd`` starts an engine; measurement begins once ``--ready-url`` answers
                      200 (or after ``--ready-seconds``), and the process group is killed afterwards.
Run it before and after a block to bound drift. It does not change any host setting.
"""
import argparse
import json
import math
import os
import signal
import statistics as st
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ..runtime.node_measurement import NodeCounterReader


def _ranges(reader):
    out = {}
    for key, path in reader.rapl.available_paths.items():
        try:
            out[key] = int((Path(path).parent / "max_energy_range_uj").read_text())
        except (OSError, ValueError):
            out[key] = None
    return out


def _delta(a, b, wrap):
    if a is None or b is None:
        return None
    d = b - a
    if d < 0:
        if not wrap:
            return None
        d += wrap + 1
    return d


def measure(reader, windows, seconds):
    names = {d.domain_id: d.canonical_name for d in reader.get_measurement_schema().domains}
    wraps = _ranges(reader)
    rows = []
    for _ in range(windows):
        t0, e0 = time.monotonic_ns(), reader.read_energy()
        time.sleep(seconds)
        t1, e1 = time.monotonic_ns(), reader.read_energy()
        dt = (t1 - t0) / 1e9
        watts = {}
        for key in e1:
            d = _delta(e0.get(key), e1.get(key), wraps.get(key))
            watts[names.get(key, key)] = None if d is None else d / 1e6 / dt
        rows.append(dict(seconds=dt, watts=watts))
    totals = [sum(v for v in r["watts"].values() if v is not None) for r in rows]
    mu, sd = st.mean(totals), (st.stdev(totals) if len(totals) > 1 else 0.0)
    kept = [r for r, t in zip(rows, totals) if abs(t - mu) <= 2 * sd or sd == 0]
    domains = sorted({k for r in rows for k in r["watts"]})
    baseline = {}
    for d in domains:
        vals = [r["watts"][d] for r in kept if r["watts"].get(d) is not None]
        baseline[d] = dict(mean_w=st.mean(vals) if vals else None,
                           sd_w=st.stdev(vals) if len(vals) > 1 else None, n=len(vals))
    return dict(windows=rows, kept=len(kept), total_mean_w=mu, total_sd_w=sd,
                baseline_w=baseline, total_baseline_w=sum(v["mean_w"] for v in baseline.values() if v["mean_w"]))


def _ready(url, deadline, proc):
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"held process exited (rc={proc.returncode})")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise TimeoutError("held process did not become ready")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--windows", type=int, default=10)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--gpu-index", type=int, default=0)
    p.add_argument("--hold-cmd", help="Shell command to start and hold during measurement (model loaded, idle)")
    p.add_argument("--ready-url")
    p.add_argument("--ready-seconds", type=float, default=0.0)
    p.add_argument("--ready-timeout", type=float, default=900.0)
    p.add_argument("--settle-seconds", type=float, default=30.0, help="Wait after readiness before measuring")
    a = p.parse_args(argv)
    reader = NodeCounterReader(a.gpu_index)
    held = None
    try:
        if a.hold_cmd:
            held = subprocess.Popen(a.hold_cmd, shell=True, start_new_session=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if a.ready_url:
                _ready(a.ready_url, time.monotonic() + a.ready_timeout, held)
            time.sleep(a.ready_seconds + a.settle_seconds)
        started = time.time()
        result = measure(reader, a.windows, a.seconds)
        state = reader.read_operating_state() if hasattr(reader, "read_operating_state") else None
        placement = None
        if held is not None:
            from ..moe.stock_engine import numa_placement
            placement = numa_placement(held.pid)
        record = dict(version="idle-baseline-v1", label=a.label, started_unix=started, protocol=dict(
            windows=a.windows, seconds=a.seconds, filter="total power within 2 sd of mean"),
            hold_cmd=a.hold_cmd, held_placement=placement, operating_state=state, **result)
        Path(a.output).write_text(json.dumps(record, indent=2, default=str) + "\n")
        print(json.dumps(dict(label=a.label, total_baseline_w=round(result["total_baseline_w"], 1),
                              by_domain={k: round(v["mean_w"], 1) for k, v in result["baseline_w"].items()
                                         if v["mean_w"] is not None}, kept=result["kept"])))
    finally:
        if held is not None and held.poll() is None:
            os.killpg(held.pid, signal.SIGKILL)
            held.wait(timeout=120)
        reader.close()


if __name__ == "__main__":
    sys.exit(main())
