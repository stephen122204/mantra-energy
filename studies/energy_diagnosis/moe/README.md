# Bounded MoE runtime controls

This package connects the existing ALEMS goal executor, bounded tool processes,
node measurement, verifier and durable campaign ledger to an owned model worker.
The native worker targets one visible NVIDIA GPU and the unquantized BF16
`Qwen/Qwen3-30B-A3B-Instruct-2507` checkpoint. The example configuration is a
candidate for on-node qualification, not evidence that it fits or runs correctly.

## Offline acceptance

From a clean team checkout using the study Python environment:

```sh
python -m pip install -r requirements-study.txt
python scripts/check_study_runtime.py
python scripts/check_moe_pipeline.py
python -m studies.energy_diagnosis.moe.run --mode fixture --output /tmp/moe-fixture --policies demand,history,fixed,bounded --max-runs 20
```

The last command runs all five substantive tasks under four controls through
real subprocess RPC, actual tool computation, independent verification, simulated
counters and the existing ledger. Repeat with the same directory to check resume:
there should be zero new attempts. Fixture output is not model or energy evidence.
The C++ lifecycle check requires a C++17 compiler; the CUDA extension is not built
by that test. Linux CI runs both sets. Portable Python fixtures also run on Windows.

## Backend preparation

Use a separate **Python 3.11** environment for the native backend. Keep the study
checkout available on its Python module search path; do not install the CUDA
backend into the study's lightweight environment. `prepare` never installs or
launches anything merely by being imported. The stages below are explicit:

```sh
python -m studies.energy_diagnosis.moe.prepare source /ALLOCATED_STORAGE/moe-infinity
python -m studies.energy_diagnosis.moe.prepare download /ALLOCATED_STORAGE/qwen3-30b-a3b-instruct-2507
```

The download stage needs `huggingface_hub`. It pins the checkpoint revision and
hashes the downloaded weights, tokenizer, configuration and chat template files.
The source stage pins the backend commit, its submodules and the local native
patch. Neither stage runs model inference.

On the allocated Linux environment, install CUDA-enabled PyTorch 2.10.0 in that
backend environment (matching the CUDA toolkit and driver), plus the build tools
`setuptools`, `wheel`, `ninja`, `packaging` and `setuptools-scm`. Backend compilation
also needs its upstream native prerequisites, including CUDA development headers,
a C++ compiler, libaio and NUMA development libraries. Check the backend's build
requirements against the node image; this package does not assume those exist or
require a student to have root. Use a suitable image/module when they are absent.

The Ubuntu 24.04/CUDA 12.6 A100 build additionally needs `uuid-dev`, CUTLASS
headers and the **NVTX C++** header `nvtx3/nvtx3.hpp`. The CUDA 12.6 NVTX package
alone supplies C headers and is insufficient. For this configuration, use CUTLASS
v3.9.2 (`ad7b2f5e84fcfa124cb02b91d5bd26d238c0459e`) and NVTX v3.4.0-c-cpp
(`f71a0342a464b8580ac8573e4349086a631c3992`). Set `CUTLASS_DIR` to the CUTLASS
checkout, add the NVTX checkout's `include` directory to `CPATH`, and put the
matching CUDA toolkit's `bin` directory on `PATH`. Set `CUDA_HOME` to that toolkit,
`MOE_ENABLE_SM90=0` for an A100-only build and `MAX_JOBS=8` to bound compilation.
The local patch preserves the requested Ampere/Hopper targets for the generic
dequantization extension instead of forcing an unsupported Blackwell target.
This build fix does not select quantized weights or change model execution.

```sh
python -m studies.energy_diagnosis.moe.prepare build /ALLOCATED_STORAGE/moe-infinity
```

The build stage applies candidate dependency constraints, refuses CPU-only Torch,
verifies patched source bytes, builds the extension, and records installed Python
and native files plus the complete resolved dependency list. It does **not** mark
the native runtime qualified. The worker verifies the build fingerprint and
applied backend controls, and fails if the required patched API is absent.

Copy `qwen3-30b.example.json` to private allocation storage and replace its paths.
The expert memory ratio is explicit and logged together with the actual cache
limit. Do not silently change dtype, model revision or expert routing to make a
run fit. A changed configuration requires a new campaign directory.

## Bounded native smoke command

After the usual ALEMS node preflight confirms sensor access and allocation identity,
expose exactly one assigned GPU with `CUDA_VISIBLE_DEVICES`. From the study checkout:

```sh
python -m studies.energy_diagnosis.moe.run --mode native --config /PRIVATE/qwen.json --backend-python /BACKEND_ENV/bin/python --allocation-id ALLOCATION_ID --isolation exclusive-node --output /ALLOCATED_STORAGE/moe-smoke --task joined-orders-v1 --policies demand,fixed --byte-budget 536870912 --max-runs 2 --deadline 600
```

The 512 MiB preparation limit is a bounded smoke setting, not a tuned value. The
runner requests a new owned backend process per goal, retains disk/offload files,
and measures initialization, inference, CPU tools, preparation, cleanup and final
verification. This resets process-local caches/history; it does **not** clear OS
page caches or assert identical thermal state. Startup has its own event window.
Run paired settings in the persisted randomized order, and retain the reset,
allocation and cache evidence. A native smoke exits nonzero on incorrect output,
missing energy or invalid control behavior. Never interpret a structurally valid
ledger as proof of a successful model run.

Execution protocol `planned-body-initialized-window-v1` separates candidate selection
from transfer admission. The goal executor calls `plan_pause()` before launching
the tool graph, recording `preparation_planning_start/end` inside the measured
goal. Planning enumerates/selects experts but admits no transfers. `start_pause()`
consumes that plan only after the parent receives the first tool's `body_start`
event in the graph; it records `preparation_dispatch_start` before the native RPC.
Plans cannot cross a model request, goal or policy change, and an unused plan is
discarded at goal end. Selection and dispatch overhead are retained in goal cost.
The worker emits that event after deserialization and immediately before tool
invocation. It never waits for preparation. `body_end` brackets invocation even
when the tool raises; forced termination can leave it absent. Existing `start`
and `end` events retain process-start and completed-cleanup semantics. Each event
also records parent `observed_ns`, so delayed notification is distinguishable
from actual tool time. Short tools may finish before preparation starts; these
timestamps alone do not establish useful overlap. The protocol is recorded in
the campaign manifest and fingerprint; use a new output directory for old runs.
Demand-only pauses skip expert enumeration and the empty preparation RPC;
ownership, cancellation/drain validation and transfer logging remain active.

Candidate expert preparation is admitted by actual node byte sizes.
The model's top-k router remains unchanged. Queued work is cancelled at tool end;
already-issued work must drain before model resume. Timeout or backend failure
kills and reaps the owned worker before final cost is captured. Process cleanup failure, or forced native termination before device work was confirmed idle, makes the energy interval invalid. No remote API or fixture fallback is
used in native mode.

### Interruption, recovery and resume

`SIGTERM`/`SIGINT` to the campaign command unwinds through every cleanup block:
the owned worker and any isolated tool process are terminated, the ledger is
exported, and the command exits 130. The claimed attempt deliberately stays
`running`; reconcile it with `studies.energy_diagnosis.campaign.recover` using
the bounded launcher's terminal `status.json` (`cleanup_complete: true`), the
original session/clock identity and an endpoint from that clock, after an
independent process check. Recovery keeps the attempt as `incomplete` with
unavailable verification/measurement. The campaign command uses the ledger's
default retry limit (0), so the interrupted slot is not re-run automatically; a
retry policy is a run-definition decision, not a cleanup default. Rerunning the
identical command in the same directory then continues with the remaining
pending slots only. The summary counts the recovered attempt as an unknown cost
and `window-audit.json` reports it as `recovered: true` with
`all_domains_measured: false`; the native smoke exit codes 3/5 still apply to
such a directory because it is not a clean, fully measured batch. A different
source revision, configuration or task definition is refused by the manifest
check; task assets are reused only when identical.

## Initialized-model measurement window

The MoE command also captures real counter checkpoints after model initialization
and after task-owned work has drained and the independent verifier has run. The
model remains resident until the second checkpoint; it is released afterward.
`initialized-model-window.json` records this interval and the before/after portions
of the outer goal. All raw checkpoint readings and acquisition brackets remain in
`measurement.json`. For valid cumulative counters, the three energy portions sum
to the original outer goal total; endpoint timing brackets may overlap at shared
boundaries. Periodic and checkpoint reads are serialized. No duration is subtracted
from an energy measurement.

The extra interval is explicitly an initialized model with fresh process-local
state, not a persistent warm-cache serving session. The outer deadline still
includes initialization, and the original outer totals retain loading, planning,
verification, failed attempts and model release. Do not replace those totals
silently with the inner interval or drop failed/missing-window attempts. A failed
drain cannot seal a valid inner interval; unverified final termination invalidates
its energy as well. Default non-MoE GoalExecutor callers retain their existing
lifecycle order. Changing this protocol requires a fresh campaign directory.

Each command writes `window-audit.json`. It independently replays the exported
raw counters and checks registered artifact hashes, source/clock/session identity,
checkpoint ordering, task-span containment, drain/release evidence, and the
outer/before/initialized/after totals. Native qualification exits with code 5 if
this audit fails or any required domain/ownership evidence is missing. To audit a
saved packet without changing its records:

```sh
python -m studies.energy_diagnosis.moe.audit_windows /path/to/campaign
```

The standalone command exits 2 on absent/inconsistent evidence; an audit that
reconciles correctly recorded missing counters can pass with
`all_domains_measured: false`. It retains incorrect outcomes and explicitly marks
simulation. It reports acquisition-duration brackets without inventing exact
simultaneous boundaries. Counter replay assumes at most one wrap between adjacent
readings; it is not external sensor calibration or model-output qualification.

## Controls and records

`preparation_planning_end.stages` now contains host-clock `start_ns`/`end_ns`
brackets for `snapshot_rpc` and `policy_select`. The snapshot interval includes
live metadata acquisition, worker serialization, IPC and host reconstruction;
it is not a native-only timing. The demand control has an empty stage map because
it performs neither operation. The enclosing planning interval remains available
alongside these narrower brackets; whole-goal accounting is unchanged. Short
stages may fall within one clock tick. Snapshot fields and order are unchanged;
native scalar metadata is serialized directly, and residency is read afresh on
every settled snapshot rather than cached across requests.

`request_prefix_cache` in the native config is `disabled` by default. The opt-in
`exact_prefix` mode retains a Transformers cache only within the owned goal
process. Each request matches exact token IDs, crops to the shared cached prefix,
and forwards the remaining prompt. At least one prompt token is forwarded even
for an identical prompt. Failed generation, unsupported cache operations or a
cache-length mismatch clears state and fails the request; there is no silent
fallback. A fresh goal process cannot inherit the previous goal's cache.
This path accepts only the pinned fixed rotary/full-attention configuration;
scaled rotary or sliding-window configurations require separate qualification.

The boot record and model-call results record the mode. Per-call `prefix_cache`
fields distinguish reused prefix tokens, observed new prefill tokens, decode
forward tokens, and tokens retained for the next request. First-forward events
identify prefill even when its suffix has one token. Actual forward counts must
agree with reuse accounting. Hook cost remains included in `hook_ns`; cache
matching/cropping and retained memory remain within the goal's measured work.
The config is fingerprinted, so modes require distinct campaign directories.

Lightweight prefix-state tests run in CI. Optional CPU qualification exercises
the actual bridge and a random reduced Qwen MoE with eager/SDPA attention:

```sh
python -m pytest -q tests/test_moe_prefix_transformers.py
```

It needs Torch 2.10 and Transformers 5.3 and skips when they are absent. This is
not validation of the pinned BF16 model or native offload. Native prefix reuse,
output fidelity, cache-memory behavior and phase accounting still require the
assigned on-node qualification before this mode is accepted.

- `demand`: no speculative expert admission.
- `history`: rank experts actually used earlier in this goal; cap count and bytes.
- `fixed`: same history ranking, admitting candidates within the byte budget.
- `bounded`: same ranking with an additional transfer-throughput × expected-pause
  byte limit. Estimates must be supplied from earlier calibration. Missing
  calibration explicitly selects demand-only; no future tool outputs are read.

Artifacts retain model requests/results, tool outcomes, raw counter readings,
independent correctness, immutable fingerprints and expert events. Native admission
IDs identify **nodes**, not tensor IDs; the bridge resolves them to layer/expert
and representative tensor identities. Preparation completions carry actual padded
transfer bytes and host timing brackets. A placement event separately records
logical bytes, source/destination, demand flag and whether completion was synchronous
at return. It is not an extra transfer to add to preparation bytes. Host-backed
GPU eviction need not copy those bytes back to CPU. Asynchronous placement return
is not a transfer completion timestamp; the later synchronization supplies only an
upper bound. Clock alignment includes its host bracket uncertainty.

Demand routing hooks aggregate exact selection counts and pre-dispatch residency by request, layer, expert and prefill/decode phase. They retain first/last observation times without materializing a Python record for every token. They do not assign
GPU energy to each expert. Their overhead remains inside total measured cost and
is separately recorded in model-call `hook_ns`. Bounded buffers report overflow as
a failed observation, never as an empty trace. Preparation that is not used by the
goal end remains visible; this does not by itself prove a causal performance loss.

The default workload catalog now contains five bounded tasks. The data task performs
a 20,000-row join/filter/aggregation with an independent SQL reference. The
repository task reads, repairs, compiles and runs visible checks, then verifies pure
arithmetic code against 90 separate test cases. The new database task uses a
read-only customer/orders SQLite database and recomputes paid counts and revenue by
segment independently. The new ETL task repairs a constrained `transform_rows`
function and checks ordered outputs on hidden cases. The numerical task reads a
deterministic observation table and verifies an exact-fraction ordinary least-squares
reference rounded to six decimals.

The allowed repairs are bounded functions, not arbitrary repository development.
Workload version `moe-tools-v4` exposes the exact permitted repair languages in the
prompts and checks source shape and behavior. The changed task is `pricing-repair-v2`;
it retains lineage
`synthetic-pricing-v1`. Earlier task outcomes keep their original version and
must not be retroactively regraded. Use a new campaign directory for this version.
Every goal starts from a hash-checked copy of its immutable input. Task assets are
generated once per campaign directory; a rerun in the same directory reuses an
identical existing asset and refuses a changed one rather than rewriting it. The
prompt-visible tool contracts (`TOOL_CONTRACTS`) declare the exact argument set,
an example call and any read/write/test or schema/query ordering, and the runtime
rejects calls outside that set. The database and
numerical tools are read-only, ETL and repository writes are limited to their named
source file, and all final checks use the existing bounded process executor where
subprocess work is required.

The summary exports startup time, resume-barrier time, summed transfer host brackets, Python routing-hook time, and prepared bytes not requested. The resume barrier includes cancellation/drain/reporting overhead; summed transfer brackets can overlap and must not be added to goal duration. It includes failed-attempt costs by physical domain, marks missing energy
unknown, and leaves joules per success undefined when there are zero successes.
`paired_interval` is for independent task/session pairs, not sensor samples or
tokens. A smoke campaign cannot establish an uncertainty estimate for general
performance. CPU package plus GPU board is not whole-node or facility energy.

## Remaining on-node acceptance

An optional [queryable TLC task](QUERY_WORKLOAD.md) uses prepared public source
records and a read-only SQL tool with an independent raw-Parquet answer check.
It is selected explicitly via `--query-assets`; default task selection remains
unchanged. See its setup and qualification limits before using it on a node.

Verify native build/load and BF16 outputs; actual GPU/host memory fit; native
preparation versus demand-only acknowledgments and completed transfers; correct
routing/output under each setting; queued cancellation and in-flight drain;
placement/eviction records; instrumentation overhead; CPU/GPU counter arithmetic,
coverage and process/device isolation. Start with two bounded runs, inspect their
raw artifacts, and only then expand an authorized session budget. No hardware
qualification was inferred from fixture tests.
