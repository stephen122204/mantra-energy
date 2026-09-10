# Latest published context: stephen

[Immutable turn record](turns/20260909-sigmetrics-accepted-paper-opportunities.md)

# SIGMETRICS research opportunity map for ALEMS

Prepared September 9, 2026. Exploratory research guidance; no student assignment, frozen experiment or hardware reservation is changed by this note.

## Task and current understanding

The objective is to derive a substantive research question from the assumptions and findings of prior accepted work, rather than add models to the existing configuration sweep. Goal-level energy accounting is an enabling measurement boundary. It is not, by itself, a verified gap.

This pass screened the official SIGMETRICS [2024 program](https://www.sigmetrics.org/sigmetrics2024/program.html), [2025 program](https://www.sigmetrics.org/sigmetrics2025/program.html), and [2026 program](https://www.sigmetrics.org/sigmetrics2026/program_at_a_glance.html), read selected full papers and official abstracts, and checked adjacent recent work. Conference years below refer to presentation years; POMACS publication dates can differ. This is a targeted opportunity map, not an exhaustive systematic review or acceptance prediction. A paper's deliberate scope boundary is not a defect.

My inference from these examples is that productive extensions change an assumption, decision or resource interaction, then explain its consequences. Adding a workload label or a measurement metric without a new finding is weaker. A strong measurement paper need not introduce a new neural architecture or prove a scheduling theorem; it still needs convincing evidence and an explanation that transfers beyond its examples.

## Ideas and hypotheses

### What accepted work offers us

| Accepted work | Established result or scope | Research principle we can carry into ALEMS |
|---|---|---|
| **Agents of Autonomy / RoWild, SIGMETRICS 2024** | Studies complete robotic computation pipelines across hardware, with independently checked results and analysis of hardware inefficiencies. Full paper inspected. | Connect the application's actual objective to component behavior. Whole-application analysis is an established research method, not a new invention of ours. [Paper](https://www.pdl.cmu.edu/ftp/associated/bakshalipour-Agents-of-Autonomy.pdf) |
| **Change Point Detection with Adaptive Measurement Schedules, SIGMETRICS 2024** | Treats when to measure as a decision, balancing measurement cost, detection delay and false alarms. Author-hosted institutional thesis material and research poster inspected. | A check can itself consume resources and change when the system reacts. Ask when information is worth its acquisition cost. [Author poster](https://internal.wasp-sweden.org/winterconf2024/posters/simon_lindstahl.pdf) |
| **Application-driven Reexamination of Datacenter Microbursts, SIGMETRICS 2025** | Explains why mitigation effectiveness depends on the application-generated characteristics of congestion. Official abstract inspected, not full paper. | Identify an application property that predicts which optimization will work; do more than report varying speedups. [Official abstract](https://www.sigmetrics.org/opentoc/sigmetrics25toc.html) |
| **NetJIT, SIGMETRICS 2025** | Uses program behavior and data relations to anticipate communication rather than relying solely on traffic prediction. Official abstract inspected; full paper not retrieved. | Program structure may expose useful information before hardware counters reveal a bottleneck. For agents, test whether a tool or task transition supplies genuinely additional information. [Official abstract](https://www.sigmetrics.org/opentoc/sigmetrics25toc.html) |
| **UniCache, SIGMETRICS 2026** | Distinguishes session and structural prefix reuse, including agentic trajectories, and designs an eviction policy for heterogeneous traffic. Full paper inspected, especially workload and reuse analysis. | Model the lifetime and reuse of state, not just how many tokens are generated. Agent-aware caching is already occupied territory. [Paper](https://jxing.me/pdf/unicache-sigmetrics26.pdf) |
| **Characterizing Performance–Energy Trade-offs of Large Language Models in Multi-Request Workflows, SIGMETRICS 2026** | Measures workflow energy/latency and component energy for four workloads, including multi-agent coding. Its discussion explicitly excludes MoE, quantization and CPU–GPU co-scheduling from its controlled study. Full HTML, metrics and discussion inspected. | This is a direct baseline and overlap. Investigate a mechanism involving these omitted dimensions rather than claim workflow energy is missing. [Paper](https://arxiv.org/html/2604.09611v1) |
| **Minos, SIGMETRICS 2026** | Classifies GPU workload performance/power behavior and supports economical characterization. Abstract inspected this turn; previously reviewed as a close profiling baseline. | Relate measurements to decision quality and include the cost of collecting them. Cheap profiling is not an untouched contribution. [Paper](https://arxiv.org/abs/2604.03591) |
| **Optimal Scheduling Algorithms for LLM Inference, SIGMETRICS 2026** | Develops scheduling models and throughput/SLO policies using prefill/decode resource structure. Author paper introduction/contributions inspected. | Write an explicit objective and resource model. Token deadlines, request throughput and verified goal completion are different objectives, but their difference alone is not proof of novelty. [Paper](https://users.ece.utexas.edu/~gustavo/papers/BHD25j.pdf) |

### Candidate A: architecture-dependent cost of resuming useful work

**Question:** When an agent pauses, branches or revises its work, what state is worth preserving, and can a policy use that information to reduce the measured cost of reaching a verified result?

This combines application-level analysis, reuse/lifetime modeling and architecture-dependent state costs. Attention-based models retain KV state. Recurrent/hybrid models introduce different checkpoint and recomputation choices. MoE adds expert-weight residency as another resource dimension. These are not three mutually exclusive model categories: a model can combine MoE with hybrid attention/recurrent layers.

A concrete experiment would capture naturally occurring reuse and revision boundaries, then compare ways to retain inference state under a fixed memory budget. Measure save/restore/recompute costs and complete-goal energy and latency. First hold the request sequence fixed to isolate system effects; then test live independently verified goals. Do not confuse restoring inference state with undoing external tool side effects. File/database state requires its own consistent snapshot or sandbox reset.

The possible contribution is an experimentally validated rule for when retaining a particular state is worth its memory and energy cost, tied to a new interaction between goal behavior and architectural state. It is **not** simply adding checkpointing to a hybrid model. [Sparse Prefix Caching for Hybrid and Recurrent LLM Serving](https://arxiv.org/abs/2605.05219) already formulates checkpoint placement, including empirical overlap estimation and drift analysis. A proposed policy must improve on the relevant existing method or establish a new limitation under the goal/recovery objective.

**First discriminating test:** Does the same goal trace incur a substantial, repeatable resumption/recomputation cost under feasible memory budgets, and does goal-boundary information improve decisions beyond existing overlap/reuse information? Stop pursuing this formulation if there is negligible cost or existing policies already capture all useful signals.

**Engineering burden:** Highest of these candidates. Needs a backend exposing exact state extraction/restoration, memory occupancy and cache/recomputation events. Existing ALEMS sensor readings and request logs do not supply these capabilities. Select one architecture and one decision first; a dense/MoE/hybrid matrix is not the starting requirement. Real physical memory constraints and a fully resident control are preferable to a conclusion based only on artificially restricted memory.

### Candidate B: when should an agent pay to check its work?

**Question:** Can we schedule intermediate executable correctness checks to reduce total energy and completion time, while holding the final independent correctness standard fixed?

This combines the adaptive-measurement principle with the fact that an agent's mistakes change how much future work must be performed. In a repository task, checking after every edit spends CPU time and may leave the GPU waiting; checking only at the end may allow an error to propagate through subsequent changes. The economically preferable schedule could depend on the cost of a check, its chance of finding an actionable error, the work it can save, and the model/runtime's repair cost.

The decision is **when to invoke an existing deterministic check**, not whether to believe an LLM judge. Never weaken required final verification or mandatory enforcement checks. Available intermediate tests must be separate from held-out final evaluation tests, so the policy cannot learn hidden answers.

Compare terminal-only discretionary checking, fixed-interval checking, every-eligible-boundary checking, inexpensive failure-triggered checking and a cost-aware policy. Count the energy/time of checks, successful forward execution, repairs, failed attempts and owned waits. A policy that reduces checks but increases wrong completions is not a success.

The new scientific target would be a predictive boundary: when does the cost of an intermediate check become smaller than the downstream work it prevents, and can this be predicted well enough to guide execution on new tasks? A useful explanatory decomposition is forward work + checks + recovery + measured owned waiting. This bookkeeping identity is not itself a contribution.

**Known overlap:** [AgentStop](https://arxiv.org/abs/2605.15206) already studies energy wasted on unsuccessful agent trajectories and early stopping. [Strategic Verification for Long-Running LLM Agents](https://www.preprints.org/manuscript/202608.2057) already proposes event-triggered verification under resource budgets; its displayed ablation examples are explicitly illustrative rather than empirical results. Thus neither adaptive verification nor failed-trajectory energy is a unique claim. A fuller verification/test-selection literature review remains necessary before selecting this topic.

**First discriminating test:** On real repair-capable tasks, do check timing and repair work materially change measured energy at comparable success? Use controlled fault injection only to validate mechanisms, and report it separately from naturally occurring model errors. If all checks are essentially free or failures do not propagate, this candidate has little opportunity on that workload.

**Engineering burden:** Closer to the current team architecture than Candidate A. Reuses the executor, independent verifiers and failure-preserving ledger, but requires genuine multi-step repository tasks, a check-scheduling hook and repair/event accounting. The tiny sales fixture cannot substantiate it. Architecture variation would test a specific predicted change in repair economics after the mechanism is established on one model, not serve as an uncontrolled causal comparison.

### Candidate C: agent hints for MoE expert preparation

**Question:** Does information available before a tool finishes improve prediction of the next expert working set sufficiently to make preparation useful?

This is the previous candidate, now grounded in the program-information principle illustrated by NetJIT. The required evidence is incremental predictive value beyond routing history, actual useful transfers, and net goal-level benefit including overhead and interference. It requires expert routing/residency instrumentation; a power trace alone cannot explain it.

Its comparison bar is higher than the earlier discussion implied. [WiSP](https://arxiv.org/abs/2606.21868) already studies MoE expert/KV memory allocation and reports unhelpful speculative transfers in its single-stream setup. [MORI](https://arxiv.org/abs/2606.00866) exploits tool-call idleness. [CacheScout](https://arxiv.org/abs/2608.14624) already learns agent execution transitions to guide KV eviction and prefetch. The opportunity, if any, must concern a distinct expert-memory mechanism and useful signal, not generic agent-aware prefetching.

**First discriminating test:** Does phase/tool metadata improve held-out next-expert demand prediction over routing-history baselines? If so, can the available idle window and bandwidth turn this into a physical benefit without slowing the tool? If weights are fully resident, do not attribute any improvement to avoided offloading.

## Decisions and rationale

Keep two lines of exploration visible: Candidate A for the architecture/state question and Candidate B for the most direct reuse of our existing workload/verifier infrastructure. Keep Candidate C as an alternative rather than presume it is the best paper. This is a recommendation for bounded discovery, not a final choice or a requirement to implement all three.

The common research direction is **how the cost of reaching and preserving correct progress changes system decisions**. This umbrella is intentionally broader than the final submission should be. Choose one decision, one main mechanism and one primary environment after initial evidence. A combination becomes valuable when it produces a result or decision rule neither component supplies by itself; combination alone does not establish originality.

Do not assume that adding goal-level analysis to an old paper creates an unoccupied gap. Current adjacent work includes [MARS](https://arxiv.org/abs/2604.26963) on coupled CPU/GPU agent scheduling and [TOPAS](https://arxiv.org/abs/2608.25523) on joint prefix-state scheduling for task completion time. These are preprints in the present review, not papers verified as SIGMETRICS acceptances. Their existence makes generic workflow scheduling a poor novelty claim.

## Changes and artifacts

Created this research opportunity map and a matching immutable shared research-context record. No application code, experiment configuration, branch history, assignment, deadline or reservation was changed. The student's common runtime, workload, measurement and reproducibility work remains useful whichever candidate is selected.

## Tests and evidence

Repository inspection refreshed private integration at **08ac06aabe8f9756b9b851ccd9879aa732e31346**. The inspected local review code remains **e6095cc58a62b3e146f2f5c7b375cd8d783a622b**. No open PRs were listed at this check.

- Merged evidence includes Aldric's first independently recomputed CSV verifier and Nitheesh's fixture execution ledger, with PR 22's integration repairs.
- The study runtime directory still contains a README stating implementation is pending.
- No full study executor, four-task pilot, live collector integration or measured architecture experiment is present in the inspected study tree.
- Alex has no published implementation turn in the inspected shared context. This is unknown local progress, not proof that he has done nothing.
- The published ledger demo explicitly invokes no live model or tools and measures no hardware energy.

No new code tests or physical experiments were run for this literature review. Earlier passing component tests are not reclassified as system readiness.

## Open questions and disagreements

1. Which candidate has both a new mechanism and a feasible implementation path within the remaining paper schedule?
2. Can the chosen backend expose state or expert events with acceptable overhead, and can it preserve semantics under interventions?
3. Are intermediate correctness checks sufficiently costly and failures sufficiently consequential for Candidate B?
4. Can a method outperform strong simple policies and the closest published approach on unseen task instances?
5. How much uncertainty remains after accounting for task and session variation, rather than treating sensor samples as independent experiments?
6. Does the measured CPU/GPU/domain coverage support the intended energy claim? Report measured domains honestly rather than labeling their sum wall-plug energy.

No candidate is certified unique, no negative result is automatically publishable, and no acceptance probability is inferred from topic similarity.

## Next actions and handoff

First complete one actual, independently verified local-model goal with synchronized measured energy, failure capture, clean termination and a reproducible ledger export. That is the entry gate to using ALEMS as an experimental instrument.

Once that gate passes, budget a short discovery pass rather than the full campaign: a few tasks deliberately spanning the proposed mechanism, paired interventions and a baseline that could disprove the idea. A two-to-three-day probe is a planning estimate only after the required instrumentation is usable; backend development can take longer. The small probe determines feasibility and effect size, not publication-level significance.

For the selected candidate, require three pieces of evidence before expansion: (1) the mechanism is observable, (2) it changes the preferred action relative to a relevant simple baseline, and (3) a model of that mechanism predicts outcomes on new tasks or conditions. Then define the task/session sampling, repeat count from pilot variation, frozen success/latency constraints, overhead accounting and appropriate held-out evaluation.

Student responsibilities remain: Alex produces the trustworthy runtime and measurement path; Aldric produces real task execution and independent verification; Nitheesh produces the scheduler/ledger/export path; Stephen owns integration, the research decision and evaluation design. New architecture hooks or intermediate-check policies require explicit scoped interface additions. Do not silently broaden student assignments because an exploratory note lists possible experiments.
