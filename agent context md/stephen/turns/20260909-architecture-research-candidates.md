## Task and current understanding

Stephen asked to consider creative architecture-dependent research questions, including MoE, rather than constrain the SIGMETRICS contribution to the existing configuration selector. This is exploratory research guidance, not a change to assignments or authorization for a larger hardware campaign.

## Ideas and hypotheses

Candidate A: agent tool boundaries may provide advance information about the next MoE expert working set. Test whether tool identity and execution phase add predictive value beyond recent routing history, and whether useful transfers can fit into otherwise idle tool windows without competing excessively with tool CPU, memory or I/O work. A useful outcome requires net energy or latency improvements under fixed correctness, including prediction and transfer overhead.

Candidate B: identify and predict conditions under which dense versus MoE energy rankings reverse over verified goals as context retention, memory pressure and tool behavior change. Comparing two architectures alone is insufficient; within-model interventions and a predictive boundary are needed to explain the mechanism. Model-family and quality differences confound architectural causality.

Candidate C: quantify whether energy-tail events at agent transitions create goal deadline or energy-budget violations that average token metrics miss. A useful contribution would require a predictive or preventive method and enough independent runs for credible tail estimates; the four-task pilot is insufficient evidence.

## Decisions and rationale

Prefer a bounded feasibility probe of Candidate A before proposing a change to the paper. First test whether tool/phase labels add held-out predictive signal to routing-history baselines. Then test whether that signal can improve actual transfers, with no speculative transfers as a baseline. No claim that this gap is unique has been verified. Combining existing caching and tool-idleness techniques alone does not establish novelty.

Do not infer an offloading mechanism when all model weights fit on the GPU. Use a fully resident control and, if justified, a real memory-constrained deployment; artificial memory limits alone are weaker evidence. A large-memory H100 may conceal this mechanism for a small MoE. Model choice and usable hardware require a probe before committing resources.

## Changes and artifacts

Research context only. No code, student assignments, frozen configurations or reservations changed. Existing executor, verifier, ledger and telemetry work remains useful across these candidates.

## Tests and evidence

Primary sources inspected during this turn:

- https://arxiv.org/abs/2606.21428 — MoE/dense throughput, memory and energy comparisons on consumer/edge hardware already exist.
- https://arxiv.org/abs/2603.11114 — task-conditioned MoE routing signatures already reported; not proof of tool-boundary prediction or system benefits.
- https://proceedings.iclr.cc/paper_files/paper/2026/hash/6a7a2238da2b755e6dc1dbe278c60c2a-Abstract-Conference.html — routing consistency and offloading efficiency across 20 MoE models.
- https://arxiv.org/abs/2606.21868 — WiSP already handles expert/KV memory competition, includes agentic workloads, and reports that speculative expert prefetch did not benefit single-stream decode under its measured bandwidth limits.
- https://arxiv.org/abs/2606.00866 — MORI already exploits tool-call idleness for KV offloading. Tool pauses alone are not an unoccupied contribution.
- https://arxiv.org/abs/2608.15127 — broad characterization of agentic serving bottlenecks already exists.
- https://arxiv.org/abs/2411.08982 — batching and aggregate expert activation are an existing research topic.

No experiments run and no new implementation tested this turn. These sources narrow candidate claims; this is not an exhaustive novelty audit.

## Open questions and disagreements

Does tool information improve prediction beyond token/routing history on held-out tasks? Does the target backend expose expert IDs, cache residency and actual transfers? Are useful transfers possible during tool execution without consuming more energy or worsening host-side work? Does a policy improve over established expert cache/prefetch and tool-idleness baselines? Is this feasible on the current deadline? Unresolved.

## Next actions and handoff

If Stephen selects Candidate A for exploration, specify a bounded probe with expert-routing traces, phase/tool boundaries, bytes transferred, cache misses, KV reuse, CPU/GPU energy and instrumentation overhead. Begin with controlled request traces, then independently verified live goals. Include no-prefetch, routing-history prediction, phase-aware prediction and fully resident controls. A lack of predictive information or a bandwidth bottleneck is a decision to revise the candidate, not automatically a publishable negative result. Continue current authorized integration work without silently replacing the student scope.
