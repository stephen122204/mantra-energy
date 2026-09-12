# Workloads

Aldric: immutable task contracts, verifiers and narrow tool/dependency execution. Start ED-03.

Implementation pending. See the [study index](../README.md) and root instructions.
Student 2 owns immutable task contracts, verifiers and bounded trace execution.

The first ED-03 fixture is `data-aggregate-reconcile-v1`. Its contract requires
revenue totals independently grouped by region and product, reconciliation to a
shared grand total, and source-asset evidence. `data_analysis.py` recomputes the
reference directly from the CSV; it does not consume SQL output or an agent's
self-reported status. The CSV and expected-result JSON are synthetic CC0 assets,
and their SHA-256 values are pinned in `task.json`.

The existing `core.execution.tools.real_tools.DatabaseQueryTool` uses synchronous
SQLite connections and exposes no worker/thread control. It is suitable for a
portable fixture path, but no worker-based intervention is eligible from that
tool until an engine with an observable setting is selected and measured.

`bounded_executor.py` is the AL2 single-goal boundary. It accepts a finite
dependency graph, admits only one or two ready calls, maps dependency results
with `$result:<call_id>`, and records ready/start/end events with monotonic
timestamps and configured controls. Tools may expose a `workers` argument; the
executor records configured and observed workers without treating a generic
environment variable as a control. The adapter tests use the existing
`CodeExecutorTool` for real computation and a deterministic worker probe for
control-effect evidence.

AL3 pilot assets are in `pilot_assets/`: two synthetic data goals and two
synthetic repository snapshots. They are CC0 fixtures created for this study;
`manifest.json` pins canonical hashes, family/lineage identity, expected
references, and eligible controls. `pilot_tasks.py` recomputes data totals and
repository file manifests from the assets before comparing structured answers.
These fixtures establish software correctness and control eligibility only;
they do not establish representative energy work or Grace validity.

`trace_replay.py` records model/tool inputs, dependency links, controls,
monotonic lifecycle events, outputs and hashes. Conditional replay invokes the
provided model and tool runners again and labels the resulting trace explicitly;
it is not saved-output playback. Live execution and replay divergence remain
software evidence until tested with actual inference and tools.
