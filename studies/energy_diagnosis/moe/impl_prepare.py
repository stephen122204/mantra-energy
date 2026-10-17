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
    """Time canonical, fastest and slowest references on the performance input (parent-measured whole-process wall),
    and check every reference against the canonical outputs on the hidden inputs and the performance input."""
    from .impl_workload import equal
    if type(reps) is not int or reps < 1:
        raise ValueError("reps must be a positive integer")
    src = json.loads(Path(sources).read_text())["problems"]
    res = {}
    for pid, p in src.items():
        if problems and pid not in problems:
            continue
        mode = "set" if "assert set(" in (p.get("assertion") or "") else "exact"
        atol = float(p.get("atol") or 0.0)
        hidden = list(p["base_input"]) + list(p["plus_input"])
        inp = [p["pe_inputs"][0]]
        hs, _, c_hidden = _timed(p["canonical"], p["entry"], hidden, 300.0)
        ps, _, c_perf = _timed(p["canonical"], p["entry"], inp, 300.0)
        if (not hidden or hs != "ok" or ps != "ok"
                or not isinstance(c_hidden, dict) or not isinstance(c_perf, dict)
                or len(c_hidden.get("outputs", [])) != len(hidden)
                or len(c_perf.get("outputs", [])) != 1):
            res[pid] = dict(eligible=False, all_references_correct=False,
                            reason="canonical outputs unavailable or incomplete")
            continue
        row = {}
        for label in ("canonical", "fast_ref", "slow_ref"):
            hs, _, hp = _timed(p[label], p["entry"], hidden, 300.0)
            hidden_ok = hs == "ok" and isinstance(hp, dict) and len(hp.get("outputs", [])) == len(c_hidden["outputs"]) and all(
                equal(a, b, mode, atol) for a, b in zip(hp["outputs"], c_hidden["outputs"]))
            walls, results, status = [], [], None
            for _ in range(reps if label != "slow_ref" else 1):
                status, wall, payload = _timed(p[label], p["entry"], inp, 120.0)
                walls.append(wall)
                if status != "ok":
                    break
                results.append(isinstance(payload, dict) and len(payload.get("outputs", [])) == 1
                               and equal(payload["outputs"][0], c_perf["outputs"][0], mode, atol))
            perf_ok = status == "ok" and bool(results) and all(results)
            row[label] = dict(status=status, wall_s=[round(w, 3) for w in walls], median_wall_s=round(st.median(walls), 3),
                              hidden_correct=hidden_ok, perf_correct=perf_ok, perf_correct_each=results)
        budget = max(2.0, 3 * row["canonical"]["median_wall_s"])
        slow, fast = row["slow_ref"], row["fast_ref"]
        correct = all(r["hidden_correct"] and r["perf_correct"] is True and r["status"] == "ok" for r in row.values())
        row.update(budget_seconds=round(budget, 1), all_references_correct=correct,
                   eligible=correct and row["canonical"]["status"] == "ok"
                   and slow["median_wall_s"] >= 3 * budget)
        res[pid] = row
        print(pid, json.dumps(row), flush=True)
    Path(out).write_text(json.dumps(dict(rule="budget = max(2 s, 3 x canonical whole-process wall); eligible only if canonical, "
                                              "fastest and slowest references are correct on hidden and performance inputs, the "
                                              "fastest completes, and the slowest takes >= 3 x budget", problems=res), indent=1))


def _statement(p, first_input, first_output):
    """MBPP+: the docstring states the task and its example assert. HumanEval+: the signature and docstring state
    the task; the example assert is built from the first base input and its canonical output."""
    if p.get("family") == "humaneval":
        text = p["prompt"].rstrip()
        args = ", ".join(repr(a) for a in first_input)
        if p.get("atol"):
            example = f"assert abs({p['entry']}({args}) - {first_output!r}) <= {p['atol']!r}"
        else:
            example = f"assert {p['entry']}({args}) == {first_output!r}"
        return text, example
    text = p["prompt"].strip().strip('"').strip()
    asserts = [l.strip() for l in text.splitlines() if l.strip().startswith("assert ")]
    return text, asserts[0] if asserts else ""


def _stub(p):
    if p.get("family") == "humaneval":
        return p["prompt"].rstrip() + "\n    raise NotImplementedError\n"
    m = re.search(rf"^def\s+{re.escape(p['entry'])}\s*\(.*?\)\s*(->\s*[^:]+)?:", p["canonical"], re.M | re.S)
    header = m.group(0) if m else f"def {p['entry']}(*args):"
    return header + "\n    raise NotImplementedError\n"


def _decode(x):
    """Inverse of the sandbox output encoding for building example literals."""
    if isinstance(x, dict) and "__tuple__" in x:
        return tuple(_decode(v) for v in x["__tuple__"])
    if isinstance(x, dict) and "__set__" in x:
        return set(_decode(v) for v in x["__set__"])
    if isinstance(x, list):
        return [_decode(v) for v in x]
    return x


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
        text, example = _statement(p, hidden[0], _decode(payload["outputs"][0]))
        out[pid] = dict(entry=p["entry"], statement=text + "\n", statement_text=text, example_assert=example,
                        stub=_stub(p), hidden_inputs=hidden, hidden_expected=payload["outputs"], atol=float(p.get("atol") or 0.0),
                        performance_input=p["pe_inputs"][0], performance_expected=perf["outputs"][0],
                        compare="set" if "assert set(" in (p.get("assertion") or "") else "exact",
                        budget_seconds=c["budget_seconds"],
                        provenance=dict(evalperf="huggingface.co/datasets/evalplus/evalperf revision ba4395260c2705af25e3b0ef5b0f69d83a541b1a (test split)",
                                        evalplus=("github.com/evalplus/humanevalplus_release v0.1.10 HumanEvalPlus.jsonl.gz"
                                                  if p.get("family") == "humaneval" else
                                                  "github.com/evalplus/mbppplus_release v0.2.0 MbppPlus.jsonl.gz"),
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
