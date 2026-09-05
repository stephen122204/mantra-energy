# Evidence and source status

Prepared 5 September 2026. This pack records the earlier code review and reported hardware access. It is not an exhaustive literature search or a fresh full repository audit.

## Evidence levels

- **Code-reviewed:** selected files at `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`. Model loader, YAML registry, adapter, agent executor, factory and root license were additionally checked for this handoff. No upstream build or cluster experiment was run.
- **Reported access:** Alex's screenshots supplied in this conversation; no screenshots or account credentials are redistributed. Awards and telemetry claims remain distinguished from current balance and sensor validation.
- **Existing local planning code:** copied generator, manifest and data contract in starter/. Their original source is the September 4 diagnostic-launch package. Placeholder entries remain unfilled.
- **Proposed:** role split, module interfaces, model, candidates, campaign size and method. These require implementation and pilot evidence.
- **Verified current documentation:** GitHub repository setup checked for this handoff; hardware/runtime links were checked during this conversation. Resource documentation does not establish a reservation.

## Important corrections to older context

1. Alex now reports usable team GPU allocations and approved Explore ACCESS. Older documents saying ACCESS was only submitted are historical.
2. Active model routing uses models.yaml through core/models_loader.py; the remaining models.json is not sufficient evidence of current runtime configuration.
3. vLLM provider/model entries already exist. Do not assume a vLLM integration must be built from scratch; verify execution behavior and select one runtime.
4. Implement the assigned energy measurement and workload contracts; changes to the research direction are coordinated privately with Stephen.
5. No planner output is experimental data. No source-review defect is yet a measured failure without reproduction.

## Publication boundary

Research reviews and contribution strategy are maintained privately outside this repository. Shared context contains the implementation contracts and operational references needed to build and validate the software.

## Operational primary sources

- [GitHub forks](https://docs.github.com/en/pull-requests/reference/forks): visibility and repository-network behavior.
- [Upstream license](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/LICENSE): MIT at the reviewed revision.
- [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/) and [batch guide](https://hprc.tamu.edu/kb/User-Guides/Grace/Batch/).
- [HPRC allocation accounting](https://hprc.tamu.edu/kb/User-Guides/AMS/): consult for current charges and balances; SUs are not GPU-hours.
- [ACCESS activation](https://allocations.access-ci.org/get-your-first-project): resource credit exchange.
- [Ollama chat API](https://docs.ollama.com/api/chat) and [configuration](https://docs.ollama.com/faq).
- [Linux powercap](https://cdn.kernel.org/doc/html/latest/power/powercap/powercap.html): energy domains/counter semantics.
- [NVIDIA NVML](https://docs.nvidia.com/deploy/nvml-api/): device telemetry API; capability depends on device/driver/access.

Use the code and measurement contracts for implementation. Keep broader research reviews outside shared context.
