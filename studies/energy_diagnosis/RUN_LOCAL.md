# Run the integrated local build

The integration branch combines the model adapter, bounded tool executor, four versioned pilot fixtures, measurement session, independent verifier and resumable campaign ledger. Use this private team repository. The upstream repository is not the integration target.

## Install and check on your computer

From the repository root, create/activate a Python virtual environment and run:

```sh
python -m pip install -r requirements-study.txt
python scripts/check_energy_diagnosis_setup.py
python scripts/check_study_runtime.py
python -m studies.energy_diagnosis.local_run --list-tasks
python -m studies.energy_diagnosis.local_run --mode fixture --settings C00,C01,C10,C11 --max-runs 12 --output artifacts/local-smoke
```

These commands work with an activated Windows, macOS or Linux environment. The fixture run makes actual loopback HTTP requests through the ALEMS adapter, executes real local tool computations in isolated processes, independently verifies answers and writes durable records. The model responses and counters are explicitly simulated. This is not hardware energy evidence.

The 12 eligible slots comprise four settings for each data task and two one-worker settings for each repository task. C00/C01 permit one ready tool call, C10/C11 permit two; C00/C10 configure one worker, C01/C11 configure four. Recorded worker participation can be lower than the configured count for tiny tasks. Eligibility and a completed run do not establish a useful performance effect. These are small software fixtures; no representative workload or measurement-quality claim follows from them.

Rerun the same command with the same output directory to resume pending slots. Completed attempts are not repeated. Schedule/model/code/setting changes require a new output directory; never delete a failed observation to make a run appear successful.

Failure checks, using separate output directories:

```sh
python -m studies.energy_diagnosis.local_run --mode fixture --fixture-case wrong_answer --output artifacts/check-wrong
python -m studies.energy_diagnosis.local_run --mode fixture --fixture-case model_failure --output artifacts/check-model-failure
python -m studies.energy_diagnosis.local_run --mode fixture --fixture-case tool_timeout --deadline 2 --output artifacts/check-timeout
python -m studies.energy_diagnosis.local_run --mode fixture --fixture-case missing_telemetry --output artifacts/check-missing
```

A zero CLI exit after a deliberately wrong answer means the ledger was written and validated, not that the answer passed. Inspect verifier and execution status in the records.

For V100 preparation and observed readiness limits, see the
[V100 validation runbook](runtime/V100_READINESS.md).

## On the allocated Linux compute node

Run the code and inference server on the same node. Use the approved runtime/model installation and a server bound to loopback; use your own authorized account and the actual allocation identifier. Install the study dependencies into that runtime environment. Do not start jobs on a login node.

Run read-only capability checks before a measured goal:

```sh
python -m studies.energy_diagnosis.local_run --mode live --preflight --allocation-id YOUR_ALLOCATION_ID --gpu-index 0 --output artifacts/node-preflight
```

Inspect the saved preflight JSON: actual CPU package/DRAM domains, their readability, selected physical NVML GPU index/UUID, source revision, host, boot ID and CPU affinity. Match that GPU UUID with the inference server's device. NVML indices are physical device indices; do not assume CUDA_VISIBLE_DEVICES numbering is the same. A user-supplied isolation description is an assertion to verify against the allocation, not independent proof of exclusivity.

The live bridge reuses ALEMS RAPL and NVML readers. It samples counters every 100 ms and preserves acquisition brackets and per-domain wrap ranges. Only cumulative-counter domains are totaled by this command. If a GPU exposes sampled power only, this command reports unavailable energy; the separate GPUCollector power-integration path requires integration/coverage validation before claiming a complete goal total. A readable CPU/GPU counter is not a whole-machine power meter.

With an already-running OpenAI-compatible local server:

```sh
python -m studies.energy_diagnosis.local_run --mode live --provider vllm --base-url http://127.0.0.1:8000/v1 --model YOUR_SERVED_MODEL_ID --model-sha256 YOUR_PINNED_MODEL_ASSET_DIGEST --allocation-id YOUR_ALLOCATION_ID --isolation YOUR_VERIFIED_ISOLATION_DESCRIPTION --gpu-index 0 --settings C00 --max-runs 1 --output artifacts/first-live-goal
```

For Ollama use `--provider ollama --base-url http://127.0.0.1:11434` and the exact served model ID. The model digest must identify the retained model assets/revision; hashing a model name alone is insufficient. The CLI rejects non-loopback inference endpoints. Set NO_PROXY and no_proxy to include 127.0.0.1,localhost on nodes with proxy configuration. The CLI also adds those loopback exclusions in its own process.

Default budgets are one goal, up to four model steps and a 120-second goal deadline. Tool cleanup is included before the measurement endpoint. HTTP request timeouts are bounded I/O waits; a live server may continue inference after a disconnected request. Such failures checkpoint artifacts, leave the ledger claim unresolved and block subsequent goals until server-side termination is independently confirmed. Do not relabel that captured interval as complete-goal energy or blindly recover it with the current wall time.

Model loading and server preparation occur before this command and are not included in its goal counter window. Retain those setup costs separately if needed. Stop after the first goal to inspect output, raw counters, physical coverage and isolation before using an approved larger run budget.

## Inspect the artifacts

- `environment.json`: environment, dependency versions, source revision, model/preparation identity, GPU identity and dirty-checkout flag.
- `state/schedule.json`: immutable order and plan identities.
- `goals/<execution-id>/model-calls.json`: every actual prompt, adapter response, token provenance and model-call timing, including partial/error information.
- `tool-results.json` and `events.json`: actual computed results, lifecycle times, configured and observed worker counts.
- `measurement.json`: raw endpoint/periodic readings, transitions, environment and derived per-domain energy. Preparation samples remain separate from the goal window.
- `record.json` and `answer.json`: independently checked result and linked execution record.
- `ledger.sqlite` and `exports/`: durable attempts, dispositions, integrity checks and schedule validation.

Keep these generated artifacts outside Git. Failed attempts remain in outcome/cost accounting. The runner's per-observation eligibility flag is not permission to discard failed attempts when aggregating total cost. Fixture records are never hardware evidence.

## Remaining hardware acceptance

The combined executable revision must still be checked on the allocated node with the real model and sensors. Earlier component-level Grace reports do not validate this new combined command. Required evidence is a correct goal plus raw domain readings, verified device placement/isolation, failure/cleanup behavior and reproducible artifacts. This guide does not authorize an expanded campaign or declare it completed.
