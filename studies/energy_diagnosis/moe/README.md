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
python -m studies.energy_diagnosis.moe.run --mode fixture --output /tmp/moe-fixture --policies demand,history,fixed,bounded --max-runs 8
```

The last command runs both substantive task families under four controls through
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

Execution protocol `tool-body-notification-v1` admits preparation only after the
parent receives the first tool's `body_start` event in a model-request tool graph.
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

## Controls and records

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

The data task performs a 20,000-row join/filter/aggregation with an independent SQL
reference. The repository task reads, repairs, compiles and runs visible checks,
then verifies pure arithmetic code against 90 separate test cases. Its allowed
repair is one pure arithmetic function, not arbitrary repository development.
Every goal starts from a hash-checked copy of its immutable input. Tools and final
checks use the existing bounded process executor.

The summary exports startup time, resume-barrier time, summed transfer host brackets, Python routing-hook time, and prepared bytes not requested. The resume barrier includes cancellation/drain/reporting overhead; summed transfer brackets can overlap and must not be added to goal duration. It includes failed-attempt costs by physical domain, marks missing energy
unknown, and leaves joules per success undefined when there are zero successes.
`paired_interval` is for independent task/session pairs, not sensor samples or
tokens. A smoke campaign cannot establish an uncertainty estimate for general
performance. CPU package plus GPU board is not whole-node or facility energy.

## Remaining on-node acceptance

Verify native build/load and BF16 outputs; actual GPU/host memory fit; native
preparation versus demand-only acknowledgments and completed transfers; correct
routing/output under each setting; queued cancellation and in-flight drain;
placement/eviction records; instrumentation overhead; CPU/GPU counter arithmetic,
coverage and process/device isolation. Start with two bounded runs, inspect their
raw artifacts, and only then expand an authorized session budget. No hardware
qualification was inferred from fixture tests.
