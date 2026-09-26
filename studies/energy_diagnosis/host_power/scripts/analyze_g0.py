"""G0 analysis (fixed before data collection). Usage: analyze_g0.py G0_DIR OUT.json

W1: per stage decode ms/token (token-weighted over calls), energy by domain (record.json measurements, whole goal),
    output hash, CCD clock during model spans (operating-state), acceptance.
W2: per run mean over 3 measured generations of (t_last - t_first)/(stamps - 1); output hash per generation.
Effects: ratio of means vs D; 95% CI Welch t on log values. Decision rule applied mechanically.
"""
import glob, hashlib, json, math, statistics as st, sys
from pathlib import Path

root = Path(sys.argv[1]); res = dict(w1={}, w2={})
T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306}
SET = dict(D=range(72, 80), F=range(80, 88), X=range(88, 96))


def welch(x, d):
    lx, ld = [math.log(v) for v in x], [math.log(v) for v in d]
    vx, vd = st.variance(lx) / len(lx), st.variance(ld) / len(ld)
    se = math.sqrt(vx + vd); diff = st.mean(lx) - st.mean(ld)
    df = (vx + vd) ** 2 / (vx ** 2 / (len(lx) - 1) + vd ** 2 / (len(ld) - 1)) if se > 0 else 1
    q = T[max(1, min(8, math.floor(df)))]
    return dict(ratio_of_means=st.mean(x) / st.mean(d), ci95=[math.exp(diff - q * se), math.exp(diff + q * se)])


for sd in sorted((root / "w1").glob("[DFX][0-9]")):
    g = glob.glob(str(sd / "campaign/goals/*/record.json"))
    acc_p = root / "w1" / f"{sd.name}-acceptance.json"
    acc = json.loads(acc_p.read_text()).get("smoke_passed") if acc_p.exists() else None
    if not g:
        res["w1"][sd.name] = dict(cond=sd.name[0], valid=False, reason="no record", acceptance=acc); continue
    d = Path(g[0]).parent
    calls = json.loads((d / "model-calls.json").read_text()); rec = json.loads((d / "record.json").read_text())
    gt = [c["adapter"]["backend"]["generation_timing"] for c in calls]
    ms = sum(x["subsequent_tokens_ns"] for x in gt) / 1e6 / sum(x["generated_tokens"] - 1 for x in gt)
    E = {m["domain_id"]: m["energy_j"] for m in (rec.get("measurements") or []) if m.get("status") == "valid"}
    spans = [(s["start_ns"], s["end_ns"]) for s in rec["spans"] if s["kind"] == "model"]
    o = json.loads((d / "operating-state.json").read_text())
    smp = [s for s in o["samples"] if any(a <= s["read_start_ns"] <= b for a, b in spans)]
    fr = [s["fields"][f"cpu_frequency/policy{c}"]["value"] / 1e3 for s in smp for c in SET[sd.name[0]]
          if s["fields"].get(f"cpu_frequency/policy{c}", {}).get("status") == "available"]
    res["w1"][sd.name] = dict(cond=sd.name[0], valid=bool(acc), acceptance=acc, ms_tok=ms,
                              percall=[round(x["subsequent_tokens_ns"] / 1e6 / (x["generated_tokens"] - 1)) for x in gt if x["generated_tokens"] > 1],
                              kj=sum(E.values()) / 1e3, E=E, goal_s=(rec["ended_ns"] - rec["started_ns"]) / 1e9,
                              ccd_mhz=round(st.mean(fr)) if fr else None,
                              out=hashlib.sha256(json.dumps([c["adapter"]["content"] for c in calls]).encode()).hexdigest()[:12])

for rj in sorted((root / "w2").glob("*/*/result.json")):
    stack, run = rj.parent.parent.name, rj.parent.name
    r = json.loads(rj.read_text()); gens = r["gens"]
    ok = all(gg.get("tokens") == r["n"] for gg in gens)
    msv = [(gg["stamps"][-1] - gg["stamps"][0]) / 1e6 / (len(gg["stamps"]) - 1) for gg in gens]
    res["w2"].setdefault(stack, {})[run] = dict(cond=run[0], valid=ok, ms_tok=st.mean(msv), gens_ms=msv,
                                              shas=sorted({gg["output_sha"] for gg in gens}))

summ = {}
w1 = res["w1"]
for c in "DFX":
    v = [s["ms_tok"] for s in w1.values() if s["cond"] == c and s["valid"]]
    e = [s["kj"] for s in w1.values() if s["cond"] == c and s["valid"]]
    summ[f"w1_{c}"] = dict(n=len(v), ms_mean=st.mean(v) if v else None, ms_sd=st.stdev(v) if len(v) > 1 else None,
                           kj_mean=st.mean(e) if e else None)
dv = [s["ms_tok"] for s in w1.values() if s["cond"] == "D" and s["valid"]]
for c in "FX":
    xv = [s["ms_tok"] for s in w1.values() if s["cond"] == c and s["valid"]]
    if len(xv) > 1 and len(dv) > 1: summ[f"w1_{c}_vs_D"] = welch(xv, dv)
de = [s["kj"] for s in w1.values() if s["cond"] == "D" and s["valid"]]
fe = [s["kj"] for s in w1.values() if s["cond"] == "F" and s["valid"]]
if len(fe) > 1 and len(de) > 1: summ["w1_energy_F_vs_D"] = welch(fe, de)
outs = {s["out"] for s in w1.values() if s["valid"]}
for stack, runs in res["w2"].items():
    for c in "DFX":
        v = [x["ms_tok"] for x in runs.values() if x["cond"] == c and x["valid"]]
        summ[f"w2_{stack}_{c}"] = dict(n=len(v), ms_mean=st.mean(v) if v else None)
    d2 = [x["ms_tok"] for x in runs.values() if x["cond"] == "D" and x["valid"]]
    f2 = [x["ms_tok"] for x in runs.values() if x["cond"] == "F" and x["valid"]]
    if len(d2) > 1 and len(f2) > 1: summ[f"w2_{stack}_F_vs_D"] = welch(f2, d2)
    summ[f"w2_{stack}_distinct_outputs"] = len({s for x in runs.values() for s in x["shas"]})

fv = [s["ms_tok"] for s in w1.values() if s["cond"] == "F" and s["valid"]]
g0a = bool(fv) and all(v < 260 for v in fv) and summ.get("w1_F_vs_D", {}).get("ratio_of_means", 9) <= 0.67 and len(outs) == 1
g0b = any(abs(1 - summ[k]["ratio_of_means"]) >= 0.15 for k in summ if k.startswith("w2_") and k.endswith("_F_vs_D"))
summ["decision"] = dict(G0a=g0a, G0b=g0b, w1_distinct_outputs=len(outs))
res["summary"] = summ
json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
print(json.dumps(summ, indent=1, default=str))
