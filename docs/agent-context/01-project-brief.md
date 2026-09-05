# Project brief: from energy accounting to energy diagnosis

## Question and intended contribution

For a verifiable agentic goal, which feasible execution change reduces measured energy while preserving correctness and an acceptable completion time? Can a diagnostic method choose that change with fewer profiling executions than testing every candidate?

A-LEMS connects goals, attempts, execution events and hardware observations. This project aims to turn those observations into useful intervention decisions. Energy charged to a phase is not necessarily the energy saved by accelerating it: idle power, overlap, cache state and changed runtime can alter the result.

The technical contribution is still to be developed. A promising target is a small-budget decision procedure using dependency/resource observations, measured interventions and uncertainty. We must show why it works, when it fails and whether it adds value over simple profiling. Fixing A-LEMS bugs is necessary engineering, not the paper's scientific discovery.

## Narrow scope

- One primary Grace A100 environment, subject to measurement preflight.
- One locally served model and frozen runtime. Qwen2.5 7B Instruct Q4_K_M through Ollama is a proposed pilot candidate, not an installed or scientifically frozen choice. Current A-LEMS also registers vLLM models; first inspect Deepak's working environment. A functioning existing local stack can be selected instead before freezing the study.
- Two task families: local structured-data analysis and repository analysis with independently checkable outcomes.
- One goal at a time initially; one concurrent model request. Experimental concurrency applies to independent ready tools.
- Four candidate settings, with the same allocated CPU/GPU resources:

| Candidate | Maximum concurrent ready tool calls | Workers per tool |
|---|---:|---:|
| C00 | 1 | 1 |
| C10 | 2 | 1 |
| C01 | 1 | 4 |
| C11 | 2 | 4 |

These controls are proposed extensions, not verified existing A-LEMS functionality. C00 is an experimental reference, not automatically the deployment default. Measure the real default and add it if different; regenerate counts and budgets when the candidate set changes. Verify the chosen tools have meaningful worker controls in both families.

## Two experiments, kept separate

1. **Conditional replay:** preserve recorded logical model/tool requests, inputs and dependencies, and physically execute them under alternative mechanics. Log generated-output/token divergence. If downstream inputs are frozen despite newly generated output, label that conditioning explicitly; it is not a closed-loop agent run.
2. **Live validation:** execute the original goal under the selected policy, use actual newly produced outputs throughout, and apply the unchanged independent verifier.

Paired candidate energy differences support the first claim. Correct, efficient new goal completions support the second. Neither substitutes for the other.

## Evidence required

Report energy per verified completion, success fraction, latency distribution, profiling cost and measured-domain coverage together. At policy level, divide energy for all submitted goals, including failed attempts and owned waits, by the number independently verified. With zero successes the ratio is undefined. Missing measurements require disclosure, not silent exclusion.

Compare against deployment default, simple timing/token/phase heuristics where meaningful, uniform profiling, ordinary factorial screening and an independently measured exhaustive candidate reference. Use comparable information and profiling budgets. The four-setting reference is only the best tested feasible option, not a universal optimum.

Initial planning: 4 pilot goals, 20 development goals and 40 held-out goals, two families, 3 repetitions per relevant comparison. The existing full schedule has 1,432 planned executions across all stages, not 1,432 independent tasks or completed results. Pilot variance and workload validity determine whether this design is adequate.

## Research gate

Do not expand automatically if ordinary screening is as good at similar cost, candidate effects are below measurement resolution, or goals have no meaningful scheduling choice. Stephen decides whether to change the method, task scope or submission target. Negative results remain data.

The Fall abstract deadline is 2 October 2026 and paper deadline 9 October 2026, 23:59 AoE, per the [official CFP](https://www.sigmetrics.org/sigmetrics2027/pages/cfp.html). Venue fit is plausible under measurement/problem diagnosis; novelty and acceptance are unestablished.

Excluded from the initial scope: model training, multi-GPU scaling, broad model sweeps, arbitrary agent frameworks, physical wear/lifetime estimates, carbon estimates, Shapley attribution as the main invention, and a separate full campaign on every available cluster.
