# Task-pack execution handoff

Dependencies: PR41 and PR42; this combined draft includes both plus bounded SQL
ETL repair and production CLI selection. PR40 remains separate. The work does not
modify PR40's default workload definitions.

## Prepare explicit specifications

Create a JSON file with a list of objects such as:

    [{"kind":"numerical","rows":128,"seed":7},
     {"kind":"business","rows":128,"seed":7},
     {"kind":"etl","rows":128,"seed":7}]

Numerical and ETL each contribute one task; business contributes three.
Sizes/seeds share one lineage per generator. These sample sizes are for software
checks, not an approved physical run matrix. `--task-pack` and `--query-assets`
are mutually exclusive. Existing default workloads remain selectable as before.

## Full local path

    python -m studies.energy_diagnosis.moe.run --mode fixture --task-pack /absolute/spec.json --output /absolute/new-output --policies demand,fixed --max-runs 10 --deadline 30

This invokes the existing owned worker, tools, measurement fixture, ledger and
exports. `--max-runs` limits attempts per invocation; rerunning with the same
specification and configuration resumes the remaining planned attempts.
Do not reset output directories to restart. A changed pack is refused.

Each plan/catalog entry records its own actual verifier version and source hash.
The manifest also retains pack specifications and component hashes. Real inputs,
outputs and model configuration are not bundled here. Native selection uses the
same task/runtime path but still requires separately reviewed model settings,
allocation, isolation, explicit transfer budget, and a clean checkout. No native
campaign is authorized by this example.

## Evidence and limitations

Component and injected-pipeline checks cover task contracts, actual SQL/numerical
work, independent references, invalid answers, input preservation, dispatch and
resume. test_task_pack_cli.py independently invokes the CLI/worker subprocesses
and checks all five tasks across demand/fixed settings under success, wrong answer
and missing telemetry. It checks exact verifier hashes, partial-batch resume,
no duplicate completed attempts, and refusal of changed specifications.
The fixture model executes scripted decisions; native model reasoning and
transfer/energy validity are not established by these tests.

ETL verifier queries are each bounded to ten seconds and may run three times.
Budget and record this verification cost. Confirm final native goal/deadline
behavior, nonzero transfers, counter quality and backups before a physical batch.
Real-source task inclusion and final sizes/repetitions are separate supplied
configuration decisions. No research protocol is distributed in this handoff.


## Prepared numerical inputs

A specification may also identify a caller-prepared local dataset:

```json
[{"kind":"numerical","assets":"/absolute/prepared-input","asset_sha256":"REPLACE_WITH_64_HEX_CHECKSUM","task_id":"prepared-regression-v1","lineage":"source-dataset-v1"}]
```

The directory must contain exactly `observations.csv` and `source.json` as regular files. CSV columns are exactly `group,x,y,valid`; coordinates are integers within ±1,000,000,000, flags are 0 or 1, and each included group must have at least two observations with varying x. Limits are one million rows, 64 included groups, 128 MiB CSV and 64 KiB metadata. Decimal source values must be converted explicitly into documented integer units before import. The loader does not infer unit conversions or missing-value rules. Metadata must include a `source` description; retain source attribution, original checksum, units and conversion rules there.

The checksum uses the existing ALEMS directory hash (`studies.energy_diagnosis.workloads.pilot_tasks._hash`), which includes relative filenames and bytes; it is not a raw CSV checksum. The caller must independently check the source conversion. The launcher copies validated inputs into the campaign asset directory and rechecks the copy. Preserve the original prepared directory unchanged and at the same absolute path for resume. Changed source bytes or a changed snapshot are refused.

Prepared inputs use the same regression tool, verifier, manifest and record path as generated inputs. Source IDs and row variants do not automatically imply independent tasks. Do not commit input datasets, local paths or run outputs. `tests/test_prepared_numerical.py` covers normalization rejection, immutable snapshots and an actual fixture CLI execution plus resume. Fixture results are simulated.


### Token budget before native execution

`--max-tokens` defaults to 512 and applies to every model response. The prepared-input limit of 64 groups is a data-validation bound, not a promise that the answer fits that token budget. Before selecting a native configuration, use the pinned model tokenizer/chat template on the actual saved prompt and a correct answer. Include accumulated tool-result metadata and the optional inspect step. Check both answer length and `prompt_tokens + max_tokens <= max_context`; reserve headroom for differences in real model output. Keep the chosen setting identical across policy comparisons. Fixture workers do not enforce actual tokenizer-length limits and cannot qualify this condition. If a task requires a larger budget, pass it explicitly and record it in the manifest; do not silently remove answer fields or truncate groups.
