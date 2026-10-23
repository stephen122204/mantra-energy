# Reproduction and artifact preparation

This guide describes the integrated source at
`6a49455c4d32c7d1812f7431718b140d668e2701`, with the approved cleanup, as inspected
on 8 October 2026. It distinguishes rebuilding saved results from conducting new
measurements. **Complete raw-to-summary-to-paper reproduction has not been
performed.** There is no completed Zenodo deposit or public raw-archive retrieval
location established by this review.

A-LEMS records energy, latency, correctness and execution behavior for LLM and
agentic tasks. Read [RUN_LOCAL.md](../RUN_LOCAL.md) for the integrated local
runtime, [MoE README](../moe/README.md) for native inference and expert preparation,
and [campaign documentation](../campaign/README.md) for records, retries and
recovery. Task verification and measurement validity are separate checks.

## Consolidation note

The cleanup branch now includes source changes from PRs #62–74 except #68,
plus #77. The baseline and unmerged-status descriptions below record the
8 October audit snapshot; they do not describe the current cleanup tree.
PR #68 host-power work and PR #75 datasets remain separately archived. The
historical artifact hashes and missing-archive limitations below are unchanged.

## Evidence and source boundaries

The [artifact manifest](artifact-manifest.json) is a release-preparation inventory,
not a certification of the experiments. Its status values mean:

| Status | Meaning |
|---|---|
| `VERIFIED` | The identified artifact bytes were actually checked; this alone does not verify the scientific content. |
| `PARTIALLY VERIFIED` | Metadata/manifests were checked, but original underlying bytes were unavailable. |
| `UNAVAILABLE` | A required artifact was inaccessible in this environment. |
| `NOT TESTED` | The artifact or procedure was not independently checked. |

Availability is recorded separately: integrated files, files in an inspected
unmerged revision, and external/unavailable artifacts are distinct. Recorded
archive hashes are expectations from metadata, not verified archive hashes.
Unknown filenames, revisions, URLs and hashes remain `null`. Paths in the manifest
are repository-relative unless their scope explicitly says otherwise. A saved
plan's expected revision is not independent proof of the executed revision.

Obtain the project repository with authorized access, preserving its Git history
and the exact required objects. A future public source archive must contain the
reviewed frozen code and licenses; its DOI/retrieval URL is still to be supplied.
Do not substitute the current integration tip for a historical execution revision.
The cleanup/documentation changes are recorded in PR #76 at `37b1534`;
base commit `6a49455` alone does not include them. Record the exact reviewed
source revision when distributing a snapshot.

The following are **unmerged**, according to the inspected audit snapshot; no
branches were merged or changed for this guide:

| Evidence | Inspected revision | Purpose |
|---|---|---|
| PR #68 | `d0d1aaef2a54d0beacff4db5291e6eeec1bc21f9` | `studies/energy_diagnosis/host_power/`: retained tables, analysis and node-specific scripts |
| PR #75 | `9e564dee99fbdfa8c1f05cc17c5869e401e8ac3d` | `data/c2-precision-energy/`: seven campaigns' processed rows and verification metadata |
| Qwen C2 plan expectation | `187c227417475d2e20632b7237ea930217237538` | Historical precision/campaign implementation referenced by available plans |
| Devstral C2 plan expectation | `7dfd892f829e9e5c791449a63659c8d97fc989b9` | Historical Devstral implementation referenced by its plan |

Other work in PRs #62–74 includes decode diagnosis, preparation/resume changes,
affinity, campaign operations, cache reconciliation, precision-task execution,
task screening/qualification and admission checks. None is implicitly available
at this guide's base merely because its PR exists. Exact inspected PR revisions
are listed in the manifest. Integration and revalidation remain separate work.

## Workflow A — regenerating reported results

### 1. Obtain and verify the original evidence

Request the original raw archives and complete incremental backup chains from
the archive custodian. They are reportedly preserved privately by the team but
were **not accessible for this review**. The original Chameleon nodes have expired.
Do not treat a receipt saying that files once matched as a fresh check of those
files. Required records include raw counter samples/checkpoints, model calls,
task inputs and outputs, verifier records, traces, statuses, ledgers, saved
configs, environment/build/model manifests and failure/recovery evidence.

For the integrated snapshot format, the inspected restore interface is:

```bash
python -m studies.energy_diagnosis.diagnostics.archive_results \
  --restore-receipt "$RECEIPT" --destination "$RESTORED"
```

**Requires unavailable inputs; not executed here.** Set `RECEIPT` to the original
local receipt and `RESTORED` to a new destination. Keep every referenced bundle
and receipt in the chain. Use the original format-compatible implementation;
do not assume every historical archive is this format. For an archive with a
recorded whole-file digest, compare its bytes with that expected SHA-256 before
extraction. For a per-file manifest, verify every restored file and investigate
missing/extra entries. A compressed manifest's hash is not the hash of an archive.

For compatible integrated MoE campaign records, these interfaces are available:

```bash
python -m studies.energy_diagnosis.moe.audit_windows "$CAMPAIGN"
python -m studies.energy_diagnosis.moe.audit_transfers "$CAMPAIGN"
python - "$CAMPAIGN" <<'PY'
import json
import sys
from studies.energy_diagnosis.moe.summary import summarize
print(json.dumps(summarize(sys.argv[1]), indent=2))
PY
```

**Source-inspected; not executed on original campaigns.** `CAMPAIGN` must be a
restored compatible campaign root with its complete `exports/attempts.jsonl`
and linked goal artifacts. The summary is a Python API; there is no claimed
`moe.summary` CLI. These checks preserve failures and unavailable energy. A
successful audit may still report unavailable domains; transfer traces do not
measure physical PCIe traffic or prove useful overlap. These are not C2 precision
extraction scripts and do not generate manuscript tables automatically.

### 2. Regenerate the accessible host-power summaries and figures

PR #68 contains processed discovery CSVs and analysis scripts. The following
recipe was verified against the pinned Git object in an external temporary
directory. It does not switch branches. The Git object must already be available
in the researcher's source distribution/clone; the paths below exist **only in
that PR export**, not in this integrated checkout.

```bash
REPRO_WORK=$(mktemp -d)
mkdir -p "$REPRO_WORK/source" "$REPRO_WORK/tables" "$REPRO_WORK/figures"
git archive d0d1aaef2a54d0beacff4db5291e6eeec1bc21f9 \
  studies/energy_diagnosis/host_power | tar -x -C "$REPRO_WORK/source"
HP="$REPRO_WORK/source/studies/energy_diagnosis/host_power"
cp "$HP/data/stages_liqid05_20260924.csv" "$REPRO_WORK/tables/stages.csv"
python "$HP/scripts/summarize.py" "$REPRO_WORK/tables/stages.csv" \
  > "$REPRO_WORK/summary.txt"
python "$HP/scripts/figures_retained.py" "$REPRO_WORK"
```

The summary uses the Python standard library. Plotting needs Matplotlib;
regeneration used Python 3.14.4, Matplotlib 3.11.2, NumPy 2.5.3 and Pillow 12.3.0.
This is the audit plotting environment, not the original experiment environment.
Use an isolated plotting environment if needed (`python -m pip install
matplotlib==3.11.2 numpy==2.5.3 pillow==12.3.0`); installation itself was not repeated
for this documentation update. A complete locked plotting environment remains a
release deliverable.

Both `figures/figA_decode_by_placement.png` and
`figures/figB_energy_domains.png` regenerated successfully and matched the prior
audit's hashes, recorded in the manifest. They are diagnostic figures, **not
verified final manuscript figures**. Other plotting stacks may render different
bytes. No claim of raw-data reproduction follows from using the retained CSV.

The PR also supplies `scripts/extract_stages.py OUTDIR ARCHIVE_ROOT[:LABEL_PREFIX] ...`
for restored stage directories, `scripts/freq_by_stage.py ARCHIVE_ROOT` and
`scripts/verify_c1.py ARCHIVE_ROOT OUTPUT_JSON`. These interfaces were inspected,
but original input roots, stage selection and complete raw bytes were unavailable.
Do not guess those roots or run them over unrelated campaigns.

**Unresolved PR #68 discrepancies:** `summarize.py` uses a sample-count-dependent
t multiplier (and a fallback), while the retained energy-boundary table describes
normal-approximation intervals. Its regenerated energy interval widths differ
from the prose/table. `extract_stages.py` also retains LIQID-specific NUMA labels
and fallback labels that do not implement the documented H100 label corrections.
The energy-boundary table's full generation procedure is not established by
`summarize.py`. Preserve all originals; the analysis owner must supply a reviewed
explanation or versioned correction before matching final tables.

### 3. Reconstruct the C2 precision results when missing inputs arrive

At the pinned PR #75 revision, `data/c2-precision-energy/campaigns/index.json`
indexes seven campaigns. Their `attempts.csv` files contain 2,747 dispatched
attempts, including invalid attempts. The earlier audit checked counts, IDs and
energy-phase consistency against the accessible metadata; it did not rederive
rows from raw records. These CSVs omit the latency information needed for a full
latency analysis.

Five campaigns include `plan.json`, `node-spec.json` and `preflight.json`.
`c2-l0-liqid05` and `repo-r-liqid05` lack these original configurations in the
supplied Git data; the PR says they exist privately. Six campaigns have compressed
node manifests and comparison receipts; `c2-l0-liqid05` has neither in this export.
For `repo-r-liqid05`, one interrupted attempt lacks several critical goal-file
listings in its manifest. Preserve that missingness rather than inventing records.

The earlier audit reproduced the available plan hashes and matched the observed
batch subsets at the expected historical revisions. Some schedules were cut
short; the continuation was a selected subset, not an entire regenerated plan.
Saved preflight failures must remain visible. These metadata checks do not show
that the planned software/environment actually ran unchanged.

The PR describes an attempt-extraction function in analysis scripts, but the C2
precision extraction/aggregation/plotting scripts have not been located in the
inspected material. There is therefore **no established command** to regenerate
these CSVs or final precision tables/figures. Supply the scripts, their exact
version/environment, all inputs, selection/exclusion rules and an output-to-paper
mapping before claiming reproduction. Do not substitute the integrated MoE
summary or independently invented formulas.

## Workflow B — running new experiments

These steps describe supported interfaces, **not commands executed during this
documentation update**. New measurements reproduce a procedure; different CPUs,
GPUs, drivers, clocks, thermal state and background activity can change numerical
results. New experiments cannot replace missing historical evidence.

### 1. Prepare software, models, tasks and hardware

Use a frozen, reviewed source revision and new storage outside the checkout.
Create the portable environment with `requirements-study.txt` as shown in the
[root README](../../../README.md). Run the setup checker, runtime fixtures and
MoE checks before requesting hardware qualification. The setup checker was
rerun successfully here. The prior cleanup baseline passed 105 selected tests
plus five subtests; full runtime/CI checks were blocked by missing dependencies.
Fixture success is not evidence of model correctness or energy-counter accuracy.

For this documentation review, the setup checker and retained-CSV summary/figure
commands completed successfully. Six CLI help interfaces also executed:
`moe.prepare`, `moe.audit_windows`, `moe.audit_transfers`,
`diagnostics.qualify_counters`, `diagnostics.audit_counters` and
`diagnostics.archive_results` (all beneath `studies.energy_diagnosis`).
`local_run --help` could not import because `cloudpickle` is absent in the audit
environment; its documented arguments were checked against the source parser.
No new experiments, model downloads, installations or hardware qualification ran.
The earlier cleanup's broader CI results also included sandbox-related failures;
the same selection gave matching failure IDs before and after cleanup.

Use separate environments for the upstream `requirements.txt` stack, portable
study stack and native backend: their constraints are not interchangeable. Native
preparation uses Python 3.11, CUDA-enabled Torch 2.10.0, Transformers 5.3.0 and the
build prerequisites in [MoE README](../moe/README.md). No clean installation of
these environments was validated for this guide. Record resolved packages,
OS/kernel, driver/toolkit, compiled backend, model/tokenizer bytes and source hash.

| Input | Location and interpretation |
|---|---|
| Local pilot tasks and independent checkers | [workloads/](../workloads/), [workload guide](../workloads/README.md); see `local_run --list-tasks` |
| Native tasks/verifiers | [moe/workloads.py](../moe/workloads.py), [moe/task_pack.py](../moe/task_pack.py); preserve assets, seeds and verification rules |
| Native example configuration | [qwen3-30b.example.json](../moe/qwen3-30b.example.json); candidate settings, with paths that require replacement outside Git |
| Pinned model/backend preparation | [moe/prepare.py](../moe/prepare.py); backend `6da092fc98e7246bfa1b2f9b2a480524b8697a7e`, model revision `0d7cf23991f47feeb3a57ecb4c9cee8ea4a17bfe` |
| Upstream model/task registries | [config/](../../../config/); registration is not installation or qualification |
| C2 precision configurations and external task provenance | Historical PR revisions above; not the integrated BF16 example |

The native preparation stages are `python -m studies.energy_diagnosis.moe.prepare
source DEST`, `download DEST`, and `build DEST`. Follow the existing guide for
separate source/model destinations and backend dependencies. They fetch source,
weights or build software; they were not executed here. The native model is
`Qwen/Qwen3-30B-A3B-Instruct-2507`. Model weights and original tokenizer/build
manifests must be obtained and hashed; the repository does not bundle them.

Physical runs require an assigned Linux machine, sufficient host RAM/disk and
GPU memory for the chosen configuration, a compatible NVIDIA driver/CUDA stack,
readable Linux powercap/RAPL counters and NVML domains, and exactly the assigned
visible GPU. An A100 40 GB was the documented target, not a guarantee that every
configuration fits. Check physical GPU UUID/index mapping. Missing CPU or GPU
energy must remain unavailable, not zero. Do not reuse expired allocation IDs,
CPU-affinity lists or private absolute paths from historical guides.

### 2. Qualify and execute a bounded run

From the portable study environment, the integrated live preflight interface is:

```bash
python -m studies.energy_diagnosis.local_run --mode live --preflight \
  --allocation-id "$ALLOCATION_ID" --gpu-index 0 --output "$PREFLIGHT_OUT"
```

Set the allocation ID and a new external output directory for the actual machine.
Preflight checks availability; it does not qualify numerical fidelity. Counter
qualification additionally launches CPU/GPU work (not run here):

```bash
python -m studies.energy_diagnosis.diagnostics.qualify_counters \
  --backend-python "$BACKEND_PYTHON" --allocation "$ALLOCATION_ID" \
  --isolation-note "$ISOLATION_NOTE" --output "$COUNTER_OUT"
python -m studies.energy_diagnosis.diagnostics.audit_counters "$COUNTER_OUT"
```

`BACKEND_PYTHON` must have the CUDA dependencies; `COUNTER_OUT` must be new.
Review the raw idle/CPU/GPU/combined records and required-domain validity. This
is an internal consistency check, not external electrical calibration. The study
sampler targets 100 ms intervals, with acquisition brackets retained; do not
describe all platform measurement as a guaranteed 100 Hz stream.

For native execution, run the fixed-input/reference qualification in
[diagnostics](../diagnostics/README.md), including actual nonzero completed
preparation transfers when testing preparation. Do not loosen tolerances or
interpret a zero-transfer test as qualification. Real task verifiers are still
required after numerical checks. For local vLLM/Ollama serving, follow
[RUN_LOCAL.md](../RUN_LOCAL.md); the server runs on the measured node, and its
installation/startup and actual model asset digest must be supplied separately.

Use the bounded native launch in [OPERATIONS.md](../moe/OPERATIONS.md), supplying
the reviewed config, backend interpreter, isolation declaration, allocation,
task/policies, run limit, deadline and a new output directory. Its supervisor
requires a lock, wall-time budget and UTC cutoff with copy margin. The exact
`moe.run` invocation is documented there; it is source-supported, not validated
on a new machine here. Serialize measured jobs; do not build, download, copy
results or log in during sensitive measurement windows. A process guard is not
hardware isolation. Changes of source/configuration require a new campaign.

### 3. Retain, inspect and copy all outputs

`local_run` saves `environment.json`, `state/schedule.json`, `ledger.sqlite`,
`exports/` and per-goal records under `goals/<execution-id>/`. Native MoE additionally
saves `summary.json`, `window-audit.json` and linked window/expert/verification
artifacts. Preserve the entire result tree, supervisor status/logs and original
configuration, including failed and incomplete attempts. An export references
raw files; it is not a replacement for them.

Validate task answers independently, counter coverage, session/clock identity,
artifact hashes, source/config/model fingerprints and failure dispositions.
Preserve distinct outer-goal, initialized-model, initialization and grading
boundaries; CPU package plus GPU board energy is not whole-system wall energy.
Do not combine incompatible historical windows or infer per-expert GPU energy.

Use the existing [copy/archive utilities](../diagnostics/README.md) and
[node batch guide](../diagnostics/NODE_BATCHES.md) for quiescent, independently
verified off-node copies before releasing hardware. Keep full incremental
chains. Resume with an identical manifest; recovery requires owned-work
termination and an endpoint in the original host/boot clock, as explained in
[campaign recovery](../campaign/README.md). Do not invent an endpoint after reboot.

## Remaining gaps and proposed Zenodo organization

The following layout is **proposed**, not present data or an uploaded release:

| Proposed release component | Available evidence | Still required |
|---|---|---|
| `source/` | Integrated Git base, approved cleanup, pinned unmerged objects | Reviewed final source revision/archive; campaign-to-execution revision map; release checksum |
| `configurations/` | Integrated example and five C2 plan/spec/preflight sets in PR #75 | Two missing original campaign configs; reviewed portable path mapping without altering experiment definitions |
| `analysis/` | Integrated audit/summary APIs; PR #68 scripts | C2 extraction/analysis scripts; complete environment locks; PR #68 discrepancy resolution |
| `processed/` | PR #68 tables and PR #75 attempt CSVs | Raw-to-processed regeneration and independently reviewed comparisons |
| `raw/` | Names/digests or per-file metadata for some archives | Original raw bytes and full backup chains from the archive custodian; independent restore/hash checks |
| `verification/` | Six C2 manifest/receipt pairs; this inventory | Missing first campaign metadata, independent verification reports, release-wide SHA-256 listing |
| `figures-tables/` | Two regenerable diagnostic figures | Final manuscript tables/figures, expected values and exact script/input/output mapping |
| `environment-models/` | Backend/model pins, expected manifest hashes in plans | Original build/weights/tokenizer manifests, tool freezes, quantized model provenance, external task versions/assets and retrieval instructions |

The archive custodian/team must supply inaccessible artifacts; the analysis
owner must supply missing scripts and reconcile discrepancies. The release
maintainer must freeze the reviewed source, document dependencies and rerun the
complete chain. Historical expected hashes establish identities only when the
matching files are actually obtained. Original environment and model provenance
remain incomplete even where current example pins are explicit.

Before publication, review redistribution terms for model weights, MoE-Infinity,
third-party tasks/datasets (including BIRD/EvalPerf inputs referenced by C2), and
processed/raw outputs. Preserve the repository's [MIT license](../../../LICENSE)
and applicable third-party notices. Where redistribution is restricted, provide
permitted acquisition instructions and hashes instead of bundling assets.
Inspect proposed release contents for credentials, private paths/addresses,
personal information and private notes; do not copy operational conversations
into the deposit. No existing data or historical values were changed for this guide.

Publication readiness requires a successful independent restore, raw-to-summary
regeneration and comparison with the actual final tables/figures, with all
remaining failures and exclusions explained. Passing software tests or replotting
a processed CSV does not complete that chain.
