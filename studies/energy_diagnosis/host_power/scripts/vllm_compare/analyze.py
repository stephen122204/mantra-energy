"""vLLM CPU-offload comparison analysis (written before block data). Usage: analyze.py BLOCK_DIR G1_RESULTS.json OUT.json

Per vLLM stage (V1..V3; P1 profiled, excluded from time/energy): verifier outcome, acceptance, whole-goal energy
(record.json measurements), initialized-model-window energy, decode ms/token (token-weighted), tokens, turns,
output hash. Comparator: G1 MoE-Infinity (F' performance, D' default) from g1_results.json plus its own
initialized-window energies. Mechanism: launches and GPU-active fraction from the P1 torch-profiler trace; the
MoE-Infinity reference is the 2026-09-24 decode-diagnosis profile (call 2 decode: 387,478 kernels / 36 tokens;
GPU active 3,851.5 of 23,348.3 ms).
"""
import glob, gzip, hashlib, json, math, statistics as st, sys
from pathlib import Path

block, g1p, outp = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
MOE_REF = dict(kernels_per_decode_token=387478 / 36, gpu_active_fraction=3851.5 / 23348.3,
               source="2026-09-24 decode-diagnosis call-2 profile (slow host state; profiler-perturbed)")


def stage_row(sd):
    acc_p = sd.parent / f"{sd.name}-acceptance.json"
    acc = json.loads(acc_p.read_text()) if acc_p.exists() else {}
    g = glob.glob(str(sd / "campaign/goals/*/record.json"))
    row = dict(stage=sd.name, acceptance=acc.get("smoke_passed"), checks=acc.get("checks"))
    if not g:
        row["valid"] = False; return row
    d = Path(g[0]).parent
    rec = json.loads((d / "record.json").read_text()); calls = json.loads((d / "model-calls.json").read_text())
    trace = json.loads((d / "agent-trace.json").read_text()) if (d / "agent-trace.json").exists() else {}
    win = json.loads((d / "initialized-model-window.json").read_text())
    gt = [c["adapter"]["backend"]["generation_timing"] for c in calls if c["adapter"]["backend"].get("generation_timing")]
    dec_tok = sum(x["generated_tokens"] - 1 for x in gt)
    E = {m["domain_id"]: m["energy_j"] for m in (rec.get("measurements") or []) if m.get("status") == "valid"}
    W = {m["domain_id"]: m["energy_j"] for m in win.get("measurements", []) if m.get("status") == "valid"}
    row.update(outcome=trace.get("outcome"), turns=len(calls),
               prompt_tokens=sum(c["adapter"]["backend"]["tokens"]["prompt"] for c in calls),
               completion_tokens=sum(c["adapter"]["backend"]["tokens"]["completion"] for c in calls),
               ms_tok=sum(x["subsequent_tokens_ns"] for x in gt) / 1e6 / dec_tok if dec_tok else None,
               goal_kj=sum(E.values()) / 1e3, window_kj=sum(W.values()) / 1e3, E=E,
               goal_s=(rec["ended_ns"] - rec["started_ns"]) / 1e9,
               out=hashlib.sha256(json.dumps([c["adapter"]["content"] for c in calls]).encode()).hexdigest()[:12],
               profiled=any(c["adapter"]["backend"].get("profiled") for c in calls))
    row["valid"] = bool(acc.get("smoke_passed")) and row["outcome"] == "passed"
    return row


rows = {sd.name: stage_row(sd) for sd in sorted(block.glob("[VP][0-9]")) if sd.is_dir()}
V = [r for k, r in rows.items() if k.startswith("V")]
Vv = [r for r in V if r.get("valid")]

# comparator
g1 = json.loads(g1p.read_text())
moe = {c: [x for x in g1["w1"].values() if x.get("valid") and x["cond"] == c] for c in "FD"}
cmp_ = {c: dict(ms_tok=st.mean(x["ms_tok"] for x in v), goal_kj=st.mean(x["kj"] for x in v), n=len(v)) for c, v in moe.items()}

# mechanism from the vLLM profiled call
mech = dict(vllm=None, moe_infinity=MOE_REF)
traces = sorted(glob.glob(str(block / "profile" / "**" / "*.json*"), recursive=True))
if traces:
    tp = traces[-1]
    raw = gzip.open(tp, "rt").read() if tp.endswith(".gz") else open(tp).read()
    ev = json.loads(raw).get("traceEvents", [])
    kern = [e for e in ev if e.get("cat") == "kernel" and "dur" in e]
    launches = [e for e in ev if e.get("cat") in ("cuda_runtime", "cuda_driver") and e.get("name", "").startswith(("cudaLaunchKernel", "cudaGraphLaunch", "cuLaunchKernel"))]
    ivs = sorted((e["ts"], e["ts"] + e["dur"]) for e in kern)
    busy, cur = 0.0, None
    for a, b in ivs:
        if cur is None or a > cur[1]:
            if cur: busy += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur: busy += cur[1] - cur[0]
    span = (ivs[-1][1] - ivs[0][0]) if ivs else float("nan")
    prof_call = next((c for r in rows.values() if r.get("profiled") for c in [r]), None)
    ptoks = None
    P = rows.get("P1")
    if P and P.get("valid") is not None:
        d = Path(glob.glob(str(block / "P1/campaign/goals/*/model-calls.json"))[0])
        pc = [c for c in json.loads(d.read_text()) if c["adapter"]["backend"].get("profiled")]
        ptoks = pc[0]["adapter"]["backend"]["tokens"]["completion"] if pc else None
    mech["vllm"] = dict(trace=Path(tp).name, kernels=len(kern), launch_calls=len(launches), profiled_completion_tokens=ptoks,
                        kernels_per_token=len(kern) / ptoks if ptoks else None,
                        launch_calls_per_token=len(launches) / ptoks if ptoks else None,
                        gpu_active_fraction=busy / span if span == span and span > 0 else None)

S = dict(n_valid=len(Vv), n=len(V), pass_rate=f"{sum(r.get('outcome') == 'passed' for r in V)}/{len(V)}",
         ms_tok=[r.get("ms_tok") for r in Vv], goal_kj=[r.get("goal_kj") for r in Vv], window_kj=[r.get("window_kj") for r in Vv],
         outputs={r.get("out") for r in Vv}, comparator=cmp_)
if Vv:
    m, e = st.mean(S["ms_tok"]), st.mean(S["goal_kj"])
    spread = max(S["ms_tok"]) / min(S["ms_tok"]) - 1 if len(Vv) > 1 else None
    R1 = len(Vv) == len(V) == 3 and all(r["outcome"] == "passed" for r in V)
    R2 = "pass" if e <= cmp_["F"]["goal_kj"] else ("fail" if e > 1.10 * cmp_["F"]["goal_kj"] else "inconclusive")
    R3 = m <= cmp_["F"]["ms_tok"]
    vm = mech["vllm"] or {}
    R4 = bool(vm.get("kernels_per_token") is not None and vm["kernels_per_token"] < MOE_REF["kernels_per_decode_token"]
              and (vm.get("gpu_active_fraction") or 0) > MOE_REF["gpu_active_fraction"] and R2 == "pass" and R3)
    R5 = len(Vv) == 3 and len(S["outputs"]) == 1 and spread is not None and spread < 0.05
    S.update(ms_tok_mean=m, goal_kj_mean=e, window_kj_mean=st.mean(S["window_kj"]), decode_spread=spread,
             rows=dict(R1=R1, R2=R2, R3=R3, R4=R4, R5=R5),
             all_pass=all([R1, R2 == "pass", R3, R4, R5]))
S["outputs"] = sorted(S["outputs"])
res = dict(stages=rows, mechanism=mech, summary=S)
json.dump(res, open(outp, "w"), indent=1, default=str)
print(json.dumps(dict(summary=S, mechanism=mech), indent=1, default=str))
