import csv, sys, statistics as st
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
G = sys.argv[1]
rows = list(csv.DictReader(open(f"{G}/tables/stages.csv")))
BLUE, ORANGE, AQUA, INK, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#1f1f1e", "#6b6a64"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})
order = ["ccd-64-71-whole-stage", "ccd-0-7-whole-stage", "unpinned", "unpinned-omp8", "numactl-node0",
         "numactl-node1", "spread-8-ccds", "run-only-affinity-64-71"]
labels = ["one CCD\n(64-71)", "one CCD\n(0-7)", "unpinned", "unpinned\nOMP=8", "numactl\nnode 0",
          "numactl\nnode 1", "8 cores,\n8 CCDs", "run-only\naffinity 64-71"]
fig, ax = plt.subplots(figsize=(8.4, 3.3))
for i, c in enumerate(order):
    ys = [float(r["decode_ms_per_tok"]) for r in rows if r["condition"] == c]
    kept = c.startswith("ccd-")
    xs = [i + (j - (len(ys) - 1) / 2) * 0.07 for j in range(len(ys))]
    ax.scatter(xs, ys, s=28, color=BLUE if kept else ORANGE, edgecolor="white", linewidth=1, zorder=3,
               label=("whole stage, incl. monitor, pinned to one CCD" if kept else "other placements") if i in (0, 2) else None)
ax.set_xticks(range(len(order)), labels)
ax.set_ylabel("decode ms/token (goal mean)")
ax.set_ylim(0, 500); ax.grid(axis="y", color="#e6e5df", linewidth=0.6); ax.set_axisbelow(True)
ax.annotate("r2b-f512 (unpinned, fast by chance;\nfirst read as a prefetch effect)", xy=(2 + 0.39, 222), xytext=(3.1, 120),
            fontsize=8, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
ax.legend(frameon=False, fontsize=8, loc="lower right")
ax.set_title("Fig. A  LIQID05 (EPYC 7763 + A100), MoE-Infinity, 35 guarded goals, identical outputs", fontsize=9, loc="left", color=INK)
fig.tight_layout(); fig.savefig(f"{G}/figures/figA_decode_by_placement.png", dpi=200)

# Fig B: energy per goal by domain, observed fast vs slow state
fast = [r for r in rows if float(r["decode_ms_per_tok"]) < 300]; slow = [r for r in rows if float(r["decode_ms_per_tok"]) >= 300]
dom = [("pkg0_kj", "CPU package, socket 0 (no worker threads)", AQUA), ("pkg1_kj", "CPU package, socket 1", BLUE), ("gpu_kj", "GPU board (A100)", ORANGE)]
fig, ax = plt.subplots(figsize=(5.2, 3.2))
for x, (lab, rs) in enumerate((("observed fast\n(n=%d)" % len(fast), fast), ("observed slow\n(n=%d)" % len(slow), slow))):
    bottom = 0
    for k, name, col in dom:
        v = st.mean(float(r[k]) for r in rs)
        ax.bar(x, v, bottom=bottom, width=0.55, color=col, edgecolor="white", linewidth=2, label=name if x == 0 else None)
        ax.text(x + 0.3, bottom + v / 2, f"{v:.1f}", va="center", fontsize=8, color=INK)
        bottom += v
    w = st.mean(float(r["total_kj"]) * 1e3 / float(r["window_s"]) for r in rs); t = st.mean(float(r["window_s"]) for r in rs)
    ax.text(x, bottom + 1, f"{bottom:.1f} kJ\n{t:.0f} s x {w:.0f} W", ha="center", va="bottom", fontsize=8, color=INK)
ax.set_xticks([0, 1], [("observed fast\n(n=%d)" % len(fast)), ("observed slow\n(n=%d)" % len(slow))])
ax.set_ylabel("energy per goal, model window (kJ)"); ax.set_ylim(0, 80); ax.set_xlim(-0.6, 1.9)
ax.legend(frameon=False, fontsize=7.5, loc="upper left")
ax.set_title("Fig. B  Energy by measured domain (CPU pkg + GPU; not wall power)", fontsize=9, loc="left", color=INK)
fig.tight_layout(); fig.savefig(f"{G}/figures/figB_energy_domains.png", dpi=200)
print("ok")
