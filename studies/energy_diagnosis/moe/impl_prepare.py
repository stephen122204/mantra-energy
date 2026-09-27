"""Prepare impl problems from extracted EvalPerf + MBPP+ sources.

  calibrate SOURCES.json OUT.json [--problems A,B] [--reps 3]
      time the canonical, fastest and slowest reference solutions on the performance input through the same
      runner the tool and verifier use (whole subprocess wall time, cap 120 s); apply the budget rule:
      budget = max(2 s, 3 x canonical wall time); eligible only if slowest wall time >= 3 x budget.
  build SOURCES.json CALIBRATION.json BUNDLE.json --problems A,B,...
      compute expected outputs with the canonical solution (same runner and encoding as the verifier) and write
      the bundle used by impl_workload.create_task.
The performance input is the first EvalPerf performance-exercising input of each problem. Hidden inputs are the
MBPP+ base and plus inputs. Comparison is 'set' when the MBPP+ assertion compares with set(...), else 'exact'.
"""
import argparse
import hashlib
import json
import re
import statistics as st
import tempfile
import time
from pathlib import Path

from .impl_workload import VERSION, _run


def _timed(source, entry, inputs, cap):
    t0 = time.monotonic()
    status, payload = _run(source, entry, inputs, cap)
    return status, time.monotonic() - t0, payload


def calibrate(sources, out, problems=None, reps=3):
    src = json.loads(Path(sources).read_text())["problems"]
    res = {}
    for pid, p in src.items():
        if problems and pid not in problems:
            continue
        inp = [p["pe_inputs"][0]]
        row = {}
        for label in ("canonical", "fast_ref", "slow_ref"):
            walls, outs, status = [], [], None
            for _ in range(reps if label != "slow_ref" else 1):
                status, wall, payload = _timed(p[label], p["entry"], inp, 120.0)
                walls.append(wall)
                if status != "ok":
                    break
                outs.append(json.dumps(payload["outputs"], sort_keys=True))
            row[label] = dict(status=status, wall_s=[round(w, 3) for w in walls], median_wall_s=round(st.median(walls), 3),
                              consistent_output=len(set(outs)) <= 1)
        budget = max(2.0, 3 * row["canonical"]["median_wall_s"])
        slow = row["slow_ref"]
        row.update(budget_seconds=round(budget, 1),
                   eligible=row["canonical"]["status"] == "ok" and (slow["status"] == "timeout" or slow["median_wall_s"] >= 3 * budget))
        res[pid] = row
        print(pid, json.dumps(row), flush=True)
    Path(out).write_text(json.dumps(dict(rule="budget = max(2 s, 3 x canonical wall); eligible if slowest wall >= 3 x budget",
                                         problems=res), indent=1))


def _statement(prompt):
    text = prompt.strip().strip('"').strip()
    asserts = [l.strip() for l in text.splitlines() if l.strip().startswith("assert ")]
    return text, asserts[0] if asserts else ""


def _stub(canonical, entry):
    m = re.search(rf"^def\s+{re.escape(entry)}\s*\(.*?\)\s*(->\s*[^:]+)?:", canonical, re.M | re.S)
    header = m.group(0) if m else f"def {entry}(*args):"
    return header + "\n    raise NotImplementedError\n"


def build(sources, calibration, bundle, problems):
    raw = Path(sources).read_bytes()
    src = json.loads(raw)["problems"]
    cal = json.loads(Path(calibration).read_text())["problems"]
    out = {}
    for pid in problems:
        p, c = src[pid], cal[pid]
        if not c["eligible"]:
            raise ValueError(f"{pid} is not eligible under the budget rule")
        hidden = list(p["base_input"]) + list(p["plus_input"])
        status, _, payload = _timed(p["canonical"], p["entry"], hidden, 300.0)
        if status != "ok":
            raise ValueError(f"canonical failed on hidden inputs for {pid}: {status}")
        status2, _, perf = _timed(p["canonical"], p["entry"], [p["pe_inputs"][0]], 300.0)
        if status2 != "ok":
            raise ValueError(f"canonical failed on the performance input for {pid}")
        text, example = _statement(p["prompt"])
        out[pid] = dict(entry=p["entry"], statement=text + "\n", statement_text=text, example_assert=example,
                        stub=_stub(p["canonical"], p["entry"]), hidden_inputs=hidden, hidden_expected=payload["outputs"],
                        performance_input=p["pe_inputs"][0], performance_expected=perf["outputs"][0],
                        compare="set" if "assert set(" in p["assertion"] else "exact",
                        budget_seconds=c["budget_seconds"],
                        provenance=dict(evalperf="huggingface.co/datasets/evalplus/evalperf (test split)",
                                        mbppplus="github.com/evalplus/mbppplus_release v0.2.0 MbppPlus.jsonl.gz",
                                        sources_sha256=hashlib.sha256(raw).hexdigest(), calibration=c))
    Path(bundle).write_text(json.dumps(dict(version=VERSION, problems=out)))
    print(json.dumps({k: dict(entry=v["entry"], hidden=len(v["hidden_inputs"]), compare=v["compare"],
                              budget=v["budget_seconds"]) for k, v in out.items()}, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate"); c.add_argument("sources"); c.add_argument("out")
    c.add_argument("--problems"); c.add_argument("--reps", type=int, default=3)
    b = sub.add_parser("build"); b.add_argument("sources"); b.add_argument("calibration"); b.add_argument("bundle")
    b.add_argument("--problems", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "calibrate":
        calibrate(a.sources, a.out, a.problems.split(",") if a.problems else None, a.reps)
    else:
        build(a.sources, a.calibration, a.bundle, a.problems.split(","))


if __name__ == "__main__":
    main()
