# Shared-server cohort runner

Runs N independent agent sessions against one persistent vLLM server and measures one
CPU-package + GPU-board energy interval per cohort. The agent loop, tool contracts, task packs
and trusted verifiers are the existing ALEMS components (`GoalExecutor._chat`, `task_pack`,
`BoundedToolExecutor`); this package adds the shared-server adapter, session processes, the
cohort supervisor, replay, telemetry and a bounded pilot driver.

## Pieces

| module | role |
|---|---|
| `server.py` | one vLLM 0.10.2 OpenAI server per precision config; config id = hash of every treatment field; startup KV capacity and quantization log lines |
| `client.py` | adapter for the agent loop; renders with `mistral_common` (tekken v13), sends prompt token ids to `/v1/completions`, streams output ids, records per-request timing, cached tokens and delta-encoded prompt ids |
| `session.py` | one task attempt per process with its own workspace; `--verify` grades later in the harness verification process |
| `cohort.py` | admission limit (`fixed`) or scheduled offers (`arrivals`); one energy interval incl. failures and drain; hard session/cohort caps; explicit outcomes; verification after the interval; `SHA256SUMS` |
| `replay.py`, `forcing.py` | replay of recorded sessions: same prompt ids, forced output ids (V1 logits processor), recorded inter-turn gaps; tools emulated by delay |
| `energy.py` | integrates `NodeMeasurement` samples per domain, bridging gaps ≤ 30 s, single wraps; reports gaps |
| `telemetry.py` | 1 s `/metrics` poller (running/waiting requests, KV usage, prefix-cache queries/hits, preemptions, token counters) |
| `engine_check.py` | after each server start: forced decoding exact, ≥ 2 requests batched, prefix-cache hits reported |
| `swebench_workload.py` | SWE-bench Verified runtime: sanitized image (no refs beyond the base commit), `--network none` container, `bash` tool, diff as patch, official harness grading, gold/no-op qualification |
| `taskprep.py`, `make_plan.py`, `pilot.py` | task preparation outside intervals, frozen plan, bounded driver (budget + reservation cutoff, randomized precision-block order, logged skips) |
| `campaign.py`, `node/run_campaign.sh` | main run across nodes: shard a frozen matrix by repeats (all precisions per node), bind a shard to a qualified node, resumable round loop, checksum/plan/commit coverage check |
| `qualify_node.py`, `node/setup_node.sh` | node report (GPUs, VRAM, counters, disk, software) and environment setup |

## Counter and telemetry polling

The driver records `measurement_protocol="cohort-polling-v2"` in `driver_start`,
result rows and idle summaries. Plan-level `sample_period_s` (default 0.1 seconds,
maximum 20 seconds) and `telemetry` (default true) may be overridden per step.
Both supported plan layouts (`blocks` and `passes`) are validated before task
preparation or server startup. Actual sample-gap and counter-quality checks still apply.

Under this protocol, idle steps start the metrics poller before the energy interval
and stop it after the endpoint, including on failure, matching the live/replay
boundary order. `telemetry=false` disables this poller. Idle summaries also record
`telemetry_started` (false in fixture runs). Earlier driver versions never started
the idle poller, even if the configured mode said telemetry was enabled. Therefore
new default idle readings include metrics polling; older idle readings do not.
Keep those versions distinguishable when comparing idle energy or polling overhead.
Live/replay polling behavior and the default counter sampling rate are unchanged.
This switch measures counter/operating-state and metrics polling differences; it
does not disable session logging or isolate all instrumentation overhead. Raw energy
is not automatically adjusted or subtracted.

## Treatments (Devstral-Small-2507, A100, vLLM 0.10.2)

| config | checkpoint @ revision | weights / activations / KV |
|---|---|---|
| `devstral-bf16` | `mistralai/Devstral-Small-2507` @ `bd165ab2` | BF16 / BF16 / BF16 |
| `devstral-w8a8` | `RedHatAI/Devstral-Small-2507-quantized.w8a8` @ `b152b057` (SmoothQuant + GPTQ) | INT8 / INT8 / BF16 |
| `devstral-w4a16` | `RedHatAI/Devstral-Small-2507-quantized.w4a16` @ `bb96f0d1` (GPTQ g128) | INT4 / BF16 / BF16 |

Equal total memory budget (`--gpu-memory-utilization 0.90`), prefix caching on, max model length
65 536. The equal-KV-capacity control sets `num_gpu_blocks_override` to a common block count.

## Run

```bash
# Mac: copy the tested commit (team repo is private) and start setup on the node
bash studies/paper2/cohort/node/launch.sh <node-ip>                 # writes a git bundle, scp, ssh

# node (cc), once. The repository-task sandbox needs Landlock ABI 4 (kernel >= 6.7); on the 5.15
# kernel of CC-Ubuntu22.04-CUDA run node/prepare_kernel.sh first (HWE 6.8 + gcc-12, reboots).
bash ~/paper2/setup_node.sh <commit> ~/paper2/repo.bundle
~/paper2/venv/bin/python ~/paper2/repo/studies/paper2/cohort/qualify_node.py --out ~/paper2/node-report.json \
    --cutoff-utc <lease-end>
cd ~/paper2/repo && ../venv/bin/python -m pytest -q -rs tests/test_sandbox_linux.py tests/test_repo_verification_boundary.py \
    tests/test_private_challenges.py tests/test_paper2_cohort.py           # PAPER2_TEKKEN=~/paper2/models/devstral-bf16/tekken.json

# SWE-bench calibration instances (docker; outside measurements)
../venv/bin/python -m studies.paper2.cohort.swebench_workload prepare --raw ~/paper2/swev-raw \
    --selection studies/paper2/tasks/manifests/swebench_calibration.json --out ~/paper2/swe-prep
../venv/bin/python -m studies.paper2.cohort.swebench_workload qualify --raw ~/paper2/swev-raw \
    --selection studies/paper2/tasks/manifests/swebench_calibration.json --out ~/paper2/swe-prep \
    --harness-python ~/paper2/venv-swebench/bin/python

# frozen plan + bounded pilot
../venv/bin/python -m studies.paper2.cohort.make_plan --work ~/paper2 --gpu-uuid <GPU-UUID> --allocation <lease> \
    --swebench-catalog ~/paper2/swe-prep/catalog.json --out ~/paper2/pilot-plan.json
nohup ../venv/bin/python -m studies.paper2.cohort.pilot --plan ~/paper2/pilot-plan.json --out ~/paper2/pilot-<date> \
    --budget-s 10800 --cutoff-utc <lease-end> > ~/paper2/pilot.log 2>&1 &
```

## Multi-node campaign

Before any measured run, validate the frozen plan with `pilot --dry-run` (the other required
arguments, including budget and cutoff, still apply). This prepares tasks, checks their expected
hashes and external qualification files, records every pass as skipped, and never starts a server
or measurement, even with a large budget. Set `campaign.commit` to the approved execution commit.
An insufficient budget alone is not the dry-run interface.

SWE-bench admission reads `qualification.json` beside the catalogue named in `extra_catalogs`.
When reusing a prepared catalogue with newer control results, copy both files into a new versioned
directory, validate it with `pilot.check_qualified`, and point the plan at that directory's
`catalog.json`. Retain the source files and their hashes. A qualification file in another directory
does not qualify the old catalogue automatically.

`budget.py` counts each recorded step's wall time once. Verification is already included in that
time and is reported as a subset. Measured intervals come from energy summaries; missing interval
evidence is reported as null instead of substituting wall time. Session terminal events record the
scheduler's stop reason and actual signal separately from the process exit status; an independently
crashed process remains an infrastructure failure at the cohort deadline.

Each node runs **every** precision configuration on its own GPU. Each GPU class gets its own full
set of repeats and needs its own pilot; repeats are split only among nodes of the same class, never
by precision and never across classes. A round is one driver run: pass 0 runs the round's live
cohorts on every configuration, pass 1 replays those traces (diagonal and crossed) on every
configuration; block order rotates across a node's rounds. Durations come only from pilot runs on
the same GPU class; the planner stops on a class without a pilot, an unmeasured cell, or an
evaluation cell that reuses pilot task ids. Task selection, success criteria, time limits and the
configuration-selection rule are fixed in the matrix before any evaluation round runs.

Coordinator (after the pilot, at the frozen commit):

```bash
python -m studies.paper2.cohort.campaign shard --base-plan ~/paper2/pilot-plan.json --matrix matrix.json \
    --pilot A100-SXM4-80GB=~/paper2/pilot-<date> [--pilot H100=...] --nodes nodes.json \
    --out campaign-<id>                                                   # exit 2 = a node's shard does not fit
# hand each node operator: campaign-<id>/ (whole directory) and the commit in campaign-manifest.json
```

Node operator (bare-metal GPU node, user `cc`, all accounts given sudo as for every team node):

```bash
# own machine, fresh clone of the team repo at the campaign commit
bash studies/paper2/tasks/fetch_task_metadata.sh ~/swev-raw        # public SWE-bench Verified rows (pinned revision)
bash studies/paper2/cohort/node/launch.sh <node-ip> ~/swev-raw       # bundle + setup; ~1 h (checkpoints, venvs)
scp -r campaign-<id> cc@<node-ip>:paper2/

# node: same qualification and tests as the pilot node (see Run), then the SWE-bench instances the
# matrix names (prepare + qualify into ~/paper2/swe-eval), then:
cd ~/paper2/repo
../venv/bin/python -m studies.paper2.cohort.campaign bind --campaign ~/paper2/campaign-<id> --node <node-name> \
    --node-report ~/paper2/node-report.json --allocation <lease-id> --out ~/paper2/bound
nohup bash studies/paper2/cohort/node/run_campaign.sh ~/paper2/bound <lease-end-utc> > ~/paper2/campaign.log 2>&1 &
```

`bind` requires one selected GPU of the shard's class with its own advancing NVML energy counter
(use `--gpu-uuid` to select on multi-GPU nodes). The default campaign requires readable, advancing
CPU-package counters on every socket plus GPU-board energy. GPU-only measurements are admitted
only when the frozen matrix explicitly sets `energy_metric: gpu_board`. Neither metric is
whole-machine energy, and different metrics are never pooled. `run_campaign.sh` skips finished
rounds. An interrupted round (lost node, ssh, lease) is rerun only with
`RETRY_REASON='infra: <cause>'`, into a new directory linked by `--retry-of`; the interrupted one
is kept. A server that fails to start or dies, out-of-memory, timeouts and failed tasks are
outcomes of the configuration: they are recorded in the round (`server_start_failed`,
`server_died`, session outcomes) and never rerun. Nothing else may run on the node while it works. Copy `~/paper2/campaign-results/` off the node before the lease ends; the coordinator checks
every copy with

```bash
python -m studies.paper2.cohort.campaign collect --campaign campaign-<id> --results <copied round dirs...> --out coverage.json
```

which checks each round against its recorded checksums, plan hash and commit, lists
configuration failures and retries with their reasons, and reports rounds as ok / partial /
incomplete / conflict / missing. Checksums establish integrity against the recorded manifests,
not that the experiment was correct. Collection exits with code 2 unless a nonempty campaign has
every round complete and valid, with no stray results. Configuration failures remain recorded
outcomes, but do not by themselves establish a complete set of measurements.

## Launch gates (main campaign)

| gate | enforced by |
|---|---|
| node: advancing counters for every CPU package and the GPU, Landlock ABI 4 sandbox, idle GPU | `campaign bind` (GPU-only energy only if the matrix sets `energy_metric: gpu_board`) |
| same workload across agent counts | `shard`: live cells sharing `sweep` must have identical task ids, order, seeds, mode, arrival schedule, deadline and repeat count |
| measured durations per configuration, full block-order rotation | `shard` (opt-outs: `allow_borrowed_estimates`, `allow_unbalanced_order`) |
| frozen task instances | matrix `frozen_catalog` (+ `prepared_assets`): every round checks asset hashes before running |
| cold prefix cache per cohort | driver: probe cached, `POST /reset_prefix_cache`, isolated counter deltas must prove a lookup with zero cache hits (`cache_reset` event); `cache_start: warm` opts out |
| interval closes after engine drain; no leftover task containers | live and replay require explicit zero running/waiting metrics; failed drain or container cleanup stops the driver before another measurement |
| SWE-bench controls | `qualify`: gold resolves and the no-op patch fails with valid harness reports; admission requires both control results and `controls_valid` in `qualification.json`; regenerate older qualification files |
| completeness | `collect`: expected vs completed cells; `complete`, `complete_with_configuration_outcomes`, `partial`, `invalid`, `incomplete`, `conflict`, `missing`; `analysable` only when every round is complete |
| engine | after every server start: long-context answer, exact agent request, forced decoding, batching, prefix cache |

## Records (per cohort)

`events.jsonl` (offered / admitted / terminal / verified, fsync'd), `sessions/<id>/` (spec,
requests.jsonl with token ids, model calls, tool results and events, outcome, verification),
`metrics.jsonl`, `measurement.json` (raw counter samples), `cohort-summary.json`, `SHA256SUMS`.
Outcomes: `completed` (answer submitted), `agent_failed`, `timed_out`, `cancelled`,
`infra_failed`; verdicts `pass`/`fail`/`not_run`/`unavailable`. Energy per verified success is
undefined (null) when no attempt passes. An interrupted cohort is closed with
`close_interrupted` and rerun under a new id (`retry_of`); its records are kept.

## Tests

`tests/test_paper2_cohort.py` (fixture server, no GPU): overlap of sessions in one server,
outcome paths, arrivals queueing, cohort cancellation, verification after the interval, replay
prompt reconstruction and forced outputs, gap/wrap/reset handling, manifest tampering, SWE-bench
container lifecycle and harness report parsing, pilot driver. Linux-only isolation tests
(`test_sandbox_linux.py`, Linux cases of `test_repo_verification_boundary.py`) must run on the node.

`tests/test_paper2_acceptance.py` checks missing telemetry, incomplete qualification evidence,
malformed harness reports, invalid energy, verifier failures, crossed-replay fidelity, server
drain inside replay measurement, and incomplete campaign coverage. Stream, GPU-selection and
model-configuration regressions live in the corresponding `test_paper2_*` files. Local fixture
passes do not replace node qualification, real-server engine checks, or SWE-bench Docker controls
at the final campaign commit.

Cache evidence uses the pinned 16-token block size. Before and after each probe the engine
must drain; both prefix-cache counters must be finite and non-decreasing, with the query
increase covering at least the probe's full blocks. The warm probe must reuse at least one
block and the cold probe must reuse none. Present usage counts must agree with the hit
increase. vLLM 0.10.2 may omit zero-hit usage; omission is accepted only with the counter
evidence. Probe records retain usage, before/after counters, deltas and drain evidence.
The counter check waits at most ten seconds for delayed telemetry. Probes require an
exclusive server. Replay summaries preserve incomplete request cache usage as null.
