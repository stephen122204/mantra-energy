# Team kickoff message

Human starting point: [overview](HUMAN_START_HERE.md), then [Alex](alex/HUMAN_START_HERE.md), [Aldric](aldric/HUMAN_START_HERE.md), [Nitheesh](nitheesh/HUMAN_START_HERE.md), or [Stephen](stephen/HUMAN_START_HERE.md).

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

The first software tasks can run mostly in parallel. I will establish the small shared data/interface contract so each component fits the others. You do not need to wait for the entire system or a GPU reservation to begin isolated tests. Later, the components must come together for one real goal before we run the pilot.

Alex will start on a development computer with the local-model response tests/fixes in ED-02. Once an individual account and session are assigned, the main hardware is Grace A100 for live inference and CPU/GPU energy validation. Your handoff is a tested model interface, trustworthy measurement records and a clear report of what the sensors cover. Aldric and Nitheesh depend on these for real execution and measurement.

Aldric will start locally with one fixed data-analysis task and an independent verifier in ED-03; the team Intel machine is an option if assigned. These tests do not need a model or collector. You will then add meaningful tool controls and a repository-analysis family, and validate them with Alex's runtime on Grace. Your handoff is immutable task inputs, verifiers and a single-goal executor that Nitheesh's runner can use.

Nitheesh will start locally with ED-04: a ledger tested using simulated successes, failures and interruptions. This needs no GPU. You can build the runner before the other components finish, but the real Grace pilot depends on Alex's runtime/measurements and Aldric's tasks/controls. Your handoff is a complete, reproducible record of runs, outcomes, energy coverage and actual execution costs.

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

Our sequence is shared contract plus parallel component work, then one integrated verified goal on Grace, then the bounded pilot, then a scientific go/no-go decision and a frozen evaluation on new goals. Passing individual tests is not the same as completing integration, and completing the software is not proof of a publishable result.

At the start of each session, read current shared context and your issue. Work on a separate branch, open a draft PR early and keep testing while I review. At the end, push scoped work, record the exact tests/results and publish your context summary. If blocked, state the specific missing dependency and work on another independent part. Book energy experiments so unrelated jobs do not share the measured resources; a separate branch does not provide hardware isolation.

Use your updated name.txt to start your agent. Send me your GitHub username if access is still pending. Start guide: https://github.com/stephen122204/alems-energy-diagnosis/blob/research/energy-diagnosis/START_HERE.md

