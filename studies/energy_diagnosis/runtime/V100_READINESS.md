# V100 node readiness and bounded validation

This procedure prepares the existing platform for a later approved pilot. It does
not select the pilot model, qualify the native MoE backend, or authorize a campaign.
Use the [integrated runtime guide](../RUN_LOCAL.md) and the
[current handoff](../../../agent%20context%20md/CURRENT_HANDOFF.md).

## Revision and isolated installation

The 15 October 2026 inspection started at `ccfac59b9f177782b3d4b43b77947a2ba517bdb1`
on `alex/v100-hardware-validation`. It was 73 commits ahead of integration
`6a49455c4d32c7d1812f7431718b140d668e2701`, with no integration-only commits.
Those changes belong to other open work. The readiness branch
`alex/v100-node-readiness` starts directly from integration in a separate worktree;
the original branch remains intact. Do not merge the old validation branch to
publish this work.

Local paths for the prepared installation:

- Checkout: `/home/alex/repositories/alems-v100-readiness`
- External environment/evidence root: `/home/alex/alems-data/v100-readiness-20261015`
- Portable environment: `venv`; GPU load environment: `backend-env`
- Model cache: `models`; Ollama executable: `ollama/bin/ollama`
- Dependency freezes, device inventory and raw discovery: `evidence/`
- Installation, original failing tests and repaired test logs: `logs/`

A new operator can reproduce the environments with Python 3.10:

```sh
python3 -m venv "$V100_WORK/venv"
"$V100_WORK/venv/bin/python" -m pip install -r requirements-study.txt
python3 -m venv "$V100_WORK/backend-env"
"$V100_WORK/backend-env/bin/python" -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
"$V100_WORK/backend-env/bin/python" -m pip install numpy==1.26.4
```

Set `V100_WORK` to an external directory with sufficient free space before using
these commands. Retained `venv-freeze.txt` and `backend-env-freeze.txt` identify the
actual resolved packages. The installed Torch wheel reports CUDA 12.1 and `sm_70`.
The synthetic load uses FP16 on V100, with an exact all-ones matrix-product check;
Ampere and later retain the prior BF16 default. Explicit BF16 on pre-Ampere is
rejected. This does not change model arithmetic or a frozen experiment setting.

The A100 bootstrap hardcodes `TORCH_CUDA_ARCH_LIST=8.0` and a different native
backend installation; do not execute it as a V100 bootstrap. No FlashAttention
package is required for this validation. No driver replacement or reboot is used.

The readiness-only inference runtime is Ollama **0.6.8**, unpacked from its
[official Linux release](https://github.com/ollama/ollama/releases/tag/v0.6.8)
without installing a service. Its downloaded archive SHA-256 is retained locally.
The smoke model is `qwen2.5:3b-instruct-q4_K_M`, about 1.93 GB. Every registry blob
was checked against its manifest digest; the exact manifest and its SHA-256 are
retained. This small GGUF model is a software/hardware smoke input, not an approved
research model. The intended preparation step precedes the goal, but server reloads must be checked
in the retained logs; the first smoke attempt reloaded its runner (see below).

## Devices and measurement scope

Read-only discovery confirms four Tesla V100-SXM2-32GB devices, compute capability
7.0, driver 560.35.05, and two Intel Xeon Gold 6230 sockets on Ubuntu 22.04.5.
Python is 3.10.12. About 140 GiB was available before installation.

The existing `NodeCounterReader` exposes both CPU package domains, two DRAM
domains and one explicitly selected GPU per session. All four GPUs were probed
separately. Saved identities use UUIDs, not assumed CUDA enumeration order.
Qualification workers receive the selected NVML UUID as `CUDA_VISIBLE_DEVICES`.

- GPU energy is the cumulative NVML counter, natively **millijoules**, converted
  to **microjoules** by the existing bridge. All four counters advanced during
  discovery. GPU power is independently reported in **milliwatts**.
- CPU package/DRAM counters are Linux powercap RAPL values in **microjoules**, with
  kernel-provided wrap ranges. These are on-device estimates, not wall-meter
  calibration. Do not add overlapping domains or label their sum whole-node energy.
- The counter bridge does not substitute integrated power if a cumulative GPU
  counter is unsupported. Such energy remains unavailable. The separate
  `GPUCollector` power-integration implementation has fixture tests; it is not the
  measurement method observed on this node.
- Read brackets and elapsed times are monotonic nanoseconds; wall-clock anchors
  support correlation. Polling frequency is not a claimed hardware refresh rate.
- Invalid numeric readings cannot pass CLI preflight as readable. Missing and
  denied domains stay explicit; a real zero remains readable.

The four discovered `energy_uj` files initially had root ownership and mode 0400.
Only these package/DRAM files were changed to group `alex` with group-read access.
The original owner/group/mode are retained in `rapl-permissions-before.json`.
Restore each saved group/mode with `sudo chgrp`/`sudo chmod` if needed. These sysfs
permissions may disappear after reboot; inspect them at every session. Do not
make sysfs recursively writable or run the inference server as root.

## Next-session startup

1. Obtain the actual allocation/session ID, UTC cutoff and bounded test budget.
   Confirm coordination with other users; logged-in sessions are not proof of
   competing work or proof of exclusivity.
2. Inspect `git status`, exact revision and origin integration before using this
   checkout. Keep unrelated branches and generated outputs separate.
3. Run `nvidia-smi` and inspect all GPU compute processes and host CPU activity.
   Stop if another measurement or workload conflicts. Recheck before each stage.
4. Verify CPU counter permissions, device UUIDs and free disk. Preserve prior
   attempts; each new check uses a new output directory.
5. Run the setup and portable runtime checks:

```sh
"$V100_WORK/venv/bin/python" scripts/check_energy_diagnosis_setup.py
"$V100_WORK/venv/bin/python" scripts/check_study_runtime.py
"$V100_WORK/venv/bin/python" -m pytest -q tests/test_counter_qualification.py tests/test_session_diagnostics.py tests/test_operating_state.py
```

After budget approval, run the existing preflight for each physical GPU index
0 through 3. Supply the real allocation ID and a factual isolation description:

```sh
"$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.local_run   --mode live --preflight --allocation-id "$V100_ALLOCATION"   --gpu-index 0 --isolation "$V100_ISOLATION" --output "$V100_ATTEMPT/preflight-gpu0"
```

Use the existing bounded launcher around each qualification command, with an
absolute UTC cutoff, cleanup margin and shared lock. The default helper runs two
repetitions of idle, CPU, GPU and combined work, eight seconds per stage, and up
to eight CPU hash workers. Only one GPU worker runs at a time. Repeat sequentially
for each physical GPU, with a different output directory:

```sh
"$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.diagnostics.run_bounded   --output "$V100_ATTEMPT/supervisor-gpu0" --cwd "$PWD"   --seconds 180 --cutoff-utc "$V100_CUTOFF" --lock "$V100_WORK/measurement.lock" --   "$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.diagnostics.qualify_counters   --backend-python "$V100_WORK/backend-env/bin/python" --gpu-index 0   --gpu-dtype auto --seconds 8 --allocation "$V100_ALLOCATION"   --isolation-note "$V100_ISOLATION" --output "$V100_ATTEMPT/counters-gpu0"
"$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.diagnostics.audit_counters   "$V100_ATTEMPT/counters-gpu0"
```

The independent audit recomputes totals from retained endpoints and checks units,
order and derived values. It deliberately refuses counter decreases; inspect a
wrap/reset rather than declaring it a passing short non-wrapping check. Do not
sum CPU measurements across separate GPU sessions or assign package energy solely
to one process. Failed initializations retain an error record and configuration.

For the integrated smoke task, start the user-owned Ollama process on loopback,
restricted to GPU 0's observed UUID, with one request at a time and flash attention
disabled. Set `OLLAMA_MODELS` to the external cache, `OLLAMA_HOST=127.0.0.1:11534`,
`OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=false`, and
`CUDA_VISIBLE_DEVICES` to that UUID. Retain the server log and PID. Use an owned
supervisor to stop the server and its workers within the same session budget.

```sh
"$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.local_run   --mode live --provider ollama --base-url http://127.0.0.1:11534   --model qwen2.5:3b-instruct-q4_K_M --model-sha256 "$V100_MODEL_MANIFEST_SHA256"   --allocation-id "$V100_ALLOCATION" --isolation "$V100_ISOLATION" --gpu-index 0   --task data-units-v2 --settings C00 --max-runs 1 --max-steps 4 --deadline 120   --max-tokens 512 --ollama-num-thread 8 --ollama-num-ctx 4096 --ollama-keep-alive 5m   --output "$V100_ATTEMPT/inference-1"
```

Repeat once in a new directory only after checking the first attempt and cleanup.
Inspect independent verification, model token provenance, worker/device placement,
raw energy samples, domain windows, ledger integrity and every artifact hash. A
zero CLI exit alone is not a correct answer. Keep failed attempts and stop affected
work if cleanup or record validity fails. Confirm no owned GPU processes remain.

## Validation status

The exact hardware-tested code is `ad2d97b639faafe093be45941df8d131326e940c`.
The readiness-only session used allocation `CHI-261719`, a 1,200-second allowance,
and cutoff `2026-10-16T18:55:00Z`. It ran from 04:24:30 to 04:31:33 UTC on
15 October (about 423 seconds). The outer supervisor completed with verified
process cleanup. No pilot or full campaign was launched.

| Check | Result and retained evidence |
| --- | --- |
| Setup | Passed; `logs/setup-final.log` |
| Portable runtime | 216 passed plus 5 subtests; `logs/runtime-final.log` |
| Focused diagnostics | 23 passed; `logs/diagnostics-fixed.log` |
| Final edited-path checks | 43 passed; `logs/focused-final.log` |
| Dependency consistency | Both isolated environments passed `pip check` |
| Device/counter validation | Four GPUs, two repetitions each of idle/CPU/GPU/combined; 32 windows reconciled independently with raw counter differences |
| GPU arithmetic | All 16 GPU/combined load workers reported FP16 and the exact expected matrix result |
| Device placement | 832 retained observations; at most one occupied GPU at a time and no unrelated GPU process observed |
| Live inference | Two completed real attempts, both independently **incorrect**; no inspection tool calls, null totals and misplaced answer identity/evidence |
| Ledger/artifacts | Both attempts retained as terminal verification failures; both export validations pass, 16 artifact hashes checked independently |
| Cleanup | All four GPUs had no compute processes at completion; no server left running |

The original portable suite reported 10 Python 3.10 mock-resolution failures,
198 passes and 5 passing subtests. The failure log is retained. Object-targeted
patches in the test module resolve the problem without changing provider behavior.
At the implementation commit, CI passed the Linux/Windows integrated runtime and
adapter jobs. The separate Windows MoE controls job failed its profile hash
round-trip assertion (`test_all_arms_run_through_campaign_and_profiles_build`);
that profile writer/test is unchanged here. Source inspection identifies text
newline translation versus raw-byte hashing as a likely cause. Full CI is not
claimed green, and the PR remains draft.

Hardware records are under `hardware-01/`, including four `counters-N/` directories,
per-device audit logs, separate model-loading evidence, `inference-1/` and
`inference-2/`, all-GPU observations and cleanup status. The independent post-run
check is `audit_readiness.py`; its report is `evidence/readiness-audit.json`.
The exact operator commands, session identity and source revision are retained in
`hardware-01/*-command.json`, `session.json`, and `hardware-supervisor-01/status.json`.
The external `run_readiness.py` records its own source hash and invokes the existing
platform rather than another measurement implementation.

### Limitations that affect the next session

- **Correct live task completion is unvalidated.** The Qwen smoke model returned
  null totals without inspecting the asset, and the verifier rejected both
  responses. Keep these failed attempts. Stephen supplies the approved
  model/configuration; Aldric checks task/protocol suitability. Do not relax the
  verifier or treat these responses as completed useful work.
- Operating-state reads of 286 fields took approximately 1.6 seconds on this host;
  the maximum observed energy-read gap was 3.34 seconds despite a nominal 100 ms
  target. Existing [operating-state semantics](../moe/OPERATIONS.md) intentionally
  include observation overhead inside the goal. That definition is preserved.
  Counter arithmetic passed, but fine-grained attribution and collector overhead
  acceptance remain open. A proposed ordering change was evaluated locally and
  not applied because it changes the shared measurement scope; Stephen owns that
  decision. Historical records must not be silently reinterpreted.
- Initial preparation specified eight inference CPU threads; the first adapter
  call omitted that option and Ollama reloaded with its default of 40 threads.
  The reload is inside that goal's counter window. GPU offload remained on the
  selected V100, but this is not an initialized-only or matched-cache comparison.
  The next session must align preparation/request settings and record the supplied
  starting-state rules before comparing configurations.
- The second idle observations were higher after load. Keep warm-state/clock and
  thermal history explicit; these short tests establish sensor responsiveness,
  not a stable idle baseline or a performance comparison.
- No exclusive reservation enforcement, off-node archive verification, real
  timeout/failure cleanup under inference, or electrical calibration was tested.
  Another user's login remained present; GPU monitoring alone does not isolate
  shared CPU-package energy. Preserve the local evidence archive and arrange an
  approved off-node destination before the node expires.

This readiness work does not establish native MoE/model-reference agreement,
expert-transfer activation, multi-GPU inference, electrical calibration, or
campaign isolation. Those are separate acceptance requirements for the chosen
pilot configuration. Raw node records, user/session details and model files remain
outside Git.


## Follow-up implementation and proposed live check (not executed)

The JSON prompt now gives complete task-specific tool-call and final-answer shapes.
Totals (or repository fields), `task_id`, and `evidence` all belong inside `answer`.
The strict verifier still rejects missing identity, evidence and malformed totals;
the runtime does not repair answers or manufacture tool history. Both original
responses were identical. Their exact response text is retained in the small
`tests/fixtures/v100_failed_answer.txt` regression fixture; both original attempts
and their raw measurements remain untouched outside Git. Replaying this response
and scripted inspection-then-answer coverage use a simulated model and sensors.
The latter executes the actual local CSV tool, verifier and ledger, but does not
establish live model tool selection or correctness.

### Match preparation and request settings

The CLI accepts `--ollama-num-thread`, `--ollama-num-ctx` and
`--ollama-keep-alive`. Supply all three explicitly for readiness work; omitted
options preserve server defaults. The effective options are recorded in
`environment.json` and included in the preparation digest. The adapter's
`build_ollama_preparation_payload()` builds a non-streaming `/api/chat` load-only
request (`messages: []`) from the same options as a temperature-zero task request.
It does not send a request or reset cache state by itself.

After a new hardware budget is approved, use a fresh owned server process for
EACH attempt, restricted to the same physical GPU. Preload with the same model,
thread count, context size, token limit, keep-alive and parallelism as execution.
For example, with the loopback server already supervised and a new external
`V100_ATTEMPT` directory, this preparation uses the matching adapter configuration:

```sh
"$V100_WORK/venv/bin/python" - <<'PY_PREP'
import json
import os
from pathlib import Path
import requests
from core.execution.adapters.openai_compat import OpenAICompatAdapter

root = Path(os.environ["V100_ATTEMPT"])
root.mkdir(parents=True, exist_ok=False)
adapter = OpenAICompatAdapter(
    {"provider_id": "ollama_local", "base_url": "http://127.0.0.1:11534", "is_local": True},
    {"model_id": "qwen2.5:3b-instruct-q4_K_M", "max_tokens": 512,
     "ollama_num_thread": 8, "ollama_num_ctx": 4096, "ollama_keep_alive": "5m"},
)
payload = adapter.build_ollama_preparation_payload()
(root / "preparation-request.json").write_text(json.dumps(payload, indent=2) + "\n")
response = requests.post("http://127.0.0.1:11534/api/chat", json=payload, timeout=90)
(root / "preparation-response.txt").write_text(response.text)
response.raise_for_status()
resident = requests.get("http://127.0.0.1:11534/api/ps", timeout=5)
resident.raise_for_status()
(root / "prepared-residency.json").write_text(json.dumps(resident.json(), indent=2) + "\n")
PY_PREP
```

The model above remains a smoke asset. Substitute Stephen's supplied model and
manifest in BOTH preparation and execution if a different configuration is approved.
Do not run the old `run_readiness.py` unchanged: its preparation options caused the
historical reload. The next operator must use the matching preparation above and
the updated CLI options, inside an owned bounded supervisor.

Retain the server/runner PIDs, start times, complete logs and preparation payload.
Require one runner launch during preparation and no replacement launch during any
model turn. Confirm threads 8, context 4096, GPU identity/offload and model manifest;
compare `environment.json` options with the saved preparation request. Stop the
comparison if options or placement differ. Matching requested options alone does
not prove matching effective runtime state.

Fresh server AND runner processes, no task-bearing warm-up requests, and a load-only
preparation establish the same operational prompt-cache starting procedure for each
attempt. Capture every request so earlier prompt reuse cannot be silently introduced.
Internal KV contents are not directly instrumented. Filesystem/page-cache and thermal
history remain separate uncontrolled state unless Stephen supplies further rules;
do not claim all caches are cold or compare these smoke timings as controlled effects.

Proposed renewed budget: ten minutes total, two sequential GPU-0 attempts, at most
120 seconds per goal, four model steps and 512 tokens per response; allow 90 seconds
per preparation and reserve at least 60 seconds for cleanup. An outer deadline must
also respect the newly confirmed allocation cutoff. Recheck competing work before
each attempt. Inspect attempt 1 before proceeding; stop on invalid records, unexpected
reload or failed cleanup. Retain ordinary correctness failures without extra retries.
Audit model/tool spans, independent correctness, all artifact hashes and counter
windows, then terminate only owned processes. This proposal is not authorization.
A clean reviewed source revision is required by live mode; current uncommitted
follow-up edits must be approved and committed before that check.

### Collector diagnostic scope

The focused fake-clock fixture models 1.6-second operating-state acquisitions.
It demonstrates that initial/final observations extend the goal and a periodic
observation holds the counter sampling lock. It does not read host sensors, measure
actual collector CPU/energy cost, or identify the expensive sensor family. Saved
acquisition brackets provide aggregate elapsed cost only; overlapping observation
and model spans must not be added or subtracted as exclusive CPU or energy totals.
The production collector and measurement boundaries are unchanged. A per-source
cost experiment, if needed, should be a separate non-measured diagnostic with an
explicit resource budget and no competing measurement, followed by Stephen's review.

### Evidence backup gate

No verified off-node backup is recorded. Before further hardware testing, transfer
`evidence-bundle.tar.gz`, `evidence-bundle.sha256` and `bundle-manifest.json` from
`/home/alex/alems-data/v100-readiness-20261015` to an approved durable off-node location.
Use an ordinary file transfer between measurements, not Git or a PR attachment.
Verify SHA-256 on the destination against
`f226cc9bfee37f2a94e596f015b0e184574d2074fac04b4ddb73e182923e03b1` and retain a receipt
identifying the destination and verification time. Destination/access and transfer
authorization are still needed. New follow-up outputs need their own preservation;
do not overwrite the immutable original bundle.
