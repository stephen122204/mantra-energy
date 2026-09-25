"""Independent re-derivation of C1 (host-idle-check) from model-calls.json, record.json, operating-state.json."""
import glob, hashlib, json, sys, statistics as st
from pathlib import Path
root = Path(sys.argv[1]); rows = []
for sd in sorted(p for p in root.iterdir() if (p / "campaign").is_dir()):
    g = Path(glob.glob(str(sd / "campaign/goals/*/record.json"))[0]).parent
    calls = json.loads((g / "model-calls.json").read_text()); rec = json.loads((g / "record.json").read_text())
    gt = [c["adapter"]["backend"]["generation_timing"] for c in calls]
    dec = sum(x["subsequent_tokens_ns"] for x in gt) / 1e6 / sum(x["generated_tokens"] - 1 for x in gt)
    percall = [round(x["subsequent_tokens_ns"] / 1e6 / (x["generated_tokens"] - 1)) for x in gt if x["generated_tokens"] > 1]
    outs = hashlib.sha256(json.dumps([c["adapter"]["content"] for c in calls]).encode()).hexdigest()[:12]
    ms = rec.get("measurements") or []
    E = {m["domain_id"]: m["energy_j"] for m in ms if m.get("status") == "valid"}
    spans = [(s["start_ns"], s["end_ns"]) for s in rec["spans"] if s["kind"] == "model"]
    o = json.loads((g / "operating-state.json").read_text())
    smp = [s for s in o["samples"] if any(a <= s["read_start_ns"] <= b for a, b in spans)]
    def f(cpus):
        v = [s["fields"][f"cpu_frequency/policy{c}"]["value"] / 1e3 for s in smp for c in cpus if s["fields"].get(f"cpu_frequency/policy{c}", {}).get("status") == "available"]
        return round(st.mean(v)) if v else None
    rows.append(dict(stage=sd.name, cond=sd.name[0], ms_tok=round(dec, 1), percall=percall, out=outs,
                     pkg0_kj=round(E.get("PACKAGE_SOCKET_0", 0) / 1e3, 2), pkg1_kj=round(E.get("PACKAGE_SOCKET_1", 0) / 1e3, 2),
                     gpu_kj=round(E.get("GPU_BOARD_0", 0) / 1e3, 2), goal_s=round((rec["ended_ns"] - rec["started_ns"]) / 1e9, 1),
                     f64_71=f(range(64, 72)), f72_79=f(range(72, 80))))
for r in rows: print(r)
for c in "LDU":
    v = [r["ms_tok"] for r in rows if r["cond"] == c]; e = [r["pkg0_kj"] + r["pkg1_kj"] + r["gpu_kj"] for r in rows if r["cond"] == c]
    print(c, "ms/tok mean %.1f sd %.1f" % (st.mean(v), st.stdev(v)), "| total kJ mean %.1f" % st.mean(e))
print("distinct outputs:", {r["out"] for r in rows})
json.dump(rows, open(sys.argv[2], "w"), indent=1)
