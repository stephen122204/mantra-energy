"""Write the frozen pilot plan for one node (run on the node after setup_node.sh).

Passes in priority order, each atomic (all its precisions or none): (0) idle, 1 agent on 3 tasks and
4 agents on 12 tasks, every precision; (1) 16 agents on all 23 tasks, every precision; (2) same-precision
replay of the 4-agent cohort on 4-bit and the SWE-bench calibration cohort on 4-bit and 8-bit.

    python -m studies.paper2.cohort.make_plan --work ~/paper2 --gpu-uuid GPU-... --allocation LEASE --out plan.json

Tasks: the 23 C2 task definitions that need no external benchmark bundle (business, ETL,
numerical, program, repository repair) as calibration instances. Evaluation instances are NOT
generated here: they use fresh generator seeds/cases frozen later, so pilot data cannot leak
into evaluation. Configurations: Devstral-Small-2507 BF16 / INT8 W8A8 / INT4 W4A16 on vLLM 0.10.2,
equal total GPU-memory budget (gpu_memory_utilization 0.90), BF16 KV cache, prefix caching on.
"""
from __future__ import annotations

import argparse
import json
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


def build(work: Path, gpu_uuid: str, allocation: str, swebench_catalog: Path = None) -> dict:
    swebench_ids = [c["task_id"] for c in json.loads(swebench_catalog.read_text())] if swebench_catalog else []
    ids = task_ids()
    configs = [dict(name=name, model=str(work / "models" / name), max_model_len=65536, gpu_memory_utilization=0.90,
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--gpu-uuid", required=True)
    ap.add_argument("--allocation", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--swebench-catalog", type=Path)
    a = ap.parse_args(argv)
    a.out.write_text(json.dumps(build(a.work.resolve(), a.gpu_uuid, a.allocation, a.swebench_catalog), indent=1))
    print(a.out)


if __name__ == "__main__":
    main()
