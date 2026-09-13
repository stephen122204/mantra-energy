# Latest published context: stephen

[Immutable turn record](turns/20260913-planning-snapshot-cost.md)

# Scalar snapshot serialization and planning-stage timing

## Task and current understanding

Stephen resumed PR34 in fresh clone `/tmp/alems-planning-review-20260913`, source 24bf1d6, fetched integration e14d7c5. Maintained root/shared/named instructions are unchanged; the newest implementation handoff describes the dependent query workload. Runtime head is now 8eee497. A second fresh clone `/tmp/alems-combined-qualification-20260913` combines it into the query branch at efa886e. Neither PR was merged into integration; no allocation or upstream repository change occurred.

## Ideas and hypotheses

The native snapshot API returns scalar IDs, byte counts and a device string. Building and recursively copying a dataclass for every expert is unnecessary for the wire format. Preserve every live metadata read, field/order and settled-transfer requirement. Separate host timing for the snapshot RPC and local selection so their costs can be inspected independently in the existing enclosing planning window.

## Decisions and rationale

Serialize scalar fields directly. Do not cache placement, omit experts, change sorting, alter history or change policy/budget selection. Add host-clock start/end brackets under planning-end `stages.snapshot_rpc` and `stages.policy_select`; demand has an empty map because neither operation runs. Snapshot timing includes native metadata, serialization, IPC and reconstruction, not just C++ execution. Whole-goal boundaries are unchanged. No timing speed threshold is imposed on portable tests.

## Changes and artifacts

PR34 commit 8eee497 changes native snapshot construction and records planning substages, with README and CI/test coverage. The dependent query branch includes it at efa886e. Its only merge conflict was the shared CI test list: both planning and query cases and the separate real DuckDB step were retained. PR35's incremental diff remains the query task addition. The branch dependency update is not a PR merge. Private analysis/benchmarks are not published here.

## Tests and evidence

66 local planning/pipeline/window-audit/repair/prefix cases pass on the runtime branch. New tests verify byte-for-byte JSON equivalence for 6,144 expert records, fresh changed residency, no metadata reads while unsettled, exact stage enclosure and unchanged selected experts. Demand does not invent stages and permits a coarse-clock zero tick. All eight GitHub jobs pass at 8eee497 in run 34734016071. The combined query branch passes 89 local tests with optional DuckDB/PyArrow installed; setup/diff checks pass. Its final explicitly dispatched CI run 34734603536 completed successfully at efa886e. Optional PyArrow tests remain local-only; fixture CI is not a hardware result. No native GPU execution of these changes occurred. Prior real-data tool fixtures remain at bcdc149 with simulated inference/counters; older native evidence remains at its recorded revision.

## Open questions and disagreements

G0 contracts/G1 component interfaces are implemented; G2 integrated fixtures remain covered. G3 physical acceptance is partial/version-specific: latest checkpoints, prefix reuse, task changes and this native snapshot path still need bounded on-node qualification. G4 has the optional query development input, not an accepted broad campaign. G5 existing control interfaces remain available without certifying a new supplied policy. G6 final frozen configurations/tasks and complete validated exports remain outstanding. Alex supports runtime/node measurements; Aldric workloads/verifiers/replay; Nitheesh ledger/campaign/export; Stephen integration and acceptance. No dated contributor note closes those hardware requirements.

## Next actions and handoff

Keep PR34 and PR35 draft. On the assigned node qualify established counter/output/cache behavior first, then inspect new planning-stage brackets and expert identities/bytes/residency under the same settings. The latest combined branch can exercise the optional query task after prerequisite checks. No local fixture timing certifies native speed or physical energy. Use a fresh output directory and record the exact execution commit; no reservation extension or expanded campaign is implied. Stephen retains merge authority, and research interpretation stays private.
