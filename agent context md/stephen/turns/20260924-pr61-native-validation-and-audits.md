## Task and current understanding

Technical review of PR61 on branch stephen/prefetch-controls. Fresh clone used; current code head 8b44d4a. Alex owns runtime/measurement integration, Aldric task correctness, Nitheesh record/export consistency, and Stephen this shared native-backend review. Research discussion and raw run outputs remain private.

## Ideas and hypotheses

Implementation risks inspected: tool-pause numbering can differ from model-call numbering; an enabled setting need not activate a backend mechanism; dispatch residency cannot certify survival of a particular prepared copy. Host token availability requires explicit timing rather than inference from aggregate dispatch counts.

## Decisions and rationale

Missing future task/pause entries fail. Native builtin execution is rejected pending activation qualification, while other arms explicitly disable that backend setting. Static preparation is single-use per goal. Timing is installed consistently for every native arm, and its CPU-delivery synchronization overhead is included and documented.

## Changes and artifacts

PR61 adds corrected future-trace-v2 generation, stronger transfer/usefulness validation, guarded single-goal audit_pilot, and first/subsequent host token-availability timing. Existing future-trace-v1 inputs must be regenerated. See studies/energy_diagnosis/moe/PREFETCH_ARMS.md for CLI and measurement limits. No native extension or model weights were changed.

## Tests and evidence

At 8b44d4a, 120 selected control/harness/protocol/prefix/acceptance tests passed locally and on LIQID05. Two actual reduced-Qwen Transformers cache checks passed in the node's backend environment. Portable setup checker passed. Earlier timing return-path and fake-streamer errors were fixed, not suppressed. GitHub Actions did not execute jobs due account billing/spending limits; this is not Windows CI qualification.

## Open questions and disagreements

All three guarded native smoke stages on 8b44d4a passed on LIQID05 across business-query and ETL-repair paths. Counter/transfer/prefix/token-timing audits also passed independently after the verified off-node copy. Matched stages had identical requests and outputs. Do not expose test-only PYTHONPATH package overlays to native runtime: pip-freeze identity correctly rejects the altered effective environment even though the installed backend was unchanged. Keep the runtime fingerprint check intact. A separate unauthenticated SSH connection triggered the process guard on one development attempt; retain invalid attempts and do not disable the guard to obtain a pass.

## Next actions and handoff

PR61 is ready for code review, not merged. A smoke pass is not full-campaign qualification. Preserve independent counter checks, required domains, strict deadlines, cleanup, and off-node backup verification. Do not start another SSH connection or separate agent workload during a guarded measurement stage.
