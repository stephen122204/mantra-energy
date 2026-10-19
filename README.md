# Paper 1 — multi-revision source archive

**Characterizing the Task-Level Energy Trade-offs of Model Quantization in Locally Hosted AI Agents**

The paper was submitted to SIGMETRICS. This release preserves source code and
available processed records; it does not certify reproduction of the submitted
results. No single experimental snapshot is asserted. The tag identifies this
**documentation/provenance index**, not a commit that produced every paper result.
GitHub's automatic source archives contain this index; download the named release
assets below for the experimental implementations.

## Source and artifacts

| Release asset | Original identity / purpose |
|---|---|
| `paper1-qwen-external-187c227.tar.gz` | Unchanged Qwen/external source at `187c227417475d2e20632b7237ea930217237538` |
| `paper1-devstral-7dfd892.tar.gz` | Unchanged Devstral source at `7dfd892f829e9e5c791449a63659c8d97fc989b9` |
| `paper1-source-revisions.bundle` | Both original commits and their complete reachable Git history |
| `paper1-processed-artifacts-9e564de.tar.gz` | Original `data/c2-precision-energy/` from `9e564dee99fbdfa8c1f05cc17c5869e401e8ac3d`: seven campaigns, 2,747 processed rows, five plan/spec/preflight sets and available verification metadata |
| `provenance.json`, `SHA256SUMS` | Campaign identities, known/unknown revisions, missing evidence and asset hashes |

Four available Qwen/external plans name `187c227`; the Devstral plan names
`7dfd892`. These are **expected revisions in plans**, not verified per-run
execution identities. The two early campaigns (`c2-l0-liqid05`,
`repo-r-liqid05`) have unknown execution revisions here. No campaign is assigned
to a submitted-paper figure or table without evidence. See [provenance.json](provenance.json).

## Recover exact source

Download assets from this release into a new directory, then:

```bash
sha256sum -c SHA256SUMS
git init paper1-source
git -C paper1-source fetch ../paper1-source-revisions.bundle 'refs/heads/*:refs/heads/*'
git -C paper1-source switch --detach 187c227417475d2e20632b7237ea930217237538
# For the Devstral implementation, choose 7dfd892f829e9e5c791449a63659c8d97fc989b9 instead.
tar -xzf paper1-processed-artifacts-9e564de.tar.gz
```

Both source tarballs contain their original repository-root paths. Extract each
into a separate empty directory if using them instead of the bundle.
`core/` contains shared execution/measurement code; `studies/energy_diagnosis/`
contains runtime, campaign/diagnostic tools, tasks/verifiers and MoE/stock engines;
`tests/` contains fixtures. Original licenses and instructions are retained.

## Environment and bounded commands

Historical C2 records describe Linux Chameleon A100 40/80GB nodes, host CPU
packages measured through RAPL/powercap and GPU-board counters through NVML,
with 0.1-second sampling. These domains are not whole-machine wall energy.
Models include Qwen3-30B-A3B-Instruct-2507 and Devstral Small 2 with GGUF
Q4_K_M/Q8_0; the Qwen R plan also includes BF16. L0 records describe 16,384-token
context/600-second goals; R uses 65,536-token context/1,800-second goals. Preserve
the specific plan's limits, seeded repetitions, task assets and failure records.

From the selected recovered source, create an isolated portable environment:

```bash
cd paper1-source
python3 -m venv .venv-study
source .venv-study/bin/activate
python -m pip install -r requirements-study.txt
python -m studies.energy_diagnosis.moe.run --help
python -m studies.energy_diagnosis.diagnostics.campaign_plan --help
```

Optional task dependencies are in `requirements-task-screen.txt` (including
NetworkX 3.4.2) and `studies/energy_diagnosis/moe/requirements-query.txt`
(DuckDB 1.5.0/PyArrow 23.0.1). These are source constraints, not a recovered
lock of every historical environment. The native backend guide specifies a
separate Python3.11/CUDA environment and pinned backend; its constraints
(Torch2.10.0, Transformers5.3.0, Accelerate1.13.0, sglang-kernel0.4.6.post1,
Pydantic1.10.26) do not establish the exact original llama.cpp/server build.
Use the original per-campaign engine/configuration/build identities when obtained.
Models, external BIRD/EvalPerf/EvalPlus inputs and original engine binaries are
not bundled. Their acquisition/licensing and frozen identities must be resolved.

To inspect schedule generation without launching measurements, from the selected
source checkout (with its portable dependencies):

```bash
python -m studies.energy_diagnosis.diagnostics.campaign_plan   --plan ../data/c2-precision-energy/campaigns/qwen-r-3arm-gigaio08/plan.json   --output ../qwen-node-spec.preview.json
```

Expected output: a generated batch specification and JSON counts/hash summary.
Do not execute historical schedules unchanged: node paths, allocations, cutoffs,
engine configs, prepared tasks and weight manifests are historical or missing.
For an actually provisioned, approved environment, the original operational
interfaces are `campaign_check preflight --plan PLAN.json`, then
`campaign_plan --plan PLAN.json --output NODE_SPEC.json`, and
`node_batches --spec NODE_SPEC.json --output NODE_OUTPUT`, all under
`studies.energy_diagnosis.diagnostics`. The source's `CAMPAIGN_OPERATIONS.md`
describes locks, maintenance windows, retained failures, cleanup and backups.
A new run needs an assigned allocation, strict preflight and bounded budget.
These launch interfaces were not exercised on hardware for this release.

## Reproduction limits and expected records

- **Verified preservation:** original Git objects, source bytes and archive
  hashes can be recovered and checked. Release validation is in [VALIDATION.md](VALIDATION.md).
- **Requires unavailable resources:** new measurements need qualified Linux
  hardware/counters, model weights, engine/tool environments, frozen task packs
  and original configs; generated specs alone do not make a campaign runnable.
- **Cannot currently independently verify submitted results:** original C2 raw
  archives, exact extraction/aggregation/plotting scripts and paper-output mappings
  are incomplete. The processed CSVs omit latency inputs needed for full analysis.
  The legacy `campaign_analysis` uses fixed-work preparation comparisons and is
  not a substitute C2 precision-analysis command. No complete raw-to-paper recipe
  or expected manuscript figure/table values can be supplied honestly.

Runs normally retain job status, campaign ledgers/exports, model/tool traces,
verifier records, raw samples and per-domain initialized/task/grading windows;
failed or partial attempts remain records. Missing energy stays unavailable,
not zero. Available processed rows and receipts do not replace original raw bytes.
An [older 53-run pilot release](https://github.com/stephen122204/alems-energy-diagnosis/releases/tag/saved-run-review-20260925)
provides separate core records, without establishing their use in submitted figures.

This release remains in the private repository. The official SIGMETRICS2027
[call for papers](https://www.sigmetrics.org/sigmetrics2027/call_for_papers.html)
requires good-faith submission anonymity; this release makes no public visibility
change or public promotion. Repository MIT licensing and all original third-party
notices apply; model/dataset/backend terms remain separate.
