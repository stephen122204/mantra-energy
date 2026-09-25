# Host CPU power settings: measurement workstreams

This folder measures how the host CPU's power settings change batch-1 LLM decode time and CPU+GPU energy per verified goal. The settings are the frequency governor and the deepest idle state. The workloads are MoE-Infinity agent goals, stock inference stacks, and a hand-off microbenchmark.

Why this is measured: in the 2026-09-24 LIQID05 runs, the same verified goals decoded at about 211 or 425 ms/token depending only on host CPU placement. Outputs were byte-identical. See `data/`.

## Nodes (all leases end before 2026-10-02)
| id | lease | hardware | window (UTC) |
|---|---|---|---|
| A1 | alems-liqid05-20260920-72h | 2× AMD EPYC 7763 + A100-40GB PCIe (LIQID05) | now → Oct 2 20:30 |
| A2 | alems-hostpower-liqid-b-20260926 (CHI@TACC) | same node type, second machine | Sep 26 06:00 → Oct 1 23:00 |
| I1 | alems-hostpower-intel-rtx6000-20260926 (CHI@UC) | Intel Xeon Gold 6126 + Quadro RTX 6000 24GB | Sep 26 16:00 → Oct 1 23:00 |
| H1 | alems-hostpower-h100-spr-1d-20260928 (CHI@TACC) | Intel Xeon Platinum 8468 + H100 (1 of 4 GPUs used) | Sep 28 04:00 → Sep 29 01:00 |

H1 is execution only. Setup scripts and the Intel knob port are validated on I1 first. The H1 block design is frozen before the window. Raw data are copied off before 00:30 UTC Sep 29.

## Knob conditions
| code | frequency policy | deepest idle state | placement |
|---|---|---|---|
| U | default | default | unpinned |
| D | default | default | pinned to one CCD/core group |
| F | performance governor (Intel: EPP=performance) | default | pinned |
| I | default | disabled | pinned |
| IF | performance | disabled | pinned |

- On AMD, `scripts/power-2x2.sh` applies I, F and IF to three CCDs of the GPU-local socket, and leaves D as the control.
  - It saves every value to /root and restores it with readback.
  - Run it with sudo, by the node owner only, immediately around a block.
  - It refuses to apply while another idle-limit or frequency-limit save file exists.
- The Intel port (intel_pstate/EPP and cpuidle state names) is still to do.

## Workloads
| code | workload | correctness check |
|---|---|---|
| W1 | ALEMS MoE-Infinity agent goals (etl-latest-v2 + 2 repo-v4 tasks) | task verifier pass; identical outputs across conditions |
| W2 | stock stacks at batch 1, forced length, greedy: HF eager, llama.cpp GPU, llama.cpp CPU-expert MoE, vLLM, accelerate offload | output token hash identical across conditions |
| W3 | `scripts/handoff_bench.py` (spin1, block1, chain1/2/4) | checksum identical |

## Workstreams
Each workstream owns one goal end to end.

| WS | goal | done when | depends on |
|---|---|---|---|
| WS0 | Decide whether the full study runs | On A1: the performance governor alone restores MoE-Infinity decode ≥ 1.5× with identical outputs; ≥ 1 stock stack shows ≥ 15% default-vs-performance change; the W3 2x2 block is complete | A1 free; one sudo apply/restore |
| WS1 | Every node runs every workload under every knob, with verified readback | A2 and I1: MoE-Infinity smoke goal passes (I1 at a cache ratio that fits 24 GB); stock stacks run; knob scripts pass status/apply/restore; RAPL + NVML (+ IPMI if available) readable; clock and context-switch recorder running | leases active |
| WS2 | Every workload has a verifiable runner | W1-W3 runners validated on one node, with output identity | none |
| WS3 | Size of the effect and which knob causes it, per CPU vendor | W1 × {D, F, I, IF} × 3 on A1, A2, I1; per-thread `perf` cycles D vs F; guard on/off ablation | WS0, WS1, WS2 |
| WS4 | Which runtimes are exposed, predicted before measuring | W3 fit → predictions frozen and checksummed → W2 × {D, F, IF, U} × 3 on A1/A2 and I1; prediction error reported per stack | WS0, WS1, WS2 |
| WS5 | Whether leaving the knob uncontrolled changes conclusions and variance | 12 unpinned W1 goals at quiet vs busy host times on A1; platform ranking A vs I under U vs IF | WS3, WS4 |
| WS6 | One trustworthy dataset | One export schema with sha256 manifests; independent re-derivation of every reported number; invalid-run ledger | schema before WS3/WS4 start |

## Schedule
- **Sep 25-26:** WS0 on A1. WS1 and WS2 in parallel.
- **Sep 27-29:** WS3 and WS4 on all nodes, if WS0 passes.
- **Sep 30 - Oct 1:** WS5, then re-runs of invalid slots, then data copied off and node cleanup.

## Cost per unit (measured)
- MoE-Infinity guarded goal-stage: ≈ 7.2 min.
- Stock-stack run: ≈ 1.5 min.
- W3 run: ≈ 15 s.
- W1 × 4 knobs × 3 tasks × 3 reps ≈ 4.3 h per node.

## Rules
- **Order:** Latin-square order.
- **Guarded windows:** no logins during measured blocks.
- **Pooling:** never pool across nodes, stacks, code revisions or cache ratios.
- **Pre-registration:** predictions and analysis are frozen and checksummed before each block. Any later change is a dated amendment.
- **Invalid runs:** only for a pre-stated reason (rc ≠ 0, wrong token count, knob readback wrong, another process on the measured cores, a login during a block). Invalid runs are kept and listed. A failed or deadlocked goal is an outcome, not a dropped row.
- **Energy boundary:** CPU package RAPL (per socket) + NVML GPU board. Call it that, never wall power, unless IPMI is added.

## Scripts
| script | purpose |
|---|---|
| `power-2x2.sh` | AMD knob setup (sudo, node owner): status / apply / restore |
| `freq-limit.sh` | performance governor on one CCD only (sudo): status / apply / restore |
| `handoff_bench.py` | W3 microbenchmark; records ms/token, voluntary context switches, RAPL + NVML J/token |
| `run_2x2.sh` | Latin-square runner for W3 across D / I / F / IF / U, with an external frequency sampler |
| `extract_stages.py` | per-stage and per-call tables from ALEMS stage archives |
| `freq_by_stage.py` | CPU clock on CPU sets during model spans, per stage |
| `verify_c1.py` | independent re-derivation of the 2026-09-25 idle-limit (C1) block |
| `summarize.py` | condition summary with 95% intervals |
| `figures_retained.py` | decode-by-placement and energy-by-domain figures |
