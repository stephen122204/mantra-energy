# Implementation brief

Build and validate the existing A-LEMS runtime, workload executor, independent verifiers, measurement collector and resumable execution ledger. Research planning is maintained privately.

Alex owns local-provider correctness, response/timing/token provenance, energy collection and allocated-node validation. Aldric owns immutable task assets, independent verifiers, bounded execution and observable tool controls. Nitheesh owns scheduling, interruption/recovery, complete exports and the supplied policy-interface enforcement. Stephen owns shared contracts, integration and code review.

Use the shared record contracts and named full-assignment checklists. Preserve all failed/partial attempts, distinguish unavailable energy from zero, record exact devices and clock domains, and keep conditional replay distinct from live execution. Keep all policy queries and their costs; reference outcomes must remain unavailable until a recommendation is sealed. Implement supplied interfaces with fixtures while runtime or hardware dependencies are pending.

Develop on existing computers. Real inference and telemetry checks require an individually authorized Linux compute allocation and a bounded session. The initial documented target is one Grace A100; validate actual CPU/GPU domains, permissions and resource isolation before measuring. Fixture tests do not establish hardware validity.

See [shared interfaces](04-interfaces-and-data.md), [hardware setup](05-hardware-and-access.md), [milestones](10-first-issues-and-milestones.md), and the named complete assignments. Keep task definitions and model/runtime versions explicit; changes require a new version and an impact check.
