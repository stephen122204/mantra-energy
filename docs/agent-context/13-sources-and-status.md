# Evidence and source status

Prepared 5 September 2026. This pack is a curated synthesis of the project's earlier code/literature review and Stephen's latest Alex screenshots. It is not an exhaustive literature search or a fresh full repository audit.

## Evidence levels

- **Code-reviewed:** selected files at `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`. Model loader, YAML registry, adapter, agent executor, factory and root license were additionally checked for this handoff. No upstream build or cluster experiment was run.
- **Reported access:** Alex's screenshots supplied in this conversation; no screenshots or account credentials are redistributed. Awards and telemetry claims remain distinguished from current balance and sensor validation.
- **Existing local planning code:** copied generator, manifest and data contract in starter/. Their original source is the September 4 diagnostic-launch package. Placeholder entries remain unfilled.
- **Proposed:** role split, module interfaces, model, candidates, campaign size and method. These require implementation and pilot evidence.
- **Verified current documentation:** GitHub fork visibility and SIGMETRICS deadlines checked for this handoff; hardware/runtime links were checked during this conversation. Resource documentation does not establish a reservation.

## Important corrections to older context

1. Alex now reports usable team GPU allocations and approved Explore ACCESS. Older documents saying ACCESS was only submitted are historical.
2. Active model routing uses models.yaml through core/models_loader.py; the remaining models.json is not sufficient evidence of current runtime configuration.
3. vLLM provider/model entries already exist. Do not assume a vLLM integration must be built from scratch; verify execution behavior and select one runtime.
4. The selected paper direction is energy diagnosis, not thermal wear/lifetime estimation or a platform-count exercise.
5. No planner output is experimental data. No source-review defect is yet a measured failure without reproduction.

## Closest research to inspect before strong novelty claims

The earlier review identified the following as relevant. These short characterizations guide reading and are not a complete citation audit. Stephen should recheck precise claims against the papers before writing a submission.

| Source | Why it matters |
|---|---|
| [A-LEMS](https://arxiv.org/abs/2605.22883) | Existing goal-level accounting; distinguish the new decision capability |
| [Causal Agent Replay](https://arxiv.org/abs/2606.08275) | Agent interventions/replay already exist |
| [JouleShare](https://arxiv.org/abs/2608.00026) | Request replay and inference energy attribution are close prior work |
| [Cost–Utility Alignment](https://arxiv.org/abs/2608.26195) | Broad profiling-to-adaptation framing is not itself new |
| [ML.ENERGY](https://papers.nips.cc/paper_files/paper/2025/file/9dc510e3d7b0b3b2a58ffed7a3ad6b0f-Paper-Datasets_and_Benchmarks_Track.pdf) | Energy/service frontiers and configuration evaluation |
| [AgenticBench thesis](https://digitalcommons.calpoly.edu/theses/3324/) | Verifiable agent workloads and energy profiling |
| [Minos](https://arxiv.org/abs/2604.03591) | Lower-cost prediction/profiling comparison and SIGMETRICS contribution pattern |

Do not claim to invent replay, phase attribution, Shapley allocation or energy per goal. The intended gap is a validated and economical intervention decision under the declared hardware/workflow conditions. That gap is a hypothesis to test against these and newer papers.

## Operational primary sources

- [SIGMETRICS 2027 CFP](https://www.sigmetrics.org/sigmetrics2027/pages/cfp.html): Fall abstract October 2, paper October 9, 2026, 23:59 AoE.
- [GitHub forks](https://docs.github.com/en/pull-requests/reference/forks): visibility and repository-network behavior.
- [Upstream license](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/LICENSE): MIT at the reviewed revision.
- [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/) and [batch guide](https://hprc.tamu.edu/kb/User-Guides/Grace/Batch/).
- [HPRC allocation accounting](https://hprc.tamu.edu/kb/User-Guides/AMS/): consult for current charges and balances; SUs are not GPU-hours.
- [ACCESS activation](https://allocations.access-ci.org/get-your-first-project): resource credit exchange.
- [Ollama chat API](https://docs.ollama.com/api/chat) and [configuration](https://docs.ollama.com/faq).
- [Linux powercap](https://cdn.kernel.org/doc/html/latest/power/powercap/powercap.html): energy domains/counter semantics.
- [NVIDIA NVML](https://docs.nvidia.com/deploy/nvml-api/): device telemetry API; capability depends on device/driver/access.

Do not load all papers into every student's prompt. Runtime students mainly need the code and measurement contracts; Stephen owns the broader novelty review.
