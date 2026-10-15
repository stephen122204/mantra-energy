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
research model. Model loading remains outside the integrated goal window.

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
"$V100_WORK/venv/bin/python" -m studies.energy_diagnosis.local_run   --mode live --provider ollama --base-url http://127.0.0.1:11534   --model qwen2.5:3b-instruct-q4_K_M --model-sha256 "$V100_MODEL_MANIFEST_SHA256"   --allocation-id "$V100_ALLOCATION" --isolation "$V100_ISOLATION" --gpu-index 0   --task data-units-v2 --settings C00 --max-runs 1 --max-steps 4 --deadline 120   --output "$V100_ATTEMPT/inference-1"
```

Repeat once in a new directory only after checking the first attempt and cleanup.
Inspect independent verification, model token provenance, worker/device placement,
raw energy samples, domain windows, ledger integrity and every artifact hash. A
zero CLI exit alone is not a correct answer. Keep failed attempts and stop affected
work if cleanup or record validity fails. Confirm no owned GPU processes remain.

## Validation status

Setup/read-only discovery is complete. Controlled workloads and live inference
are pending the explicitly required allocation/session budget. The original
portable suite reported 10 Python 3.10 mock-resolution failures and 198 passes;
the failures are retained. Object-targeted patches in the test module resolve the
problem without altering provider runtime behavior. Subsequent verification and
hardware evidence are recorded in the scoped PR and Alex's immutable context.

This readiness work does not establish native MoE/model-reference agreement,
expert-transfer activation, multi-GPU inference, electrical calibration, or
campaign isolation. Those are separate acceptance requirements for the chosen
pilot configuration. Raw node records, user/session details and model files remain
outside Git.
