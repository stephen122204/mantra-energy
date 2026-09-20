# Agent implementation and acceptance checklist

Read [CURRENT_HANDOFF.md](CURRENT_HANDOFF.md) first. This is concrete software work for the named roles; it does not define new experiments or authorize hardware runs. Inspect the current implementation before extending it. Preserve existing contracts and tests. Give the human a short explanation in ordinary language, then continue implementation in the same session.

## Alex: measurements that can be checked

Work in existing adapters/readers and `studies/energy_diagnosis/runtime/`. Inspect pending diagnostic code before depending on it. Reuse counter qualification/audit helpers when present on the selected revision; do not create a second measurement stack.

- Record actual node/device identities, available domains, units, read permissions, monotonic acquisition brackets and task start/end boundaries. Confirm both CPU packages where applicable. Missing energy is null with a reason; temperature/utilization is not energy.
- Test idle, CPU-only, GPU-only and combined work on the assigned node. Independently recompute totals from raw counters; do not double-count overlapping domains. Test denied/missing reads, resets/wraps, gaps and delayed collector shutdown with fixtures. Counter consistency is not external electrical calibration.
- Check timestamps for actual weight transfers against the actual tool start/end. Record completed bytes, including transfers outside the tool window; do not credit all transfers as overlapping. Report zero-transfer cases as unexercised.
- Supply Nitheesh the existing measurement record and validation result with exact code version. Supply a small permitted example plus a field guide stating what is recorded, derived and unavailable. Use labeled synthetic examples in Git; store real artifacts privately.
- Done: a reproducible check command, independent audit, positive and negative fixtures, and an exact-revision hardware report or a clearly named remaining hardware dependency. Stephen owns backend numerical repairs; send reproducible evidence rather than changing acceptance tolerances.

## Aldric: tasks whose answers can be checked

Work in `studies/energy_diagnosis/workloads/` and its existing tests. Reuse the executor, assets and checkers; inspect the query-task PR if needed. Do not recreate the first sales fixture as the entire assignment.

- Supply versioned task inputs, actual tool execution and independent expected-answer calculation. A file hash establishes which input was used, not whether the answer is correct.
- Test correct, wrong, incomplete, malformed and non-finite outputs; a broken/unavailable checker must not become a pass. Keep useful work, tools and answer requirements equivalent under the supplied settings.
- Provide Stephen fixed-input cases for checking model agreement and actual preparation. Preserve tokenizer/input identities and declared state. Do not select cases merely because they produce an attractive result or tune numerical tolerances.
- Record actual model/tool calls, inputs, outputs, timing and dependencies. Label live execution separately from conditional replay; replay must execute actual inference/tools before any energy claim. Report changed outputs rather than silently substituting saved answers.
- Supply Nitheesh the callable task interface, versioned checker and permitted success/failure examples. Explain the expected answer in language a human can verify.
- Done: supplied tasks execute through the shared runner, correct answers pass, deliberate wrong answers fail, dependencies/controls are observable, and remaining live/replay limitations are explicit. New task counts and expanded coverage need Stephen's supplied plan.

## Nitheesh: a complete record and unattended batch

Work in `studies/energy_diagnosis/campaign/` and existing validation/export code. Consume Alex's and Aldric's interfaces. Do not build another task executor. Reuse pending bounded-launch and copy helpers only through an explicit dependency.

- Provide one exact command plus a small configuration that runs an approved batch. Require verified paths, execution commit, output location, ordering seed, retry rules, time budget and reservation cutoff; reject placeholders before launching work.
- Record planned slots and every realized attempt with distinct linked IDs. Preserve independent execution, correctness and measurement statuses; failures and unavailable values must remain visible. Maintain actual order and distinguish setup from initialized execution and supplied cache settings.
- Demonstrate success, incorrect output, missing counters, model/tool failure, timeout and interruption/resume. Verify owned workers terminate before the next measured attempt, previous files cannot be overwritten and retries do not replace earlier evidence.
- Demonstrate lock exclusion for competing runs and durable status after disconnect using the supported launcher. Document process-group cleanup limits; do not promise recovery from every machine/process failure.
- Export raw records and derived summaries with hashes. Independently verify copied files and regenerate a small summary from retained inputs. Copy completion must not overwrite failed experiment status. Check copier requirements, including rsync version and known-host handling, before promising unattended backups.
- Done: another operator can run the documented small batch, inspect failures, resume safely and verify an off-node copy. Large runs use only Stephen's approved versioned configuration/budget. Preserve existing supplied-policy budget and reference-data separation; no new policy implementation is assigned here.

## Shared evidence and output examples

Use actual field names from the tested schema; do not invent sample JSON that looks like an implemented API. Provide a field-by-field guide covering task/configuration identity, execution result, independent answer check, energy domains/units/windows, validity reasons, transfer timing/bytes and artifact hashes. Include an intentionally invalid example. Synthetic examples in Git must be clearly labeled and must not contain real private task outputs or hidden reference outcomes.

There are separate acceptance questions: did the process finish, was the answer correct, were measurements valid, did the selected mechanism run, and were files copied intact? No single green status proves all five. Expected numbers are not targets. Compare measured totals with the independent audit, not with a previous machine's wattage or task duration.

## Ownership and progress without waiting

Alex and Aldric provide records/callables to Nitheesh. All can develop with declared fixtures before real integration. Stephen owns shared changes, model agreement, initialized-state/prompt-reuse rules and acceptance of execution settings. Report those dependencies specifically; continue other work. Do not rerun expensive hardware tests for a documentation-only update.

At startup report the current code/integration commits, inspected files and every owned milestone as reused, in progress, tested, accepted, conditional or blocked with evidence. At completion include exact commands, tests, representative artifacts, remaining limitations and next actions. Push code through scoped PRs and publish technical summaries under your own name. Do not expose private reasoning transcripts or publish research planning.
