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
| `qualify_node.py`, `node/setup_node.sh` | node report (GPUs, VRAM, counters, disk, software) and environment setup |

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

# node (cc), once:
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
