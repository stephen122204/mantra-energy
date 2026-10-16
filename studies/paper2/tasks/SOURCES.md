# Task sources, pins and licenses

The manifests list task identifiers and public metadata only. Problem statements, answers, gold patches and
tests are not copied here; the harnesses fetch them from the pinned sources on the node.

| benchmark | source | pin | license | in manifest |
|---|---|---|---|---|
| SWE-bench Verified | HF `princeton-nlp/SWE-bench_Verified` (test) | `c104f840cc67f8b6eec6f759ebc8b2693d585d4a` | see dataset card | 500 instances; difficulty = annotators' time-to-fix label |
| τ²-bench | GitHub `sierra-research/tau2-bench` | `96a3ef92329baf908ffe9dfe188cea34e8701d2a` | MIT | base sets: airline 50, retail 114, telecom 114 |
| Terminal-Bench 2 | GitHub `harbor-framework/terminal-bench-2` | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` | Apache-2.0 | 89 tasks; task.toml difficulty, expert/junior minutes, image |
| Aider polyglot | GitHub `Aider-AI/polyglot-benchmark` | `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f` | not declared by repo (Exercism exercises) | 225 exercises, 6 languages |
| AIME 2025 | HF `MathArena/aime_2025` | `c94da77eb22bbd6439e62a323bec18493a421302` | CC BY-NC-SA 4.0 | 30 problem ids |
| HMMT Feb 2025 | HF `MathArena/hmmt_feb_2025` | `6fdc4277120810ff75aa22d2d5489b91f7a262a1` | CC BY-NC-SA 4.0 | 30 problem ids |

Fetched 16 Oct 2026. `fetch_task_metadata.sh` + `build_manifests.py` reproduce `manifests/` byte for byte
(checked 16 Oct 2026; `manifests/SHA256SUMS`).

## Difficulty spread

| benchmark | easy / short | medium | hard / long |
|---|---|---|---|
| SWE-bench Verified (time to fix) | <15 min: 194 | 15 min–1 h: 261 | 1–4 h: 42, >4 h: 3 |
| Terminal-Bench 2 (task.toml) | easy: 4 | medium: 55 | hard: 30 |
| τ²-bench (reference pass rate, below) | retail | airline | telecom |

The hard SWE-bench instances come from django (22), sympy (7), sphinx (5), astropy (3), pytest (3), xarray (2),
pylint (2) and scikit-learn (1).

## Reference scores (vendor model cards, checked 16 Oct 2026)

Used to check that our serving setup is competent: our reference-precision score should land near these.

| model | benchmark | reported |
|---|---|---|
| Qwen3-30B-A3B-Instruct-2507 | τ²-bench retail / airline / telecom | 57.0 / 38.0 / 12.3 |
| | BFCL-v3 | 65.1 |
| | Aider-Polyglot | 35.6 |
| | AIME25 / HMMT25 | 61.3 / 43.0 |
| Devstral Small 1.1 (2507) | SWE-bench Verified (OpenHands) | 53.6 |

Vendor numbers use the vendors' own harness and settings; record any difference in ours (scaffold, context
limit, sampling, number of tries).

## Pilot selection (`manifests/pilot_selection.json`, seed 20261016)

| benchmark | selected | rule |
|---|---|---|
| SWE-bench Verified | 85 | all 45 of 1–4 h and >4 h; 30 of 15 min–1 h; 10 of <15 min |
| τ²-bench | 100 | official test splits: airline 20, retail 40, telecom 40 |
| Terminal-Bench 2 | 85 | all hard (30) and medium (55) |
| Aider polyglot | 60 | 10 per language |
| AIME25 + HMMT25 | 60 | all |

Run the pilot at the reference precision (8-bit), record each task's pass rate, then keep tasks with pass rates
between about 10% and 90% for the precision comparison. Tasks at 0% or 100% at both precisions carry no
precision signal.

## Run notes

- τ²-bench needs a second model to play the user. Serve it on a separate GPU, or exclude its energy, and record
  which.
- SWE-bench and Terminal-Bench run one Docker container per task; pull only the selected images.
- Terminal-Bench 2 tasks declare `allow_internet = true` and no GPU; agent timeouts range from 600 s to 12000 s.
