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
- Condition labels for the p8/q8/h-* stages are not mapped by `extract_stages.py`, so they show as `unknown`.

## C1, 2026-09-25 (idle-limit block, first validation)
Setup:
- Deepest idle state (C2) disabled on CPUs 64-71 and 192-199. L = pinned there; D = pinned 72-79 with the default; U = unpinned.
- 9 goals in Latin-square order. All passed, with identical outputs.

Results:
- **Decode:** L 435.3 (SD 33.8), D 424.3 (SD 4.0), U 479.2 (SD 30.1) ms/token.
- **Consequence:** disabling C2 alone does not restore fast decode on this EPYC.
- **Energy:** whole-goal energy windows. These are not comparable in absolute terms with the 2026-09-24 inner-window energies.
