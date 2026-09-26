# Derived tables (discovery and first validation block)

These tables are derived from retained stage archives by `../scripts/`. The raw archives are not in the repository. They are identified by sha256 below.

| file | source archive (sha256) | produced by |
|---|---|---|
| `stages_liqid05_20260924.csv`, `calls_liqid05_20260924.csv` | `liqid05-resume-20260924.tgz` (e433b6a41f96b8aa22573ba870d3263009d391db2bda3e7b28cb693a8d5f1eaa) | `extract_stages.py` |
| `freq_by_stage_liqid05_20260924.csv` | same | `freq_by_stage.py` |
| `energy_boundaries_liqid05_20260924.md` | same | `summarize.py` |
| `stages_h100_20260924.csv`, `calls_h100_20260924.csv` | `h100-artifacts-20260924.tgz` (25b7ca4e7d64522f9e476a1228003197241dea5a70dbed523ef3d8f2829c48f2) | `extract_stages.py` |
| `c1_idle_limit_liqid05_20260925.json` | host-idle-check C1 raw block (2026-09-25) | `verify_c1.py` |

## LIQID05, 2026-09-24 (discovery)
Setup:
- MoE-Infinity backend 6da092fc, Qwen3-30B-A3B-Instruct-2507 bf16, cache ratio 0.65, task etl-latest-v2-n1000000-s103.
- 35 guarded goals. All passed the task verifier.
- One request hash and one output hash across all goals; 669 generated tokens each.

Results:
- **Observed fast state (15 goals):** 210.6 ± 3.2 ms/token, 38.19 ± 0.41 kJ.
- **Observed slow state (20 goals):** 425.3 ± 12.8 ms/token, 60.55 ± 1.34 kJ.
- **Energy boundary:** CPU package RAPL (both sockets) + NVML GPU board, over the initialized-model window.
- **Condition labels:** from the stage scripts. `ccd-*-whole-stage` means the whole stage, including the ALEMS monitor, was pinned to one CCD.
- **CPU clock:** the kernel-reported `scaling_cur_freq`, 1 s samples. It is not a cycle-accurate effective clock.

## H100 node, 2026-09-24
- GPU board energy only; RAPL was not readable.
- Condition labels were corrected 2026-09-26. On this node GPU 0 is on NUMA node 0, so node 0 is GPU-local and node 1 is remote, the reverse of LIQID05. p8 is taskset to 8 cores on node 0 and q8 to 8 cores on node 1; h-* stages are unpinned, and h-res-profile ran with the torch profiler on.
- Every H100 stage exited rc=3 by design, because RAPL was unreadable; the goals passed their verifier. p8a exited rc=76 (guard: owned worker reparented during teardown; record complete).

## C1, 2026-09-25 (idle-limit block, first validation)
Setup:
- Deepest idle state (C2) disabled on CPUs 64-71 and 192-199. L = pinned there; D = pinned 72-79 with the default; U = unpinned.
- 9 goals in Latin-square order. All passed, with identical outputs.

Results:
- **Decode:** L 435.3 (SD 33.8), D 424.3 (SD 4.0), U 479.2 (SD 30.1) ms/token.
- **Consequence:** disabling C2 alone does not restore fast decode on this EPYC.
- **Energy:** whole-goal energy windows. These are not comparable in absolute terms with the 2026-09-24 inner-window energies.

## G0, 2026-09-25 (governor per CCD; `g0_governor_liqid05_20260925.json`)
- Setup: MoE-Infinity, C1 stage protocol. D = CCD 72-79 schedutil; F = CCD 80-87 performance; X = CCD 88-95 performance + C2 off. n = 3 each, outputs identical.
- Decode: D 434.4, F 220.5, X 233.1 ms/token.
- Whole-goal CPU pkg + GPU energy: D 104.4, F 78.6, X 79.8 kJ.
- Worker-CCD clock: D ~1.55 GHz; F and X ~2.9 GHz.
- llama.cpp GPU and CPU-expert stacks: F/D 1.000 and 0.992.
- Raw archive sha256: fad112caea44aaa0f63a8d172c04334ceb5e12f0bfbaddc50669659f795e1eea.

## G1, 2026-09-26 (CCD swap and stock stacks; `g1_ccdswap_stockstacks_liqid05_20260926.json`)
- Setup: F′ = CCD 72-79 performance; D′ = CCD 80-87 schedutil; N = CCD 96-103 schedutil. Stock stacks run from a pinned venv (torch 2.8.0, transformers 4.57.1, vLLM 0.10.2).
- MoE-Infinity:
  - decode F′ 204.7 vs D′ 405.4 ms/token (F′/D′ 0.505, 95% CI 0.445-0.574);
  - energy F′/D′ 0.793 (CI 0.744-0.844);
  - clock 3.1 vs 1.6 GHz;
  - outputs identical.
- Stock stacks, F′/D′ decode: vLLM CPU offload of Qwen3-30B-A3B 1.000; vLLM in-memory 0.999; HF eager 1.007; llama.cpp GPU 1.000; llama.cpp CPU experts with OpenMP default 1.005 and with passive wait 1.002. CCD-null N/D′ is within 0.989-1.004.
- The `handoff_bench` chain modes kept one core fully busy (a Python process at ~100% CPU), so they do not reproduce a sleeping critical path. Treat them as a benchmark limitation, not as evidence about sleeping hand-offs. chain2-F-r1 is invalid (worker device bug, fixed mid-block).
- Raw archive sha256: bcbfb5a684b498ce41007b47c8e38f5266efed845527f67f4e76939c35456dcf.
