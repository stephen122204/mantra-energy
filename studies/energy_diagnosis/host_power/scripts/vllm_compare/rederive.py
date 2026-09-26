"""Independent re-derivation of the vLLM comparison numbers. Separate code and different estimators from analyze.py.

- Decode: median over calls of per-call ms/token (analyze.py: token-weighted mean).
- Energy: sum of every valid measurement in record.json, plus the GPU share (analyze.py: whole-goal sum only).
- Outputs: hash of the concatenated assistant texts (analyze.py: JSON list hash).
- Mechanism: kernel count and GPU-busy time from the trace, with busy time computed as the union of
  intervals after rounding to 1 microsecond, over the span from the first to the last launch.
Usage: rederive.py BLOCK_DIR
"""
import glob, gzip, hashlib, json, statistics as st, sys
from pathlib import Path

block = Path(sys.argv[1])
for sd in sorted(block.glob("[VP][0-9]")):
    g = glob.glob(str(sd / "campaign/goals/*/record.json"))
    if not g:
        print(sd.name, "no goal"); continue
    d = Path(g[0]).parent
    rec = json.loads((d / "record.json").read_text()); calls = json.loads((d / "model-calls.json").read_text())
    tr = json.loads((d / "agent-trace.json").read_text())
    per = [c["adapter"]["backend"]["generation_timing"] for c in calls]
    rates = [x["subsequent_tokens_ns"] / 1e6 / (x["generated_tokens"] - 1) for x in per if x["generated_tokens"] > 1]
    ms = {m["domain_id"]: m["energy_j"] for m in rec["measurements"] if m["status"] == "valid"}
    txt = "".join(c["adapter"]["content"] or "" for c in calls)
    print(f"{sd.name}: outcome={tr.get('outcome')} turns={len(calls)} median_call_ms_tok={st.median(rates):.2f} "
          f"kJ={sum(ms.values())/1e3:.2f} gpu_share={ms.get('GPU_BOARD_0', 0)/sum(ms.values()):.2f} "
          f"text_sha={hashlib.sha256(txt.encode()).hexdigest()[:12]} goal_s={(rec['ended_ns']-rec['started_ns'])/1e9:.0f}")

for tp in sorted(glob.glob(str(block / "profile" / "**" / "*.json*"), recursive=True)):
    raw = gzip.open(tp, "rt").read() if tp.endswith(".gz") else open(tp).read()
    ev = json.loads(raw).get("traceEvents", [])
    k = sorted((round(e["ts"]), round(e["ts"] + e["dur"])) for e in ev if e.get("cat") == "kernel" and "dur" in e)
    graphs = sum(1 for e in ev if "GraphLaunch" in e.get("name", ""))
    busy = 0; hi = None
    for a, b in k:
        if hi is None or a >= hi:
            busy += b - a; hi = b
        elif b > hi:
            busy += b - hi; hi = b
    span = k[-1][1] - k[0][0] if k else 0
    print(f"trace {Path(tp).name}: kernels={len(k)} graph_launches={graphs} busy_ms={busy/1e3:.1f} span_ms={span/1e3:.1f} "
          f"active={busy/span if span else float('nan'):.3f}")
