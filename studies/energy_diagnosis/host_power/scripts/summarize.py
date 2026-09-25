import csv, math, statistics as st, sys, collections, random
rows = list(csv.DictReader(open(sys.argv[1])))
print("distinct outputs sha:", collections.Counter(r["outputs_sha"] for r in rows))
print("distinct requests sha:", collections.Counter(r["requests_sha"] for r in rows))
# classes by decode speed (not by condition) to show bimodality
for r in rows:
    r["fast"] = float(r["decode_ms_per_tok"]) < 300
groups = collections.defaultdict(list)
for r in rows: groups[r["condition"]].append(r)
def ci(xs):
    m = st.mean(xs)
    if len(xs) < 2: return m, float("nan")
    t = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26, 11: 2.23, 12: 2.20, 13: 2.18, 14: 2.16, 15: 2.14, 16: 2.13}.get(len(xs), 2.0)
    return m, t * st.stdev(xs) / math.sqrt(len(xs))
print("\n| condition | n | fast/n | decode ms/tok | window s | pkg0 W | pkg1 W | GPU W | total kJ |")
print("|---|---|---|---|---|---|---|---|---|")
for c, rs in sorted(groups.items()):
    f = lambda k: ci([float(r[k]) for r in rs])
    fmt = lambda k, d=1: "%.*f ± %.*f" % (d, f(k)[0], d, f(k)[1]) if len(rs) > 1 else "%.*f" % (d, f(k)[0])
    print(f"| {c} | {len(rs)} | {sum(r['fast'] for r in rs)}/{len(rs)} | {fmt('decode_ms_per_tok')} | {fmt('window_s')} | {fmt('pkg0_w')} | {fmt('pkg1_w')} | {fmt('gpu_w')} | {fmt('total_kj',2)} |")
# fast vs slow classes (all conditions), power decomposition
print("\nBy observed state (fast <300 ms/tok):")
for lab, sel in (("fast", True), ("slow", False)):
    rs = [r for r in rows if r["fast"] == sel]
    s = {k: ci([float(r[k]) for r in rs]) for k in ["decode_ms_per_tok", "window_s", "pkg0_w", "pkg1_w", "gpu_w", "total_kj"]}
    s["total_w"] = ci([float(r["total_kj"]) * 1e3 / float(r["window_s"]) for r in rs])
    print(lab, len(rs), {k: (round(v[0], 2), round(v[1], 2)) for k, v in s.items()})
