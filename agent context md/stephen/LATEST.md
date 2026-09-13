# Latest published context: stephen

[Immutable turn record](turns/20260913-query-workload-qualification.md)

# Optional query workload and analytical engine qualification

## Task and current understanding

Stephen continued from PR34 at 24bf1d6 in a fresh post-cleanup clone, `/tmp/alems-workload-qualification-20260913`; fetched integration ccecaa8. Root/shared/named maintained instructions are unchanged, and the latest Stephen implementation note plus unchanged contributor handoffs were inspected. This is separate dependent draft PR35 on `stephen/query-workload-qualification`, based on PR34's feature branch. Initial implementation bcdc149; test-only Windows correction 458cc4d; final dependency-preflight change 9acd52f. Nothing was merged and no allocation was changed.

## Ideas and hypotheses

A query tool should let a model inspect schemas and choose SQL, with answer checking independently derived from original source data. Runtime dependency errors should appear before expensive model startup. Short work may have zero measured elapsed time on a coarse clock; actual returned query results establish execution without inventing duration.

## Decisions and rationale

Use an explicit optional task selection rather than changing the default two-task smoke input. Pin public source hashes and record prepared database identity. Keep the reference manifest outside the model's tool interface. Use separate SQLite and DuckDB implementations, explicit engine selection and one worker. Record engine choice in the manifest/fingerprint and task lineage in the catalog. Preserve complete-goal measurement through the existing shared executor; preparation is an offline step, not an unrecorded tool call. No generated source payload/database is committed.

## Changes and artifacts

PR35 adds `query_workload.py`, offline source preparation, bounded read-only schema/query tools, exact typed answer checking, optional requirements, documentation and fixture/native runner integration via `--query-assets` and `--query-engine`. DuckDB 1.5.0 is default for the optional task and preflighted in the driver/tool interpreter; it may differ from the GPU backend interpreter. Its memory/spill/thread settings are explicit, external access/extensions are disabled, statements are restricted and an owned interruption timer is joined. SQLite uses table/function authorization and a progress deadline. Both record actual engine versions and tool diagnostics. The manifest adds a task catalog; use new run directories. Synthetic source fixtures cannot enter native mode. The fixture model chooses a known SQL path solely for integration tests; native generation remains live.

## Tests and evidence

At bcdc149, 85 local pipeline/window-audit/repair/prefix/query tests passed with optional dependencies, including 22 query cases. At 9acd52f all 23 query tests pass locally, including missing/unqualified runtime preflight. One optional raw-Parquet reference test uses PyArrow and hand-checked dates/nulls/duplicates; portable environments skip it. DuckDB tests execute actual small queries, verify output/source protection, reject mutation/external access, interrupt long queries and exercise success/failure complete goals on both engines. Full pinned-source preparation and four local integrated goals succeeded at bcdc149; model decisions and counters were simulated, queries and independent answer checks were real. Their registered artifact hashes and simulated counter-window audits were independently replayed. No actual GPU/model or physical energy result is claimed.

Initial CI run 34731592737 passed seven jobs; Windows MoE fixtures failed only an assertion that a very short elapsed time must be positive. 458cc4d changes that assertion to nonnegative, retaining actual data-result checks and production timing. Because this PR targets the prerequisite feature branch, CI is explicitly dispatched on the final ref rather than assumed from an integration-only PR trigger. All eight jobs pass at 9acd52f in final run 34732331451, including real DuckDB checks on both Windows and Linux. The optional PyArrow check remains local-only; no public source data was downloaded by CI.

## Open questions and disagreements

G0 contracts/G1 component interfaces are implemented; G2 integrated fixtures remain in CI. G3 physical acceptance stays revision-specific and incomplete, including the latest checkpoint/prefix/changed-task path. G4 now has an additional fixture-qualified optional workload path; this does not authorize or complete a broad campaign. G5 supplied control interfaces remain available without certifying a new policy. G6 frozen tasks/configuration and complete validated exports remain outstanding. Alex supports node/runtime measurement, Aldric workloads/verifiers/replay, Nitheesh ledger/campaign/export, and Stephen integration and acceptance. Old contributor notes do not close the remaining hardware requirements.

## Next actions and handoff

Keep PR35 draft, dependent on PR34, and do not self-merge. After prerequisite review/merge retarget to integration and inspect/test the combined diff. On the assigned node, qualify established checkpoint/prefix behavior first; then a bounded optional query task run can test live SQL generation, actual task correctness, dependencies, memory/runtime behavior, counter coverage and cleanup. Install the query engine in the ALEMS driver/tool environment before loading the GPU model. No new allocation or expanded campaign is implied. All scientific interpretation and private data stay outside GitHub.
