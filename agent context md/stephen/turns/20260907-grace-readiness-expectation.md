## Task and current understanding

Stephen wants the remaining Aldric implementation completed and tested in preparation for Grace, with a friendly scope clarification. Checked PR #18: still open at 5762c14, not merged. Integration study runtime/campaign directories still contain placeholders; first workload/verifier is present. No readiness claim is justified from this state.

## Ideas and hypotheses

Clarify that ready assigned software work continues after the first PR. Make completion about executable tests and integration artifacts, not an optimistic agent-assisted time estimate.

## Decisions and rationale

Aldric pre-pilot software scope includes real single-goal controls, four pilot tasks/verifiers and trace/replay implementation with local evidence, followed by shared integration fixes. An early narrow Grace capability smoke check can precede full implementation; a full pilot or replay campaign cannot skip the relevant readiness gates. Larger task expansion remains conditional on the pilot decision. Stephen owns common contracts and combined acceptance; Alex and Nitheesh retain their respective components.

## Changes and artifacts

No code/document changes or merges in this turn. Prepared a proposed Discord message in chat; no message sent. Existing complete assignment and merge gates are in PR #18. Updated maintained guides are not yet on integration.

## Tests and evidence

Read current PR state, integration tree and Aldric full checklist from the proposed branch. No code changed or tests rerun. Local fixture tests and published plans are not proof of Grace readiness.

## Open questions and disagreements

Do not promise less time than originally estimated without implementation evidence. No student acknowledgment of the revised full assignment or integrated execution result is available in this check. PR #18 needs review/merge and existing agents need to fetch/read it.

## Next actions and handoff

Aldric should read the updated full role, report all milestone statuses and complete the next ready items in separate PRs, escalating exact interface/runtime dependencies while continuing independent work. Before the main experiment Stephen verifies fresh-checkout integrated success, wrong-answer, timeout/failure, missing-telemetry and resume cases; actual control behavior; linked durable outputs; and replay fidelity before replay-based measurements. Validate real model/sensors/isolation in bounded Grace checks. Do not label the project ready merely because the checklist exists.
