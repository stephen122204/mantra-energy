# C2 precision-energy campaign data

Per-attempt records for the C2 campaigns (Qwen3-30B-A3B-Instruct-2507 and Devstral Small 2; llama.cpp GGUF Q4_K_M, Q8_0 and BF16; bare-metal Chameleon A100 nodes). Each campaign has one row per dispatched batch (attempt), valid or not. The raw result archives (about 36 GB) are not in Git. They stay off-repository, and every file in them is listed in `verification/`.

## Layout

| Path | Contents |
|---|---|
| `campaigns/index.json` | Each campaign: machine, model, budget level, attempts, valid attempts, passed attempts |
| `campaigns/<campaign>/attempts.csv` | One row per attempt (columns below) |
| `campaigns/<campaign>/plan.json`, `node-spec.json`, `preflight.json` | Scheduler plan, generated batch list and preflight checks. Present for the campaigns run after Sep 30; for `c2-l0-liqid05` and `repo-r-liqid05` they are in the private run folders |
| `machines/` | Per-node no-load idle baselines (600 s, CPU packages and GPU board, W) and full-GPU residency checks at the 65,536-token context |
| `verification/archive-check-*.json` | Each node's result files compared with the verified laptop backup chain (missing / differing / extra files; all zero) |
| `verification/*.node-manifest.sha256.gz` | sha256 of every result file on the node at the end of each campaign |

## Campaigns

| Campaign | Machine | Model | Level | Notes |
|---|---|---|---|---|
| `c2-l0-liqid05` | LIQID05, A100 40GB | Qwen3-30B-A3B | L0 | 29 cases x Q4/Q8 x 11 repetitions (r00 greedy, r01-r10 sampled) |
| `repo-r-liqid05` | LIQID05 | Qwen3-30B-A3B | R | 9 repository cases x Q4/Q8 x 11 repetitions |
| `qwen-r-3arm-gigaio08` | gigaio-08, A100 80GB | Qwen3-30B-A3B | R | 29 cases x Q4/Q8/BF16. Stopped at the lease cutoff: r00-r06 complete, r07 72/87 |
| `qwen-r-r07-gigaio07` | gigaio-07, A100 80GB | Qwen3-30B-A3B | R | The 15 unfinished r07 batches of the gigaio-08 plan (same argv except host, cutoff, allocation id and output path) |
| `devstral-r-liqid06` | LIQID06, A100 40GB | Devstral Small 2 | R | 29 cases x Q4/Q8 x 11 repetitions |
| `external-l0-liqid05` | LIQID05 | Qwen3-30B-A3B | L0 | BIRD dev (40) + EvalPerf held-out (37), blocks r00 (complete) and r01 (115/154, stopped at the cutoff) |
| `external-l0-liqid04` | liqid04, A100 40GB | Qwen3-30B-A3B | L0 | Same tasks, blocks r02 and r03 |

**Budget levels.**
- L0: 16,384 context, 24 turns, 48 tool calls, 8,192 total and 2,048 per-turn output tokens, 600 s goal deadline.
- R: 65,536 context, 250 turns, 500 tool calls, 65,536 total and 4,096 per-turn output tokens, 1,800 s.

## Columns of `attempts.csv`

| Column | Meaning |
|---|---|
| `id` | Batch id: `r<rep>-<family>-<task>-<arm>` |
| `rep`, `decoding` | Repetition block; `greedy` for r00, `sampled` otherwise (seeded, same seeds for every arm) |
| `arm` | `q4` (Q4_K_M), `q8` (Q8_0), `bf16` |
| `valid`, `infrastructure` | Measurement validity and, if invalid, the reason (e.g. job status, missing energy record) |
| `passed`, `outcome`, `failure` | Verified completion, agent outcome (`passed`, `wrong_answer`, `context_exhausted`, `turn_budget_exhausted`, ...) and verifier failure label |
| `turns`, `slips` | Agent turns, and turns that were malformed or contained no action |
| `tool_calls`, `failed_tests` | Tool calls, and tool calls whose result reported a failure |
| `completion_tokens`, `prompt_tokens` | Summed over model calls (backend counts) |
| `agent_J` | Operational energy of the task window (CPU package 0 + package 1 + GPU board, J) |
| `inference_J`, `tools_J`, `other_J` | Energy inside model-call spans, inside tool spans, and the remainder of the task window |
| `init_J`, `grader_J` | Model initialization window and research-grading window, both measured separately and excluded from `agent_J` |

All energy is gross (no idle subtraction) and comes from interpolated RAPL and NVML counter samples (0.1 s). Rows are produced by the attempt-extraction function of the analysis scripts from the saved batch records.

## Data-quality flags

- `repo-r-liqid05`: two batches are invalid (one deadline inside a model call; one interference stop). Eleven further batches overlapped SSH logins outside maintenance windows. They are valid in the table, and their ids are recorded in the private run log.
- `qwen-r-3arm-gigaio08`: `r00-business-business-orphans-v2-n8192-s7-bf16` overlapped a 0.27 s operator login (2026-10-01T06:50:09Z). The process guard did not flag it.
- `devstral-r-liqid06`: one retained invalid batch, `r10-program-python-conditional-dedup-v2-n100000-s7-q8` (the goal deadline was reached inside a model call, so the end counters are missing).
- gigaio-07 GPU idle is 49.9 W against 58.3 W on gigaio-08. The CPU packages are within 2% (`machines/`).
