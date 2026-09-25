"""Extract per-stage and per-call decode timing, energy by domain and correctness from retained ALEMS
MoE-Infinity stage archives. Read-only. Usage: extract_stages.py OUTDIR ARCHIVE_ROOT[:LABEL_PREFIX] ..."""
import csv, glob, hashlib, json, sys
from pathlib import Path

COND = {  # stage -> (placement condition, keeper/guard co-location note); from the stage scripts
    **{k: ("ccd-64-71-whole-stage", "guard co-located in CCD") for k in ["c8a", "c8b", "c8c", "c8d"]},
    **{k: ("ccd-0-7-whole-stage", "guard co-located in CCD") for k in ["r8a", "r8b"]},
    **{k: ("ccd-64-71-whole-stage", "guard co-located in CCD") for k in
       ["k-demand1", "k-demand2", "k-f1g1", "k-f1g2", "k-f2g1", "k-f2g2", "k-a1g1", "k-a1g2"]},
    **{k: ("spread-8-ccds", "one core per CCD") for k in ["s8a", "s8b"]},
    "f8": ("run-only-affinity-64-71", "supervisor/guard unpinned"),
    **{k: ("unpinned-omp8", "OMP_NUM_THREADS=8") for k in ["t8a", "t8b"]},
    **{k: ("numactl-node0", "socket 0 (remote)") for k in ["n0a", "n0b"]},
    **{k: ("numactl-node1", "socket 1 (GPU-local)") for k in ["n1a", "n1b"]},
}
def cond(name):
    if name in COND: return COND[name]
    if name.startswith(("u", "r1", "r2")): return ("unpinned", "default")
    return ("unknown", "")

def one(stage_dir, label):
    goals = glob.glob(str(stage_dir / "campaign/goals/*/record.json")) or glob.glob(str(stage_dir / "run/goals/*/record.json"))
    if not goals: return None, []
    d = Path(goals[0]).parent
    rec = json.loads((d / "record.json").read_text())
    calls = json.loads((d / "model-calls.json").read_text())
    trace = json.loads((d / "agent-trace.json").read_text())
    ver = json.loads((d / "verification.json").read_text()) if (d / "verification.json").exists() else {}
    win = json.loads((d / "initialized-model-window.json").read_text())
    ev = json.loads((d / "expert-events.json").read_text()) if (d / "expert-events.json").exists() else [{}]
    pol = ev[0].get("policy", {})
    E = {m["domain_id"]: m["energy_j"] for m in win["measurements"] if m["status"] == "valid"}
    ws = [(m["start_ns"], m["end_ns"]) for m in win["measurements"]]
    wdur = (max(e for _, e in ws) - min(s for s, _ in ws)) / 1e9 if ws else float("nan")
    model_s = sum(s["end_ns"] - s["start_ns"] for s in rec["spans"] if s["kind"] == "model") / 1e9
    tok = sum(c["adapter"]["backend"]["generation_timing"]["generated_tokens"] for c in calls)
    dec_ns = sum(c["adapter"]["backend"]["generation_timing"]["subsequent_tokens_ns"] for c in calls)
    dec_tok = sum(c["adapter"]["backend"]["generation_timing"]["generated_tokens"] - 1 for c in calls)
    outh = hashlib.sha256(json.dumps([c["adapter"]["content"] for c in calls]).encode()).hexdigest()[:12]
    reqh = hashlib.sha256(json.dumps([c["request"] for c in calls], sort_keys=True).encode()).hexdigest()[:12]
    c, note = cond(stage_dir.name)
    acc_p = stage_dir.parent / f"{stage_dir.name}-acceptance.json"
    acc = json.loads(acc_p.read_text()).get("smoke_passed") if acc_p.exists() else None
    row = dict(source=label, stage=stage_dir.name, condition=c, note=note,
               policy=pol.get("name"), budget_mib=(pol.get("byte_budget") or 0) // 2**20, timing=pol.get("timing"),
               outcome=trace.get("outcome"), verified=ver.get("passed", ver.get("status")), acceptance=acc,
               calls=len(calls), gen_tokens=tok, decode_tokens=dec_tok,
               decode_ms_per_tok=round(dec_ns / 1e6 / dec_tok, 1) if dec_tok else None,
               model_s=round(model_s, 1), goal_s=round((rec["ended_ns"] - rec["started_ns"]) / 1e9, 1),
               window_s=round(wdur, 1),
               pkg0_kj=round(E.get("PACKAGE_SOCKET_0", float("nan")) / 1e3, 2),
               pkg1_kj=round(E.get("PACKAGE_SOCKET_1", float("nan")) / 1e3, 2),
               gpu_kj=round(E.get("GPU_BOARD_0", float("nan")) / 1e3, 2),
               total_kj=round(sum(E.values()) / 1e3, 2),
               pkg0_w=round(E.get("PACKAGE_SOCKET_0", float("nan")) / wdur, 1),
               pkg1_w=round(E.get("PACKAGE_SOCKET_1", float("nan")) / wdur, 1),
               gpu_w=round(E.get("GPU_BOARD_0", float("nan")) / wdur, 1),
               outputs_sha=outh, requests_sha=reqh)
    percall = []
    for i, cl in enumerate(calls):
        g = cl["adapter"]["backend"]["generation_timing"]
        n = g["generated_tokens"]
        percall.append(dict(source=label, stage=stage_dir.name, condition=c, call=i, gen_tokens=n,
                            ttft_s=round(g["time_to_first_token_ns"] / 1e9, 3),
                            decode_ms_per_tok=round(g["subsequent_tokens_ns"] / 1e6 / (n - 1), 1) if n > 1 else None))
    return row, percall

out = Path(sys.argv[1]); rows, calls = [], []
for arg in sys.argv[2:]:
    root, _, label = arg.partition(":")
    for st in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        r, pc = one(st, label or Path(root).name)
        if r: rows.append(r); calls += pc
for name, data in (("stages.csv", rows), ("calls.csv", calls)):
    with open(out / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
print(len(rows), "stages;", len(calls), "calls")
