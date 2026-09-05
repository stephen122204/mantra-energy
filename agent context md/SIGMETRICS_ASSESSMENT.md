# SIGMETRICS assessment: what has and has not been vetted

Updated 5 September 2026. **Venue fit and a plausible research direction have been vetted; a SIGMETRICS-level contribution has not yet been established.** Existing work and the proposed experiments make this a reasonable investigation, not an acceptance-ready result.

## Why the venue fits

The [SIGMETRICS 2027 CFP](https://www.sigmetrics.org/sigmetrics2027/pages/cfp.html) explicitly includes problem diagnosis, system measurement, experimental design and energy-efficient systems. Its Measurement & Applied Modeling track seeks significant empirical insights or useful models/methodologies. A principled intervention-selection method supported by sound measurements fits that remit. Topical fit alone is insufficient.

The earlier review examined recent [accepted SIGMETRICS papers](https://www.sigmetrics.org/sigmetrics2026/accepted.html) and close work including Minos, Causal Agent Replay, JouleShare, ML.ENERGY and AgenticBench. Read the [source/status record](../docs/agent-context/13-sources-and-status.md). This was targeted, not an exhaustive proof that no competing method exists. Current CFP and accepted-paper listings were checked again for this update.

## What goal-level means here

The unit of useful service is an independently verified goal under a fixed task contract, not a token, model request or tool span. The measurement includes the goal's attempts, inference, tools, owned waits and verification under an explicit boundary. Failed attempts contribute cost; they do not disappear because no correct output was produced. Only nonoverlapping observed energy domains may be combined.

The new question is whether observations about the complete workflow let us choose an execution change that improves energy per verified completion while respecting latency and success constraints on unseen goals. Merely labeling measurements with a goal ID, inventing another composite score or testing extra platforms would not establish the intended advance. A-LEMS already contributes goal-level accounting.

## Candidate scientific claim

Under a declared class of goal workflows, state and dependency information plus a limited number of measured interventions can identify useful execution changes more economically or reliably than simple phase/token/time heuristics and ordinary configuration screening. The method should explain when a locally attractive optimization is unhelpful at the goal level and validate recommendations in new live executions.

This claim remains a hypothesis. Conditional replay can diagnose fixed logical work; live evaluation must still use newly produced outputs and the unchanged independent verifier. Replay and energy attribution are existing ideas, so we must demonstrate a substantive decision capability rather than merely combine their names.

## Main unresolved significance risk

Our four configurations vary two familiar controls: tool concurrency and workers per tool. An ordinary sweep or two-query screen may already choose well enough. If that happens, adding an agent/goal label is incremental. Do not enlarge the candidate space arbitrarily to make a weak method look necessary. Investigate real decision difficulty, interactions and state dependence on representative goals, including cases with little optimization opportunity.

## Evidence required before calling it a strong submission

1. Relevant naturally occurring goal workloads with objective verifiers and varied dependency/resource behavior.
2. Valid CPU/GPU energy boundaries, isolation and uncertainty that resolve the effects being claimed.
3. A documented decision failure or cost limitation of credible simple alternatives, with a measured mechanism.
4. A specified method that uses only available information and a fair profiling budget, including its development/profiling costs.
5. Independent held-out recommendations and live verified benefit, reporting energy, success and latency together.
6. Ablations, no-benefit/failure cases, replay limits and a clear boundary from the existing A-LEMS/platform work.

There is no established percentage-improvement or platform-count threshold that guarantees acceptance. One characterized platform can support a scoped result; a second should test a transfer claim. If ordinary screening matches the method at comparable cost or the effect is below measurement resolution, revise the research claim before expanding the campaign.

**Current decision:** continue the bounded engineering and opportunity pilot. ED-10 is the scientific significance checkpoint, not a paperwork step after the pipeline is built.
