"""Write the frozen pilot plan for one node (run on the node after setup_node.sh).

Passes in priority order, each atomic (all its precisions or none): (0) idle, 1 agent on 3 tasks and
4 agents on 12 tasks, every precision; (1) 16 agents on all 23 tasks, every precision; (2) same-precision
replay of the 4-agent cohort on 4-bit and the SWE-bench calibration cohort on 4-bit and 8-bit.

    python -m studies.paper2.cohort.make_plan --work ~/paper2 --gpu-uuid GPU-... --allocation LEASE --out plan.json
    python -m studies.paper2.cohort.make_plan ... --sweep --total-service-s S --out sweep-plan.json

``--sweep`` writes the same-task calibration sweep instead: every live cohort offers all 23 tasks with
the same seed, mode and cohort deadline, so only the admission limit N changes. Round 0 covers
N = 1, 2, 4, 8, 16; later rounds repeat the N given by ``--repeat-n`` to measure run-to-run spread.
Each round is one atomic pass; block order rotates so each precision runs first equally often, and
the N order inside a round is shuffled once (seeded) and shared by all precisions. ``S`` is the
largest total per-session service time measured for this task set on this GPU class; step estimates
use the list-scheduling bound S/N + session deadline, plus grading. ``--frozen-prep DIR`` pins every
task to a reference preparation (DIR/assets, hashes from DIR/catalog.json): private grading seeds are
drawn per preparation, so rounds and nodes are only paired when they share one snapshot.

Tasks: the 23 C2 task definitions that need no external benchmark bundle (business, ETL,
numerical, program, repository repair) as calibration instances. Evaluation instances are NOT
generated here: they use fresh generator seeds/cases frozen later, so pilot data cannot leak
into evaluation. Configurations: Devstral-Small-2507 BF16 / INT8 W8A8 / INT4 W4A16 on vLLM 0.10.2,
equal total GPU-memory budget (gpu_memory_utilization 0.90), BF16 KV cache, prefix caching on.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

REPO_CASES = ["bfs-layers-visited", "connected-components-bfs", "core-number-comparison", "dag-longest-path-multigraph",
              "degree-centrality-normalization", "dijkstra-tentative-distance", "edge-boundary-symmetric",
              "overall-reciprocity-overlap", "topological-generations-multiedge"]

ARMS = {
    "devstral-bf16": dict(weight_precision="bf16", activation_precision="bf16", quantizer="none (original BF16 weights)",
                          revision="bd165ab26cebbcc2eea2c4ecbfc07f3ac42b3c39"),
    "devstral-w8a8": dict(weight_precision="int8", activation_precision="int8",
                          quantizer="llm-compressor SmoothQuant(0.8)+GPTQ W8A8 (RedHatAI)", revision="b152b0574658cdd159721472ebf5353d8d199451"),
    "devstral-w4a16": dict(weight_precision="int4", activation_precision="bf16",
                           quantizer="llm-compressor GPTQ W4A16 asym g128 actorder=weight (RedHatAI)",
                           revision="bb96f0d1a876d6f6f3ed657b6a965328697ba2f9"),
}


def c2_specs(networkx_src: str, tool_python: str) -> list:
    specs = []
    for rows in (8192, 1000000):
        specs.append(dict(kind="business", rows=rows, seed=7))
        specs.append(dict(kind="etl", rows=rows, seed=7))
        specs.append(dict(kind="numerical", rows=rows, seed=7))
    for rows in (8192, 100000):
        for case in ("conditional-dedup", "user-histogram"):
            specs.append(dict(kind="program", case=case, rows=rows, seed=7))
    for case in REPO_CASES:
        specs.append(dict(kind="repo", case=case, source=networkx_src, python=tool_python))
    return specs


def task_ids() -> dict:
    biz = [f"business-{q}-v2-n{r}-s7" for r in (8192, 1000000) for q in ("segments", "orphans", "declines")]
    etl = [f"etl-latest-v3-n{r}-s7" for r in (8192, 1000000)]
    num = [f"grouped-fit-v1-n{r}-s7" for r in (8192, 1000000)]
    prog = [f"python-{c}-v2-n{r}-s7" for r in (8192, 100000) for c in ("conditional-dedup", "user-histogram")]
    repo = [f"repo-{c}-v4" for c in REPO_CASES]
    moderate = ["business-segments-v2-n8192-s7", "business-declines-v2-n1000000-s7", "etl-latest-v3-n8192-s7",
                "etl-latest-v3-n1000000-s7", "grouped-fit-v1-n8192-s7", "grouped-fit-v1-n1000000-s7",
                "python-conditional-dedup-v2-n8192-s7", "python-user-histogram-v2-n100000-s7",
                "repo-bfs-layers-visited-v4", "repo-dijkstra-tentative-distance-v4", "repo-core-number-comparison-v4",
                "repo-topological-generations-multiedge-v4"]
    return dict(all=biz + etl + num + prog + repo, moderate=moderate,
                isolated=["business-segments-v2-n8192-s7", "grouped-fit-v1-n8192-s7", "repo-bfs-layers-visited-v4"])


def build(work: Path, gpu_uuid: str, allocation: str, swebench_catalog: Path = None, max_model_len: int = 65536) -> dict:
    swebench_ids = [c["task_id"] for c in json.loads(swebench_catalog.read_text())] if swebench_catalog else []
    ids = task_ids()
    configs = [dict(name=name, model=str(work / "models" / name), max_model_len=max_model_len, gpu_memory_utilization=0.90,
                    max_num_seqs=64, **arm) for name, arm in ARMS.items()]
    names = [c["name"] for c in configs]
    # Passes in priority order; each pass is atomic (runs on all its precisions or not at all) so every
    # comparison inside it is paired. Same task ids and seeds across precisions within a step.
    core = [{"idle": dict(name="idle60", seconds=60, est_s=70)},
            {"live": dict(name="n1", admission_limit=1, task_ids=ids["isolated"], seed=12, est_s=900, cohort_deadline_s=1500)},
            {"live": dict(name="n4", admission_limit=4, task_ids=ids["moderate"], seed=11, est_s=900, cohort_deadline_s=1500)}]
    pressure = [{"live": dict(name="n16", admission_limit=16, task_ids=ids["all"], seed=13, est_s=1200, cohort_deadline_s=1500)}]
    extra = [{"replay": dict(name="replay-n4", source="n4", admission_limit=4, est_s=1000)}]
    if swebench_ids:
        extra.append({"live": dict(name="swe-n5", admission_limit=len(swebench_ids), task_ids=swebench_ids, seed=14,
                                   est_s=1600, cohort_deadline_s=1500)})
    passes = [dict(atomic=True, blocks={n: dict(steps=core) for n in names}),
              dict(atomic=True, blocks={n: dict(steps=pressure) for n in names}),
              # replay fidelity on one precision only (4-bit), SWE-bench calibration on 4-bit and 8-bit
              dict(atomic=True, blocks={"devstral-w4a16": dict(steps=extra),
                                        "devstral-w8a8": dict(steps=[s for s in extra if "live" in s])})]
    return dict(
        version="paper2-pilot-v1", gpu_uuid=gpu_uuid, allocation=allocation,
        isolation="dedicated node; one vLLM server; agent sessions + tools on the same host",
        block_seed=20261017, configs=configs, passes=passes,
        tekken={c["name"]: str(Path(c["model"]) / "tekken.json") for c in configs},
        task_specs=c2_specs(str(work / "networkx-src"), str(work / "venv" / "bin" / "python")),
        limits=dict(max_turns=250, max_tool_calls=500, max_total_output_tokens=65536, max_tokens=4096, deadline_s=1800,
                    verify_timeout_s=900),
        sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),  # C2: T=0.15, full vocab
        load_est_s=300, export_reserve_s=900, cohort_deadline_s=3000,
        extra_catalogs=[str(swebench_catalog)] if swebench_catalog else [],
        task_options=dict(swebench=dict(cpus="4", memory="16g", harness_python=str(work / "venv-swebench" / "bin" / "python"))),
    )


SWEEP_N = (1, 2, 4, 8, 16)


def sweep_bound_s(n: int, total_service_s: float, session_deadline_s: float, round_to: int = 300) -> int:
    """Upper bound on a closed cohort of N agents: total service / N + the longest session, rounded up."""
    return int(math.ceil((total_service_s / n + session_deadline_s) / round_to) * round_to)


def build_sweep(work: Path, gpu_uuid: str, allocation: str, total_service_s: float, *, repeat_n=(4, 16),
                repeats: int = 2, grading_s: int = 600, seed: int = 20261018, frozen_prep: Path = None,
                max_model_len: int = 65536) -> dict:
    plan = build(work, gpu_uuid, allocation, max_model_len=max_model_len)
    ids = task_ids()["all"]
    names = [c["name"] for c in plan["configs"]]
    session_deadline = plan["limits"]["deadline_s"]
    # one backstop deadline for every cohort of the sweep (the campaign sweep gate requires it); the
    # per-session deadline is the limit that normally ends a straggler
    deadline = sweep_bound_s(1, total_service_s, session_deadline)
    rng = random.Random(seed)
    rotation = list(names)
    rng.shuffle(rotation)
    passes = []
    for r, ns in enumerate([list(SWEEP_N)] + [list(repeat_n)] * repeats):
        ns = list(ns)
        rng.shuffle(ns)
        tag = f"-r{r}" if r else ""
        steps = [{"idle": dict(name=f"idle60{tag}", seconds=60, est_s=70)}]
        steps += [{"live": dict(name=f"n{n}{tag}", admission_limit=n, task_ids=ids, seed=13, mode="fixed",
                                sweep="same-task", round=r, cohort_deadline_s=deadline,
                                est_s=sweep_bound_s(n, total_service_s, session_deadline) + grading_s)} for n in ns]
        k = r % len(rotation)
        passes.append(dict(atomic=True, order=rotation[k:] + rotation[:k], blocks={n: dict(steps=steps) for n in names}))
    plan.update(version="paper2-sweep-v1", passes=passes, cohort_deadline_s=deadline,
                sweep=dict(levels=list(SWEEP_N), repeat_n=list(repeat_n), repeats=repeats, seed=seed,
                           total_service_s=total_service_s, grading_s=grading_s))
    plan.pop("extra_catalogs", None)
    if frozen_prep:
        have = {r["task_id"]: r["asset_sha256"] for r in json.loads((Path(frozen_prep) / "catalog.json").read_text())}
        missing = sorted(set(ids) - set(have))
        if missing:
            raise SystemExit(f"{frozen_prep}: frozen preparation lacks {missing}")
        plan.update(prepared_assets=str(Path(frozen_prep).resolve() / "assets"),
                    expected_tasks={t: have[t] for t in sorted(ids)})
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--gpu-uuid", required=True)
    ap.add_argument("--allocation", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--swebench-catalog", type=Path)
    ap.add_argument("--sweep", action="store_true", help="same-task calibration sweep over N")
    ap.add_argument("--total-service-s", type=float, help="--sweep: largest measured total session service time")
    ap.add_argument("--repeat-n", type=int, nargs="+", default=[4, 16])
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--frozen-prep", type=Path, help="--sweep: reference preparation (catalog.json + assets/)")
    ap.add_argument("--max-model-len", type=int, default=65536, help="serving context for every precision")
    a = ap.parse_args(argv)
    if a.sweep:
        if not a.total_service_s:
            ap.error("--sweep needs --total-service-s from a pilot on this GPU class")
        plan = build_sweep(a.work.resolve(), a.gpu_uuid, a.allocation, a.total_service_s, repeat_n=a.repeat_n,
                           repeats=a.repeats, frozen_prep=a.frozen_prep, max_model_len=a.max_model_len)
    else:
        plan = build(a.work.resolve(), a.gpu_uuid, a.allocation, a.swebench_catalog, max_model_len=a.max_model_len)
    a.out.write_text(json.dumps(plan, indent=1))
    print(a.out)


if __name__ == "__main__":
    main()
