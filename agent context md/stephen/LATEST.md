# Latest published context: stephen

[Immutable turn record](turns/20260909-industry-signals-and-mathematical-models.md)

# Industry signals and mathematical models for ALEMS

## Task and current understanding

Stephen asked what AI companies publicly disclose about efficiency, whether X/Telegram contain useful research leads, and which scientific/mathematical tools could support an ALEMS contribution involving MoE, distillation or joules/token. This continues the prior research-opportunity discussion. No research direction has been frozen and no training or hardware campaign is authorized by this brainstorming.

## Ideas and hypotheses

The most concrete continuation of the prior state/resumption candidate is to investigate when retained inference state changes the energy-optimal choice over a complete agent task. A smaller or more compute-efficient model may incur state reconstruction, transfers or additional repairs that overwhelm immediate savings. This is a hypothesis requiring controlled physical measurement, not an asserted finding or unique gap.

Public evidence and leads:

- Anthropic's Claude Code engineering article describes model-specific prompt caches, costly mid-session model changes, stable tool definitions, and cache-conscious compaction. These are engineering statements about cost and latency, not disclosed joules measurements. [Official article](https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything).
- An indexed discussion points to Thariq's [X post](https://x.com/trq212/status/2024574133011673516). The original X page could not be opened by the web reader; the technical claims used here were verified in the official article instead. Do not imply access to private posts or insider disclosures.
- Factory describes model routing that accounts for cache state and task outcomes. This directly overlaps a generic cache-aware model-selection proposal. [Engineering article](https://factory.ai/news/model-routing-belongs-in-the-harness). Its financial savings are not physical energy measurements.
- NVIDIA publicly combines MoE, hybrid Mamba/attention architectures, pruning and distillation in its Nemotron research. [Nemotron family](https://research.nvidia.com/labs/nemotron/Nemotron-3/), [hybrid MoE compression paper](https://arxiv.org/abs/2607.04371). These are not mutually exclusive architectural categories, and inventing a new foundation model is not needed for our measurement investigation.
- Public [Telegram digest](https://t.me/s/kdnuggets) surfaced FreeToken; technical scope was checked against the [paper](https://arxiv.org/abs/2608.16157). It already co-designs expert residency, CPU/GPU execution and agentic state reuse. The inspected HTML focuses on serving performance; no energy/joules terms were found. That textual absence is not a proof that its authors have not investigated energy elsewhere.
- [DeepSeek-V3 technical report](https://arxiv.org/abs/2412.19437) publicly describes MLA and MoE design. It does not justify guessing the internals of other proprietary models.
- A community [DeepSeek issue](https://github.com/deepseek-ai/DeepSeek-V3/issues/1521) proposes energy-constrained value-of-computation. Its author is hiderguardian-design. Treat it as an unvalidated community proposal, not DeepSeek endorsement, an implementation or evidence of results.
- [End-to-End Energy Accounting of Distillation Pipelines](https://arxiv.org/abs/2605.13981) already accounts for teacher-side generation/caching and student training, with energy-quality comparisons. Distillation energy accounting and simple amortization cannot be claimed as new.
- [Cross-Model KV Cache Transfer](https://arxiv.org/abs/2608.03893) already explores mappings between model caches. Reported quality varies across model pairs; cache transfer is not generally exact or compatible across arbitrary models.

### Appropriate mathematical tools

1. **Measured reward/cost accounting over completed tasks.** Report cohort energy per verified completion as total measured energy of all attempts and included overhead divided by verified successes. Always accompany it with success rate and deadline/latency statistics. A zero-success cohort has no finite energy-per-success value. Do not drop failed attempts or substitute zero for missing energy. J/token remains a diagnostic metric, not a sufficient task objective.

2. **Semi-Markov cost model.** Represent operational stages such as inference, tool execution, checks, repair and state restoration, each with an observed duration and energy distribution. Include context size, cache/residency state, model identity, remaining budget and available progress indicators where useful. Predict downstream costs when actions change stages or restore state. A short feature vector is not automatically Markov; validate history dependence and predictive residuals. A fitted model does not prove causal effects without interventions. Semi-Markov models already appear in LLM energy work, e.g. [GLOBECOM 2024 paper](https://arxiv.org/abs/2408.15907); naming the model is not novelty.

3. **Hardware bottleneck model.** Use [Roofline](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-134.html) to reason about arithmetic versus data movement, extended with measured host/GPU transfer limits when offloading. It supplies performance bounds, not joules estimates. Energy needs measured power over time. For MoE, active parameter counts alone do not determine transferred bytes or energy. Cache hits, total resident weights, memory bandwidth and execution kernels matter.

4. **Finite-horizon switching/investment decisions.** Compare expected remaining savings against transition costs and changes in downstream repair cost under fixed correctness/deadline requirements. Estimate future demand conservatively and include prediction overhead. A simple break-even threshold is a baseline. More elaborate optimal control or online learning is justified only if repeated observations demonstrate that it changes decisions usefully.

5. **Experimental identification and uncertainty.** Use paired, randomized-order interventions and task/session-level uncertainty. Establish mechanisms within a model before comparing model families. Fixed traces isolate systems behavior; live tasks reveal quality and trajectory changes. Neither substitutes for the other. Instrumentation overhead and incomplete measurement coverage remain explicit.

### Concrete equations and their scope

For a cohort, J_per_verified_goal = (sum of included measured execution and overhead energy) / (number of independently verified successful goals). Define the cohort, domains and accounting window in advance. This is an empirical ratio, not a promise that every task will eventually succeed.

A provisional switching rule is: expected remaining energy saved > state reconstruction/transfer energy + additional expected repair energy + decision overhead, subject to success and deadline constraints. These terms must cover disjoint costs; fit/check them against measured totals to avoid double counting. Existing cache-aware routers are required baselines, not a novelty straw man.

For distillation, a simple stationary break-even calculation is N_star = E_build / (e_teacher - e_student), only when the denominator is positive and the choices meet the same declared quality/deadline requirements. e_teacher and e_student must cover comparable goal-level costs including repairs; E_build includes teacher data generation, training and validation within scope. Workload drift, refreshes and uncertain future volume invalidate the simplest stationary calculation. A local evaluation of an existing distilled model does not reveal its historical training energy; report unavailable creation costs rather than invent them or infer joules from API bills.

## Decisions and rationale

Continue the same architecture/state-resumption problem class, using public company reports to motivate the mechanism. Do not silently replace it with a large distillation or foundation-model-training project. Existing released models can support the first physical probe. New distillation would add data, teacher/student memory, training and evaluation requirements and must be separately scoped if the evidence warrants it.

A defensible candidate claim would explain a new regime where a conventional energy/throughput heuristic selects the wrong execution choice and offer a validated correction. Measuring energy for an existing optimizer alone does not establish that claim. Exact prior-art clearance remains incomplete, particularly for state-aware routing and goal-level repair costs.

## Changes and artifacts

Research context only. No application code, frozen configuration, student assignment or hardware booking changed. Public-source URLs and reviewable mathematical assumptions are recorded here for team reuse.

## Tests and evidence

Fetched integration was bd24f3d5e7e2a3fe51890de3f8582ad9b4deeb6e. Alex, Aldric and Nitheesh latest published status was unchanged from the prior check. The first workload verifier and execution ledger are merged; a measured live end-to-end study run is still not evidenced in shared context. Private/local contributor progress remains unknown.

No physical runs, model downloads, distillation jobs or new code tests were performed. Social discovery used public indexed pages only; no private Telegram group or account was accessed. Primary company/research sources support technical claims; social posts were leads.

## Open questions and disagreements

- Does cache/residency state materially reverse an energy decision, or do existing throughput/cost-aware methods already choose correctly?
- Is the chosen model pair supported by a common controllable backend on the actual assigned hardware?
- Can state rebuild, transfer and repair costs be measured separately without unacceptable observer overhead?
- Do model changes preserve sufficient task capability, and are extra repairs common enough to matter?
- Does a finite-horizon model predict held-out choices better than simple measured break-even and cache-aware baselines?
- Can any discovered limitation be scoped beyond a single accidental kernel or unsupported deployment configuration?

## Next actions and handoff

Complete the existing model/tools/measurement/verifier/ledger integration gate first. Then define one bounded development probe using real tasks and existing local models: warm continuation, forced cold context reconstruction, and a controlled model handoff where supported. For MoE, add a residency/offload intervention only if the backend and real memory budget make it meaningful. Do not present cross-model differences as a pure architecture effect.

Collect input/output token counts, reused versus recomputed context, phase timings, model identity, available memory/transfer events, tool/check/repair events, CPU/GPU energy, success and deadline outcomes. Fit a simple interpretable cost model on development data and test whether it predicts an action reversal on unseen tasks or contexts. The first few tasks are a feasibility probe, not the publication dataset. Expand only after evidence identifies a mechanism and a contribution beyond current baselines.
