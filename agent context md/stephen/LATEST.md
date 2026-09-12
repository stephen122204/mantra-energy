# Latest published context: stephen

[Immutable turn record](turns/20260912T2225Z-planned-admission.md)

# Separate expert planning and admission — Stephen

## Task and current understanding

Continue the runtime integration in PR #34 (https://github.com/stephen122204/alems-energy-diagnosis/pull/34). Fresh clone at a3b8dc49e78298e857619039b7e49505121fc285; integration inspected at d7829edb63f131c02d6659e2ae55fc51d62c1347. Current runtime commit 847b384449aa484e4e0b4f55c8b1b0dfab37a2ce; test-only head 1325cb9. No merge or history rewrite.

## Ideas and hypotheses

Expert enumeration/selection should have a separately visible interval rather than delaying transfer admission after the tool notification. Planning itself must not transfer weights, and its cost remains inside the goal.

## Decisions and rationale

Use one immutable pending plan tied to goal, request, generation, pause index and policy. Reject stale or duplicate plans and intervening model requests. Discard an unused plan at goal end. The tool child continues independently of parent-side admission.

## Changes and artifacts

Added plan_pause() and explicit planning/dispatch events. GoalExecutor plans before launching tools and admits on body_start. Demand retains its no-enumeration/no-empty-admission path. Reset request identity at each new goal. Protocol is planned-tool-body-admission-v1 and is included in the manifest/fingerprint, so old output directories cannot silently resume. A test-only follow-up publishes PID readiness files atomically to eliminate an observed Windows empty-file race.

## Tests and evidence

186 runtime tests plus five subtests and 20 MoE pipeline tests passed locally. All eight CI checks pass at 1325cb9 on Windows/Linux, including native C++ lifecycle coverage on Linux. Tests cover no transfer during planning, no repeated snapshot at admission, request/goal isolation, unused-plan cleanup, planning inside goal timing and actual tool start ordering.

Two bounded native data-task executions at exact 847b384 on the assigned liqid05 A100 completed correctly, exited 0 and had six independently reconciled CPU-package/GPU-board totals. Planning/dispatch/body/transfer events were checked; GPU compute-process absence was confirmed afterward. Artifact copies are private and their archive hashes match the remote source. This is bounded qualification, not an expanded campaign or performance claim.

## Open questions and disagreements

PR #34 remains draft. Initialized-model measurement boundaries, broader output fidelity and additional workload qualification remain incomplete. Component fixture success is not final hardware/data acceptance.

## Next actions and handoff

Add explicitly sampled initialized-model boundaries while retaining outer startup/release costs and complete failure accounting. Preserve independent verification, confirmed idle/drain state, raw counter brackets, and versioned source/configuration. Keep old qualification packets unchanged. Research plans and interpretation remain private.
