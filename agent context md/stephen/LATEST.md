# Latest published context: stephen

[Immutable turn record](turns/20260913-prefix-reuse-accounting.md)

# Within-goal exact-prefix cache and forward accounting

## Task and current understanding

Stephen continues draft PR34 runtime qualification. Reviewed fresh post-cleanup clone `/tmp/alems-prefix-review-20260912` at 163efde and fetched integration eff35f7. Root/shared/named maintained instructions are unchanged; latest team handoffs were inspected. The integration delta contains only Stephen implementation notes. Current feature implementation is 24bf1d66c0e213cd10bba2cc8c14f469f4c04135. No merge or allocation change occurred.

## Ideas and hypotheses

Retaining a supported Transformers cache across exact prompt prefixes should avoid re-forwarding their tokens. Correct reuse requires owned mutable state, exact token matching, supported positional semantics and actual work counters. A one-token uncached suffix is still prefill; sequence length alone cannot label the phase correctly.

## Decisions and rationale

The new native config option is disabled by default and opt-in as `exact_prefix`. It applies only inside the owned goal process. Crop to the exact shared prefix and forward at least one prompt token. Validate returned cache length against forwarded tokens; clear failed state and reject unsupported cache behavior. The checkpoint guard accepts the pinned fixed rotary/full-attention configuration, not scaled rotary or sliding-window semantics. Prompt serialization, model precision, routing and cross-goal process lifetime are unchanged. Configuration fingerprints require distinct run directories.

## Changes and artifacts

`moe/prefix.py` owns exact-prefix state and first-forward/decode accounting. `native_backend.py` passes the retained HF cache, records per-call reuse/new-prefill/decode/cached-token counts, and labels native dispatch from actual model-forward phase. Boot records the selected mode. README/example config document the default and acceptance limits. Linux/Windows lightweight CI includes prefix fixtures. Optional separate CPU tests exercise `NativeDevice.generate` against an actual reduced Qwen3MoE. Changes are pushed to the existing draft PR34; no private research artifacts were added.

## Tests and evidence

Local `python -m pytest -q tests/test_moe_prefix.py tests/test_moe_pipeline.py tests/test_moe_window_audit.py tests/test_moe_repair_contract.py`: 63 passed, including 18 prefix cases. Separate Torch 2.10.0 / Transformers 5.3.0 CPU environment: `python -m pytest -q tests/test_moe_prefix_transformers.py`: 2 passed. Eager and SDPA each check seven request transitions, exact generated tokens and stepwise logits against fresh generation using fixed atol=1e-6/rtol=1e-5. This random reduced model is not the pinned BF16 production model or native offload. Optional CPU tests can skip without their dependencies and do not run in lightweight CI. Setup check and diff check pass. All eight GitHub jobs at 24bf1d6 pass in run 34729636607, including Linux/Windows runtime and MoE fixtures. Native lifecycle CI remains CUDA-free. No native test of the new forward hook/cache occurred.

## Open questions and disagreements

G0 contracts and G1 component interfaces are implemented; G2 integrated fixture regression remains covered in CI. G3 physical acceptance is partial and revision-specific: the last native tool-body evidence is 847b384, before initialized-window checkpoints, the revised repair contract and this cache change. G4 expanded task execution remains conditional on corrected pilot acceptance. G5 control interfaces exist, but no supplied new policy is certified. G6 frozen configuration/task versions and complete validated exports remain outstanding. Alex supports provider/node measurement, Aldric workloads/verifiers/replay, Nitheesh ledger/campaign/export, and Stephen integration and acceptance. Their dated latest notes do not close physical milestones.

## Next actions and handoff

At the next assigned node/session, inventory devices, counters, permissions and checkpoint/build identity. First qualify current code with `request_prefix_cache: disabled` and independent initialized-window replay. Then separately exercise identical request sequences with `exact_prefix`, verifying output/fidelity, recorded forward counts, actual memory and cleanup before accepting this mode. Keep task versions and failed outcomes unchanged. CPU tests do not resolve the previously failed native-reference logit check. PR34 remains draft and unmerged; Stephen retains merge authority. Native run budgets remain limited to assigned sessions. Research interpretation stays private.
