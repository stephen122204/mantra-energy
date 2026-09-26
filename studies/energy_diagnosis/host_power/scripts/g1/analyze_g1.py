"""G1 analysis (frozen with PREREG-G1.md before data). Usage: analyze_g1.py G1_DIR OUT.json

W1: per-slot accepted stage (F1a*, D1a*, ...): decode ms/token, energy by domain (ALEMS record), CCD clock, output hash.
W2: per stack/run: mean over measured generations of (t_last - t_first)/(stamps - 1); validity = token count == n,
    stamps == tokens, identical output hash within stack across all runs; energy over each decode window from sampler.
W3: handoff_bench ms/token, j/token, vcsw/token per mode/condition.
Effects: ratio of means F'/D' (and N/D' where present), 95% CI Welch t on log values.
"""
import bisect, glob, hashlib, json, math, statistics as st, sys
from pathlib import Path

root = Path(sys.argv[1]); res = dict(w1={}, w2={}, w3={}, summary={})
T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
SET = dict(F=range(72, 80), D=range(80, 88), N=range(96, 104))


def welch(x, d):
    if len(x) < 2 or len(d) < 2: return None
    lx, ld = [math.log(v) for v in x], [math.log(v) for v in d]
    vx, vd = st.variance(lx) / len(lx), st.variance(ld) / len(ld)
    se = math.sqrt(vx + vd); diff = st.mean(lx) - st.mean(ld)
    df = (vx + vd) ** 2 / (vx ** 2 / (len(lx) - 1) + vd ** 2 / (len(ld) - 1)) if se > 0 else 1
    q = T[max(1, min(10, math.floor(df)))]
    return dict(ratio_of_means=st.mean(x) / st.mean(d), ci95=[math.exp(diff - q * se), math.exp(diff + q * se)], n=(len(x), len(d)))


# ---- W1
for sd in sorted((root / "w1").glob("[FD][0-9]a[0-9]")):
    acc_p = root / "w1" / f"{sd.name}-acceptance.json"
    acc = json.loads(acc_p.read_text()).get("smoke_passed") if acc_p.exists() else None
    g = glob.glob(str(sd / "campaign/goals/*/record.json"))
    row = dict(slot=sd.name[:2], cond=sd.name[0], valid=bool(acc), acceptance=acc)
    if g:
        d = Path(g[0]).parent
        calls = json.loads((d / "model-calls.json").read_text()); rec = json.loads((d / "record.json").read_text())
        gt = [c["adapter"]["backend"]["generation_timing"] for c in calls]
        row["ms_tok"] = sum(x["subsequent_tokens_ns"] for x in gt) / 1e6 / sum(x["generated_tokens"] - 1 for x in gt)
        E = {m["domain_id"]: m["energy_j"] for m in (rec.get("measurements") or []) if m.get("status") == "valid"}
        row.update(kj=sum(E.values()) / 1e3, E=E, out=hashlib.sha256(json.dumps([c["adapter"]["content"] for c in calls]).encode()).hexdigest()[:12])
        spans = [(s["start_ns"], s["end_ns"]) for s in rec["spans"] if s["kind"] == "model"]
        o = json.loads((d / "operating-state.json").read_text())
        smp = [s for s in o["samples"] if any(a <= s["read_start_ns"] <= b for a, b in spans)]
        fr = [s["fields"][f"cpu_frequency/policy{c}"]["value"] / 1e3 for s in smp for c in SET[row["cond"]]
              if s["fields"].get(f"cpu_frequency/policy{c}", {}).get("status") == "available"]
        row["ccd_mhz"] = round(st.mean(fr)) if fr else None
    else:
        row["valid"] = False
    res["w1"][sd.name] = row

# ---- sampler series for W2/W3 energy
samp = None
sp = root / "sampler.jsonl"
if sp.exists():
    lines = [json.loads(s) for s in sp.read_text().splitlines() if s.strip()]
    head = [r for r in lines if r.get("kind") == "header"][0]; rows = [r for r in lines if "t" in r]
    mx = [z["max_energy_range_uj"] for z in head["zones"]]
    t, cpu, gpu, acc, prev = [], [], [], [0.0, 0.0], None
    for r in rows:
        if prev is not None:
            for k in range(2):
                dd = r["rapl"][k] - prev[k]; acc[k] += (dd if dd >= 0 else dd + mx[k] + 1) / 1e6
        prev = r["rapl"]; t.append(r["t"]); cpu.append(acc[0] + acc[1]); gpu.append((r["gpu_mj"] or 0) / 1e3)
    samp = (t, cpu, gpu)


def energy(a, b):
    if samp is None: return None
    t, cpu, gpu = samp
    def at(s, x):
        i = bisect.bisect_left(t, x)
        if i <= 0 or i >= len(t): return None
        return s[i - 1] + (s[i] - s[i - 1]) * (x - t[i - 1]) / (t[i] - t[i - 1])
    vals = [at(cpu, b), at(cpu, a), at(gpu, b), at(gpu, a)]
    if None in vals: return None
    return dict(cpu_j=vals[0] - vals[1], gpu_j=vals[2] - vals[3])


# ---- W2
for rj in sorted((root / "w2").glob("*/*/result.json")):
    stack, run = rj.parent.parent.name, rj.parent.name
    r = json.loads(rj.read_text()); gens = r["gens"]; n = r["n"]
    reasons = []
    ms, ej = [], []
    for gg in gens:
        stamps = gg["stamps"]
        if gg.get("tokens") != n: reasons.append(f"tokens {gg.get('tokens')} != {n}")
        if len(stamps) != n: reasons.append(f"stamps {len(stamps)} != {n}")
        k = len(stamps) - 1
        ms.append((stamps[-1] - stamps[0]) / 1e6 / k)
        e = energy(stamps[0], stamps[-1])
        if e: ej.append((e["cpu_j"] + e["gpu_j"]) / k)
    shas = sorted({gg.get("output_sha") or gg.get("output_ids_sha") for gg in gens})
    res["w2"].setdefault(stack, {})[run] = dict(cond=run[0], ms_tok=st.mean(ms), gens_ms=ms, j_tok=st.mean(ej) if ej else None,
                                               shas=shas, reasons=sorted(set(reasons)))
for stack, runs in res["w2"].items():
    allsha = {s for x in runs.values() for s in x["shas"]}
    for x in runs.values():
        if len(allsha) > 1: x["reasons"].append("output differs within stack")
        x["valid"] = not x["reasons"]

# ---- W3
for bj in sorted((root / "w3").glob("*.json")):
    b = json.loads(bj.read_text()); mode, cond, rep = bj.stem.split("-")
    res["w3"].setdefault(mode, {})[f"{cond}{rep}"] = dict(cond=cond, ms_tok=b["ms_per_token"], j_tok=b.get("j_per_token"),
                                                          vcsw_tok=b.get("vcsw_per_token"), checksum=b.get("checksum"))

# ---- summary
S = res["summary"]
w1 = [x for x in res["w1"].values() if x.get("valid")]
for c in "FD":
    v = [x["ms_tok"] for x in w1 if x["cond"] == c]
    S[f"w1_{c}"] = dict(n=len(v), ms_mean=st.mean(v) if v else None, kj_mean=st.mean([x["kj"] for x in w1 if x["cond"] == c]) if v else None,
                        mhz=[x.get("ccd_mhz") for x in w1 if x["cond"] == c])
S["w1_F_over_D"] = welch([x["ms_tok"] for x in w1 if x["cond"] == "F"], [x["ms_tok"] for x in w1 if x["cond"] == "D"])
S["w1_energy_F_over_D"] = welch([x["kj"] for x in w1 if x["cond"] == "F"], [x["kj"] for x in w1 if x["cond"] == "D"])
S["w1_distinct_outputs"] = len({x["out"] for x in w1})
for stack, runs in res["w2"].items():
    ok = [x for x in runs.values() if x["valid"]]
    by = {c: [x["ms_tok"] for x in ok if x["cond"] == c] for c in "FDN"}
    S[f"w2_{stack}"] = dict(n={c: len(v) for c, v in by.items()}, ms_mean={c: (st.mean(v) if v else None) for c, v in by.items()},
                            F_over_D=welch(by["F"], by["D"]), N_over_D=welch(by["N"], by["D"]) if by["N"] else None,
                            j_F_over_D=welch([x["j_tok"] for x in ok if x["cond"] == "F" and x["j_tok"]], [x["j_tok"] for x in ok if x["cond"] == "D" and x["j_tok"]]),
                            invalid=[k for k, x in runs.items() if not x["valid"]])
for mode, runs in res["w3"].items():
    S[f"w3_{mode}"] = dict(F_over_D=welch([x["ms_tok"] for x in runs.values() if x["cond"] == "F"], [x["ms_tok"] for x in runs.values() if x["cond"] == "D"]),
                           vcsw_tok=st.mean([x["vcsw_tok"] for x in runs.values() if x["vcsw_tok"] is not None] or [float("nan")]),
                           checksums=len({x["checksum"] for x in runs.values()}))
p1 = (S["w1_F_over_D"] or {}).get("ratio_of_means")
S["rules"] = dict(STOP_ccd_identity=(p1 is not None and p1 > 0.80),
                  second_engine_candidates={k[3:]: v["F_over_D"] for k, v in S.items() if k.startswith("w2_") and isinstance(v, dict) and v.get("F_over_D")
                                            and v["F_over_D"]["ratio_of_means"] <= 1 / 1.3 and v["F_over_D"]["ci95"][1] <= 1 / 1.05})
json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
print(json.dumps(S, indent=1, default=str))
