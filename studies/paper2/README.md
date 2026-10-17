# Paper 2: precision under concurrent agent serving — tests and task suite

Tests for 4-bit vs 8-bit weight precision when many requests or agents share one GPU: energy per token split
into prefill and decode, then energy per verified task completion at concurrency 1–16.

## Question

When many agents share one GPU, which weight precision (4-bit or 8-bit) completes a task with less energy, and
what decides it?

| factor | what we measure | where |
|---|---|---|
| Phase cost | energy per prompt token (prefill) and per generated token (decode) at each precision and load | `phase_bench/` |
| Task shape | prompt vs generated tokens per call over a task (context growth, tool output, prefix-cache reuse) | C2 traces; task runs |
| Agent behaviour | extra tokens, malformed calls and failures at each precision | C2 data; task runs |
| Outcome | total energy of a concurrent run ÷ tasks that pass their verifier | task runs (`tasks/`) |

## Layout

| path | contents |
|---|---|
| `phase_bench/` | `setup.sh`, `bench.py` (exact files used), `summarize.py`, `RUNS.md` (hardware, commands) |
| `results/v100-20261016/` | raw CSV + stdout per test, engine commit, model hashes, `SHA256SUMS`, `summary.csv` |
| `tasks/manifests/` | task ids + difficulty metadata for SWE-bench Verified, τ²-bench, Terminal-Bench 2, Aider polyglot, AIME25/HMMT25; `pilot_selection.json` |
| `tasks/` | `fetch_task_metadata.sh` + `build_manifests.py` (reproduce manifests), `setup_harnesses.sh` (node), `SOURCES.md` (pins, licenses, reference scores) |

## Results so far: V100, Qwen3-8B, llama.cpp, GPU board energy (16 Oct 2026)

Median q4/q8 energy ratio, 3 repetitions × 32 requests per cell (`results/v100-20261016/summary.csv`):

| test | conc 1 | conc 4 | conc 16 | unit |
|---|---|---|---|---|
| p0 mixed (~1.57k-token prompt, 256 generated) | 0.913 | 1.029 | 1.062 | J / generated token |
| p0b same, precision order swapped | 0.917 | 1.050 | 1.052 | J / generated token |
| p0c decode-heavy (~17-token prompt, 512 generated) | 0.876 | 0.963 | 0.876 | J / generated token |
| p0d prefill-only (~1.57k-token prompt, 1 generated) | 1.136 | 1.135 | 1.153 | J / prompt token |

Below 1 means 4-bit used less energy. Repetitions agree within about 0.03. Scope: one dense 8B model, one GPU
type without INT8 tensor cores, one engine, GPU energy only, synthetic fixed-length requests, outside the ALEMS
harness.

## Task suite

| set | source | role |
|---|---|---|
| 29 C2 tasks (numerical, program, business, ETL, implementation, repository) | branch `stephen/full-task-qualification`, `studies/energy_diagnosis/moe/` | short and medium anchor; existing per-task behaviour data |
| SWE-bench Verified, 85 selected | `tasks/manifests/` | long, hard (all 45 instances labelled 1–4 h or >4 h) |
| τ²-bench test splits, 100 | `tasks/manifests/` | long multi-turn tool use; retail → airline → telecom gets harder |
| Terminal-Bench 2, 85 (hard + medium) | `tasks/manifests/` | long terminal tasks with expert time estimates |
| Aider polyglot, 60 | `tasks/manifests/` | short, hard coding |
| AIME25 + HMMT25, 60 | `tasks/manifests/` | short prompts, long generated reasoning |

The C2 task code is not copied here; use the branch above. Calibration rule and run notes: `tasks/SOURCES.md`.

## Models

| model | precision arms | used for |
|---|---|---|
| Qwen3-8B (dense) | GGUF Q4_K_M / Q8_0 | prefill/decode energy tests only |
| Qwen3-30B-A3B-Instruct-2507 (MoE) | 4-bit / 8-bit | τ²-bench, Aider polyglot, AIME/HMMT, C2 tasks |
| Devstral Small 1.1 (24B dense) | 4-bit / 8-bit | SWE-bench Verified, C2 tasks |

## Next tests (A100-80GB lease `mantra-a100-80gb-20261017`, 17–24 Oct)

1. Repeat p0c and p0d on A100 with llama.cpp and stock vLLM (INT4 AWQ/Marlin vs INT8/FP8 weights), for Qwen3-8B
   and Qwen3-30B-A3B. Check whether the prefill ratio stays above 1.
2. Context-length and load grid: prompts of 2k/8k/32k/64k tokens; concurrency 1, 2, 4, 8, 16, 32.
3. Prompt vs completion tokens per call and prefix-cache hits from existing C2 traces.
4. Calibration pilot at 8-bit on `pilot_selection.json`; then the selected tasks at both precisions under
   concurrency 1/4/16 in the ALEMS harness (CPU package + GPU board; counters from PR #77), energy per verified
   completion.

## Setup on a new node

```bash
bash phase_bench/setup.sh                     # llama.cpp + Qwen3-8B GGUF (run as cc on the node)
bash tasks/setup_harnesses.sh                 # τ²-bench, Terminal-Bench 2, polyglot, swebench (not yet run)
```
