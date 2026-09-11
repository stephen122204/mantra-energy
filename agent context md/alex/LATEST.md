# Latest published context: alex

[Immutable turn record](turns/20260911T033031Z-ed05-grace-collector-repair.md)

# Turn summary: Alex — ED-05 Grace collector repair

**Publication boundary:** This record contains implementation requirements, concrete technical rationale, code changes, tests, hardware setup evidence and handoffs only.

## Task and current understanding

Grace capability preflight established that the allocated A100 exposes sampled board power but not the tested cumulative NVIDIA energy query, and that `g002` exposes four readable Intel RAPL zones: package and DRAM on each of two sockets. The existing NVML fallback treated power as a cumulative energy counter, while fixed RAPL mappings could not retain the four zone identities. No model inference or workload-energy run was authorized for this turn.

The repair extends existing ED-05 draft PR #27 rather than AX4 PR #28. The defects directly affect ED-05 measurement correctness and were discovered while physically validating that deliverable. The branch remains `alex/ed-05-measurement-session`; exact pushed/tested head is `0c6b68a127c0fdc68d10d22c5ce50ea9cf76da17`.

## Ideas and hypotheses

Backend measurement kind must be explicit because cumulative counter deltas and sampled-power integration have incompatible units and failure behavior. For sampled power, trapezoidal integration over consecutive observations preserves rising and falling values without confusing a power decrease with counter wrap. Poll scheduling can remain 10 Hz while elapsed time uses monotonic observation timestamps; the raw record must note that device telemetry may physically refresh or average at a different rate.

A fixed x86 schema cannot describe repeated kernel names on multiple sockets. The RAPL schema should be derived from configured accessible zones, qualify repeated domains by socket, and retain kernel metadata and per-zone counter ranges. Legacy one-socket canonical names remain unchanged for compatibility.

## Decisions and rationale

- NVML now reports `cumulative_energy`, `sampled_power`, or unsupported explicitly. Power is never returned from `read_energy_uj()`.
- Sampled-power energy uses trapezoidal integration with actual monotonic elapsed nanoseconds. Raw epoch and monotonic timestamps, acquisition brackets, both power endpoints, derived energy, coverage status, reason and refresh note are retained.
- Missing endpoints produce unavailable intervals, not zero. First and final uncovered boundaries are explicit. `EnergyEngine` refuses to publish a partial sampled-power integral as total GPU energy.
- `nvidia-ml-py>=13.0.0` is declared. It was not installed during this turn.
- RAPL hardware detection now visits child zones and produces distinct keys such as `dram-0` and `dram-1`.
- Dynamic RAPL descriptors retain native key/path, kernel name, socket, parent, individual `max_energy_range_uj`, and `socket-wide` scope. Dual-socket names are `PACKAGE_SOCKET_0`, `DRAM_SOCKET_0`, `PACKAGE_SOCKET_1`, and `DRAM_SOCKET_1`; matching catalog entries and migration were added.
- Per-domain decreases are treated as wraps only when they cross that domain's recorded high/low counter edges; other decreases are resets and omitted. Failed safe reads return `None`, never fabricated zero.
- The generic `EnergySample.total_uj` no longer automatically sums potentially overlapping or independent domains.

## Changes and artifacts

Changed collector/reader paths, persistence, schema catalog/migration, hardware detection and dependency declaration. Added `tests/test_gpu_power_integration.py` and `tests/test_rapl_grace_domains.py`. Draft PR #27 was updated with exact evidence and limitations: https://github.com/stephen122204/alems-energy-diagnosis/pull/27.

## Tests and evidence

Exact tested commit: `0c6b68a127c0fdc68d10d22c5ce50ea9cf76da17`.

- `python3 scripts/check_energy_diagnosis_setup.py` — passed; setup/planning scope only.
- `python3 -m pytest -q tests/test_gpu_power_integration.py tests/test_rapl_grace_domains.py tests/test_energy_collector.py tests/test_measurement_session.py tests/test_study_contracts.py tests/test_campaign_ledger.py tests/test_data_analysis_workload.py` — 67 passed, 5 subtests passed in 0.97 seconds.
- Focused `python3 -m py_compile` for all changed Python implementation/tests — passed.
- `git diff --check` and committed-object whitespace check — passed.
- Full unqualified `python3 -m pytest -q` remains unusable because existing `tests/test_engine.py` exits during collection when `core.readers.fallback.dummy_thermal_reader` and generated `config/hw_config.json` are absent. A second broad collection attempt also found the existing environment lacks `sqlparse`, and `tests/test_rapl_direct.py` requires generated `config/hw_config.json`. These are not failures of the focused ED-05 tests.

Test coverage includes nonuniform intervals, increasing/decreasing power, missing power, incomplete start/end coverage, unsupported energy measurement, raw database persistence, partial-total rejection, four Grace-like RAPL zones, detector key qualification, independent ranges, independent wrap/reset behavior, separate package/DRAM results and no implicit domain total.

Evidence level is locally fixture-tested based on real Grace capability findings. The hardware facts motivated the implementation, but no workload energy was measured and this code has not yet been executed on Grace.

## Open questions and disagreements

Grace still must verify that the separate Python 3.11 environment imports NVML, selects the intended A100, preserves all four real paths, and produces durable samples through the installed database migration. The A100's observed power refresh/duplicate cadence, collector overhead and bounded-window coverage remain empirical checks. CPU package readings cover whole sockets, not only affinity `4-11`; comparative CPU-energy validation needs exclusive-node or another validated isolation arrangement.

Strict ED-02 still needs an Ollama-compatible real `/api/chat` response. Existing vLLM can validate the OpenAI-compatible AX3/AX4 path but not that repair.

## Next actions and handoff

1. In a small A100 allocation, create/use the separate approved Python 3.11 A-LEMS environment and run collector-only import/backend/domain/persistence checks with no inference.
2. Capture idle timestamped A100 power for a short bounded window to characterize duplicates, physical refresh behavior, missingness, coverage and overhead.
3. After collector compatibility passes, run one small existing vLLM inference with vLLM and A-LEMS in separate environments, retaining exact runtime/model/device/config and raw measurement records.
4. Validate the Ollama-specific ED-02 path separately later using an approved user-local runtime/container and compatible model artifact. Do not infer Ollama correctness from vLLM.
5. Do not run ED-09 or a larger campaign until the pilot gate is explicitly satisfied.
