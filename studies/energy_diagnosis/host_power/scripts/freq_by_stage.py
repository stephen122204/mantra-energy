"""Mean kernel-reported cpufreq (scaling_cur_freq, 1 s samples, operating-state-v1) on CPU sets, during the
model window, per stage. Read-only over retained stage archives."""
import glob, json, sys, statistics as st
from pathlib import Path
root = Path(sys.argv[1])
sets = {"64-71": range(64, 72), "72-79": range(72, 80), "0-7": range(0, 8), "socket1-all": list(range(64, 128)) + list(range(192, 256)),
        "socket0-all": list(range(0, 64)) + list(range(128, 192))}
print("stage,decode_ms_tok," + ",".join(f"{k}_mean_GHz,{k}_frac_gt3GHz" for k in sets))
for st_dir in sorted(p for p in root.iterdir() if (p / "campaign").is_dir()):
    g = glob.glob(str(st_dir / "campaign/goals/*/operating-state.json"))
    if not g: continue
    d = Path(g[0]).parent
    o = json.loads((d / "operating-state.json").read_text())
    calls = json.loads((d / "model-calls.json").read_text())
    rec = json.loads((d / "record.json").read_text())
    spans = [(s["start_ns"], s["end_ns"]) for s in rec["spans"] if s["kind"] == "model"]
    dec = sum(c["adapter"]["backend"]["generation_timing"]["subsequent_tokens_ns"] for c in calls) / 1e6 / sum(c["adapter"]["backend"]["generation_timing"]["generated_tokens"] - 1 for c in calls)
    # samples carry read_start_ns in the same monotonic domain as record spans (checked below by overlap count)
    smp = [s for s in o["samples"] if any(a <= s["read_start_ns"] <= b for a, b in spans)]
    out = [st_dir.name, f"{dec:.1f}"]
    for k, cpus in sets.items():
        vals = []
        for s in smp:
            for c in cpus:
                f = s["fields"].get(f"cpu_frequency/policy{c}")
                if f and f.get("status") == "available": vals.append(f["value"] / 1e6)
        out += [f"{st.mean(vals):.2f}" if vals else "nan", f"{sum(v > 3.0 for v in vals) / len(vals):.2f}" if vals else "nan"]
    out.append(f"n={len(smp)}")
    print(",".join(out))
