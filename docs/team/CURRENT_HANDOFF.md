# Current team handoff: building and checking a complete run

Updated 20 September 2026. This is the current implementation handoff for humans and agents. It takes precedence over older first-task, Grace-only, proposed model, date and run-count instructions. Keep the existing complete milestone checklists as coverage records: inspect code and evidence, reuse completed work, and mark remaining or conditional items explicitly. Do not restart a first issue or launch an old planning matrix.

## What each person looks after

Alex checks whether the measurements describe what the machine actually did. Aldric checks whether the task was completed correctly and whether different settings did equivalent work. Nitheesh checks whether every run, including failures, can be reconstructed from saved files. Stephen owns changes to the model execution code, agreement with the standard model implementation, shared interfaces and final integration decisions.

The endpoint is one documented command for an approved batch: execute tasks, check answers, record time and energy, retain errors, stop at the time limit, and save verified copies. Completion means another person can use the command and inspect the evidence. An agent summary or an open PR alone is insufficient.

Read your plain-language guide: [Alex](alex/HUMAN_START_HERE.md), [Aldric](aldric/HUMAN_START_HERE.md), [Nitheesh](nitheesh/HUMAN_START_HERE.md). Agents also read [the implementation acceptance checklist](BATCH_ACCEPTANCE.md) and their existing full assignments.

## Connect and find the code

Accept the project invitation and provide Stephen your public SSH key (.pub). Keep the private key on your own computer. Stephen supplies an individual node account, verified address, connection command, shared environment/model paths, separate working/output directories and the reservation cutoff. Invitations alone do not establish a working login. Do not put addresses, keys or connection records in Git.

The current target is a shared Chameleon Linux node with an A100 40 GB GPU; verify the actual CPU, GPU, memory, energy-counter permissions and software before execution. AMD CPUs do not automatically rule out the Linux powercap energy interface. Model and tool execution and their measurements belong on the node, not the laptop used to connect. Download the model once into shared storage; the approved model/configuration is supplied by Stephen.

The shared integration branch is `main`. Runtime, query-task and diagnostic additions are tracked in PRs [34](https://github.com/stephen122204/alems-energy-diagnosis/pull/34), [35](https://github.com/stephen122204/alems-energy-diagnosis/pull/35), and [36](https://github.com/stephen122204/alems-energy-diagnosis/pull/36). Fetch integration and inspect their current merge state; older notes describe the earlier stacked branches. Stephen supplies the exact execution commit. A software merge does not establish model-reference agreement or qualify a hardware configuration. Do not reset a checkout to a historical hash or treat an old branch name as the current execution version.

Start from existing code and focused tests. Use separate branches/checkouts. Independent development and simulated tests can run in parallel. Physical measurements use one queue: no competing model jobs, builds, downloads or unrelated CPU work during a measured run. Git branches do not isolate hardware.

## What remains to establish on the execution revision

Prior hardware work demonstrated model/tool execution, counter collection and result export. It does not qualify every new configuration. The standard-model numerical comparison remains unresolved in the supplied handoff; Stephen owns its diagnosis. A dedicated preparation check previously moved no weights and cannot qualify that mechanism. Do not loosen tolerances or label zero transfers a passing preparation test. Private historical artifacts will be supplied separately; their absence is not permission to invent examples or mark acceptance complete.

Stephen also owns the starting-state rules: distinguish model loading from initialized execution and account for reuse of earlier prompt state. Students record the supplied settings and report unexpected behavior; do not independently change model arithmetic, routing, precision or cache semantics.

## First shared check and normal operation

Alex supplies checked measurement records; Aldric supplies a task and independent answer checker; Nitheesh joins them into one complete run and a verified export. Then execute the supplied comparison setting within the assigned budget. Use fixtures until hardware/dependency access exists; label them simulated. Larger batches require Stephen's accepted configuration and budget.

An ordinary failed attempt may be recorded and followed by the next approved run if cleanup and record validity pass. A broken checker, unexplained counter problem, mismatched files/records, changed model behavior, or risk of overwriting data blocks affected measurements. Preserve evidence, report the problem and continue independent work. A slow setting is an observation, not a reason to change it. Retries receive new linked attempt IDs; preserve approved ordering and retry limits.

Humans check a representative answer, a failure and a saved record. Agents implement, debug, test, push scoped PRs and publish concise technical evidence. Continue the complete assigned work without needing repeated prompts. Stephen retains merge and shared-definition decisions. Research discussion and raw experimental results remain outside GitHub.

## Progress, time and handoff

Report the current stage, elapsed time, log location and next timeout. Low GPU use alone does not mean a hang. Model downloads should show increasing bytes/completed files; builds should show advancing logs. Measure actual durations before estimating a batch. Fresh setup can take tens of minutes or longer and may be needed again on a new instance. This document does not promise a completion time or authorize an unbounded run.

Every handoff includes commit/configuration, task and run IDs, what passed/failed/unrun, evidence location, observed time/resource use, missing dependencies and next action. Keep code fixes separate from changes to the supplied run definition. Leave time before the reservation ends to stop workers, copy outputs and verify them off the node. A receiver that depends on a laptop needs that laptop awake and connected.
