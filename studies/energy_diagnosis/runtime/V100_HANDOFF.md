# V100 implementation handoff — 16 October 2026

## Result and scope

One live `staged-inspection-v1` diagnostic passed end-to-end at tested commit
`7acd9d78aa77b19a81aa181060936e7097c7efeb`, on `alex/v100-node-readiness`.
The model requested eight redundant `inspect_asset` calls in its first response;
all eight executed sequentially through the real tool executor and remain in the
evidence. Its second response passed the unchanged independent verifier. This was
one attempt, two model responses, no inserted calls, answer repair or retry.

Default-prompt success, reliability, and performance/energy comparability remain
unestablished. This is bounded platform correctness/telemetry evidence, not pilot
or campaign acceptance. Keep [PR #77](https://github.com/stephen122204/alems-energy-diagnosis/pull/77)
draft for Stephen; no merge. This documentation update does not change runtime
behavior and is not the hardware-tested revision.

## Tested configuration and acceptance

| Item | Recorded configuration/result |
| --- | --- |
| Device/runtime | GPU 0 on four-V100-SXM2-32GB node; driver 560.35.05; Python 3.10.12; Ollama 0.6.8 |
| Model | `qwen2.5:3b-instruct-q4_K_M`; manifest SHA-256 `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` |
| Task/protocol | `data-units-v2`, C00, custom JSON protocol, opt-in `staged-inspection-v1`; `pilot-verifier-v2` |
| Options | Temperature 0; token limit 512; threads 8; context 4096; keep-alive 5m; parallel 1; flash attention disabled |
| Limits | One attempt; four model-step limit; preparation 90 seconds; goal 120 seconds; five-minute session including cleanup |
| Allocation/window | CHI-261719; reservation cutoff 2026-10-16 18:55 UTC; admission 02:05:35.527826 UTC on 16 October |
| Deadline/cleanup | Session deadline 02:10:35.527826 UTC; active stop by 02:09:35.527826 UTC; owned supervisor used an earlier 230-second cap; cleanup completed 02:05:50.692541 UTC |
| Real inspection/answer | Eight requested inspections completed with real tool events; strict independent answer verification passed |
| Raw responses/artifacts | Both raw provider bodies complete and reconstructed text matched; all 11 ledger artifact hashes verified; ledger/export validation passed |
| Telemetry | Five CPU package/DRAM/GPU0 domains reconciled to cumulative-counter differences, with valid units, ordered timestamps and samples |
| Effective runner | Preparation and both request options matched; one runner launch, stable process identity, threads/context/parallel settings confirmed, 37/37 layers offloaded, no unexpected reload |
| Interference/cleanup | Fresh admission and sampled CPU/GPU checks passed; only owned work terminated; server/runner gone, port closed, all GPUs idle after cleanup |

Session through cleanup was 15.164715 seconds; goal duration was 11.344878705
seconds. These durations document deadline compliance, not a performance result.
Fresh processes and empty-chat preparation do not establish matched internal KV,
kernel warm-up, filesystem cache or thermal state. Capture/request recording and
collector work remain in their existing accounting. Hardware-domain counters are
not whole-node or isolated-process energy. Sampled checks do not prove exclusivity.

## Evidence and backup

Raw records remain outside Git. All paths below are under `/home/alex/alems-data/`:

- `v100-readiness-20261015/`: original four-GPU qualification and two failed
  inference attempts at `ad2d97b`; earlier follow-up archives retained.
- `alems-v100-followup-20261015/`: earlier implementation/test/session handoff.
- `v100-correctness-20261015T2040Z/`: two later default-prompt failures at `44f4353`,
  zero-total answers and no inspection; both preserved unchanged.
- `v100-staged-inspection-20261016T013532Z/`: reviewed diagnostic patch, initial
  fixture failures, test results, and `decoding-fix/` compatibility fix/evidence.
- `v100-staged-inspection-20261016T013532Z-checkpoint-7acd9d7/`: checkpoint identity,
  committed patch and final implementation handoff.
- `v100-staged-live-20261016T020452Z/`: successful diagnostic; `command-1.json`
  records the exact invocation, `batch.py`/`prepare.py`/`capture_request.py` the
  external orchestration, `session.json` the deadlines, `AUDIT.json` the independent
  audit, and `HANDOFF.md` the private operational handoff. `inference-1/goals/`
  retains raw responses, tool events/results, answer verification and telemetry;
  supervisor, request, residency, process and cleanup records are alongside it.

Successful diagnostic package (adjacent to the source directory):

- `v100-staged-live-20261016T020452Z-evidence.tar.gz`, SHA-256
  `92371468f606dfb23ab6ffb73c20339ea3d17b027a26080f50748ad92c021089`.
- `v100-staged-live-20261016T020452Z-manifest.json`, SHA-256
  `9164eba88a74110ba1d99982d7b07da54df03607b5b2773f7fc29ec18719af0a`.
- `v100-staged-live-20261016T020452Z-evidence.sha256` covers both files.

The user reports that this successful diagnostic package was copied off-node and
its checksums passed. Original readiness, earlier follow-up, newer failed-correctness
and staged-inspection checkpoint packages were also confirmed checksum-verified
off-node. Later session handoff/process-check files were reported copied. These
confirmations supersede historical pending-backup notes; no direct access to the
personal destination is claimed. Future evidence needs separate backup verification.

## Test provenance and remaining work

The diagnostic snapshot passed 91 focused non-GPU tests before the decoding fix.
The final fix passed 13 capture tests (43 deselected), including ISO-8859-1 JSON
through both response paths, exact bytes/hashes and single transport consumption.
Historical logs retain two initial fixture failures and their corrections. Scripted
success is separate from the real run above; the 91-test suite was not rerun after
the decoding fix. No test or hardware workload was repeated for this documentation
publication. Native Windows execution of the diagnostic patch remains unverified;
prior CI results must not be transferred to this checkpoint.

Review the documented implementation in draft PR #77. Stephen retains runtime,
starting-state and merge decisions; Alex owns measurement integrity, Aldric task
correctness, and Nitheesh ledger/export reproducibility. This updates AX3/AX4 with
one successful V100 diagnostic; broader configuration acceptance and AX5 remain
conditional on separate approval. Collector cost/fine-grained attribution, matched
starting state, default-prompt success and reliability remain open. Native MoE,
model-reference/transfer qualification, multi-GPU inference, external calibration
and whole-node isolation are not established here.

Next session: read this handoff and `V100_READINESS.md`, check revision/working tree
and relevant changes, and reuse completed tests unless conditions changed. No further
hardware attempt is authorized by this result. Any new test needs an explicit
bounded purpose/budget, valid allocation/cutoff, fresh competing-work checks and
owned cleanup. Do not change the verifier, infer pilot approval or launch a campaign.
