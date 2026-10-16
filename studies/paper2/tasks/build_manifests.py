"""Build task manifests (ids + metadata only, no problem text) and a seeded pilot selection.

Usage: python3 -I build_manifests.py RAW_DIR OUT_DIR   (RAW_DIR from fetch_task_metadata.sh)
import csv, glob, json, os, random, sys, tomllib, collections
raw, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
def write(name, header, rows):
    with open(os.path.join(out, name), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(header); w.writerows(rows)
    return len(rows)
counts = {}
# SWE-bench Verified
sw = []
for f in sorted(glob.glob(raw + "/swev_*.json")):
    sw += [r["row"] for r in json.load(open(f))["rows"]]
order = {"<15 min fix": 0, "15 min - 1 hour": 1, "1-4 hours": 2, ">4 hours": 3}
sw.sort(key=lambda r: (-order[r["difficulty"]], r["instance_id"]))
def f2p(r):
    v = r["FAIL_TO_PASS"]; return len(json.loads(v) if isinstance(v, str) else v)
counts["swebench_verified"] = write("swebench_verified.csv",
    ["instance_id", "repo", "difficulty", "gold_patch_lines", "fail_to_pass_tests", "problem_statement_chars"],
    [[r["instance_id"], r["repo"], r["difficulty"], r["patch"].count("\n"), f2p(r), len(r["problem_statement"])] for r in sw])
# tau2-bench
rows = []
for d in ["airline", "retail", "telecom"]:
    t = json.load(open(f"{raw}/tau2_{d}_tasks.json")); s = json.load(open(f"{raw}/tau2_{d}_split_tasks.json"))
    split = {k: set(v) for k, v in s.items()}
    for x in t:
        if x["id"] not in split["base"]: continue
        sp = "test" if x["id"] in split.get("test", ()) else "train" if x["id"] in split.get("train", ()) else ""
        rows.append([d, x["id"], sp, len(x["evaluation_criteria"].get("actions") or [])])
counts["tau2_base"] = write("tau2_bench.csv", ["domain", "task_id", "split", "expected_actions"], rows)
# Terminal-Bench 2
rows = []
for f in sorted(glob.glob(raw + "/tb2_toml/*.toml")):
    m = tomllib.load(open(f, "rb")); md, env = m["metadata"], m["environment"]
    rows.append([os.path.basename(f)[:-5], md.get("difficulty"), md.get("category"), md.get("expert_time_estimate_min"),
                 md.get("junior_time_estimate_min"), m["agent"].get("timeout_sec"), env.get("cpus"), env.get("memory_mb"),
                 env.get("gpus"), env.get("allow_internet"), env.get("docker_image")])
rk = {"hard": 0, "medium": 1, "easy": 2}; rows.sort(key=lambda r: (rk[r[1]], r[0]))
counts["terminal_bench_2"] = write("terminal_bench_2.csv", ["task", "difficulty", "category", "expert_min", "junior_min",
    "agent_timeout_s", "cpus", "memory_mb", "gpus", "internet", "docker_image"], rows)
tb = rows
# Aider polyglot
ex = [l.strip().split("/") for l in open(raw + "/aider_exercises.txt") if l.strip()]
counts["aider_polyglot"] = write("aider_polyglot.csv", ["language", "exercise"], [[e[0], e[3]] for e in ex])
# Math (ids and type only; problems and answers are not redistributed)
rows = []
for ds, name in [("MathArena_aime_2025", "aime_2025"), ("MathArena_hmmt_feb_2025", "hmmt_feb_2025")]:
    for r in json.load(open(f"{raw}/{ds}.json"))["rows"]:
        rows.append([name, r["row"]["problem_idx"], "|".join(r["row"]["problem_type"]) if isinstance(r["row"]["problem_type"], list) else r["row"]["problem_type"]])
counts["math"] = write("math_reasoning.csv", ["set", "problem_idx", "problem_type"], rows)
# Seeded pilot selection for 8-bit calibration
rng = random.Random(20261016)
pick = lambda xs, n: sorted(rng.sample(xs, min(n, len(xs))))
by = collections.defaultdict(list)
for r in sw: by[r["difficulty"]].append(r["instance_id"])
sel = {
  "seed": 20261016,
  "swebench_verified": {"1-4 hours + >4 hours (all)": sorted(by["1-4 hours"] + by[">4 hours"]),
                        "15 min - 1 hour (30 sampled)": pick(by["15 min - 1 hour"], 30),
                        "<15 min fix (10 sampled)": pick(by["<15 min fix"], 10)},
  "tau2_bench": {d: sorted(set(json.load(open(f"{raw}/tau2_{d}_split_tasks.json"))["test"])) for d in ["airline", "retail", "telecom"]},
  "terminal_bench_2": {"hard (all)": [r[0] for r in tb if r[1] == "hard"], "medium (all)": [r[0] for r in tb if r[1] == "medium"]},
  "aider_polyglot": {lang: pick([e[3] for e in ex if e[0] == lang], 10) for lang in sorted({e[0] for e in ex})},
  "math_reasoning": {"aime_2025": list(range(1, 31)), "hmmt_feb_2025": list(range(1, 31))},
}
json.dump(sel, open(os.path.join(out, "pilot_selection.json"), "w"), indent=1)
n = lambda v: sum(len(x) for x in v.values())
print(counts); print({k: n(v) for k, v in sel.items() if isinstance(v, dict)})
