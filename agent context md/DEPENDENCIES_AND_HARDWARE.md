# Dependencies, hardware and what completion means

Prepared 6 September 2026. The named split is the kickoff proposal: Alex runtime/measurement, Aldric workloads/verifiers, Nitheesh campaign/reproducibility, Stephen method/integration. Individual GitHub identities and machine access must still be provisioned. This guide describes one shared experiment, not four independent platform studies.

## Work that can start together

Stephen's first enabling task is ED-01: agree on the small shared contract for task/input identity, candidate settings, model response/events, verifier outcome, execution status and measurement records. Provide one small synthetic example that all three components can read/write. Do not hold up useful isolated tests while debating a perfect architecture, but resolve shared field/type/meaning questions before dependent code spreads.

Alex can test provider response parsing with fixed responses. Aldric can build a task and independently check correct and incorrect answers. Nitheesh can test a ledger with simulated execution results. All three can begin locally without an A100 reservation. These fixtures allow independent development against the same contract; they do not prove the combined system works on real hardware.

## Person-by-person start, hardware and handoff

| Person | Can start now | Starting hardware | Later hardware | Deliverable consumed by someone else |
|---|---|---|---|---|
| Alex | ED-02: provider/configuration fixtures and minimal runtime repair | Own development computer; real local model only if available/suitable | Assigned Grace A100 compute session for live model checks and ED-05 energy validation | Tested model-response interface, collector/capability report, explicit domain/timestamp validity and small example records |
| Aldric | ED-03: fixed data goal and independent verifier; then ED-06 controls/ED-08 second family | Own development computer; team Intel machine if specifically assigned | Shared Grace environment to establish real candidate behavior and integration | Immutable tasks, independent verifiers, meaningful candidate controls, trace/dependency contract and single-goal executor |
| Nitheesh | ED-04: fixture-driven ledger, restart/error handling and export checks | Own development computer; no GPU needed for ledger fixtures | Assigned Grace sessions for ED-09 pilot after ED-07/08 | Complete run ledger, failure/missingness reports, reproducible exports and actual run-cost measurements |
| Stephen | ED-01 contracts, task/service definitions, baseline and method design | Own development computer for design, review and analysis | Shared Grace sessions for integration and method evaluation | Agreed interfaces, frozen method/baselines/evaluation, integration decisions and defensible scientific claims |

No person needs a new GPU purchase for their initial software task. Grace is the primary shared measurement platform, subject to actual CPU/GPU energy access and isolation. No additional H100/H200, second cluster or thermal probe is a prerequisite. The model, tools and collector must run in the measured compute allocation for local inference energy claims. A laptop issuing a remote request does not measure the remote model's energy by itself.

## Actual dependency chain

1. **ED-01 interface agreement supports all three implementation streams.** Standalone fixtures can start while the final interface is reviewed; provisional interfaces must be identified explicitly.
2. **ED-07 needs Alex's runtime and measurement checks (ED-02/05), Aldric's first task and controls (ED-03/06), and Nitheesh's execution ledger (ED-04).** All three must fit together for one real independently verified goal with linked energy records. A stub collector or cached model response cannot pass this milestone.
3. **ED-09 pilot needs ED-07 plus Aldric's second family/four pilot assets (ED-08).** Nitheesh can implement the runner beforehand but cannot call an unintegrated fixture schedule a completed pilot.
4. **ED-10's empirical research decision needs pilot/development evidence.** Stephen can design the method and baselines now; demonstrating their value requires valid measurements and goals. If the first pilot is inconclusive, do a bounded development investigation rather than assume the method works.
5. **ED-11 and the main held-out evaluation need a frozen, justified method and an adequate measurement pipeline.** Freeze assets, policies, verifiers, information access and analysis; seal recommendations before independent reference results are read.

ED-12 (individual accounts, assigned allocation and a scheduled session) is a parallel operational dependency for real hardware work. It need not block local fixtures. Team-reported allocation awards are not automatically individual access, a reservation or a verified remaining balance.

## Start and end of a work session

At the start, fetch integration and read the latest shared context and assigned issue. Identify the current contract/version and check whether dependencies are merged, unmerged or simulated. Use a separate issue branch, inspect existing changes and state the next bounded deliverable. Do not restart completed work or silently change the shared experiment.

During work, test locally and push a small draft PR early. Continue independent tasks in separate branches while waiting for review. If genuinely blocked by another PR, state the exact missing interface/artifact and use an explicitly declared dependent branch or choose useful independent work. Do not copy unfinished code without provenance. Shared harness/schema/contract edits require coordination with Stephen.

Before ending, record what changed, tests and failures, artifact links, exact code commit, open questions and the next action. Push scoped code to the feature branch and publish the per-turn context note using the helper. Mark a PR ready only when its stated acceptance evidence is complete. An open review does not prevent testing the branch. Stephen decides code merges; a context-only update goes directly through the scoped publisher.

## Hardware session rules

Use an individually authorized account and a booked compute session. Coordinate who is running energy measurements: separate Git branches do not isolate a shared CPU package or GPU. Keep the resource allocation and preparation protocol consistent across candidate comparisons. Use separate job output locations, record the exact code/model/runtime/task/verifier versions and actual device/allocation identities, and preserve raw data outside ephemeral storage.

Validate readable energy domains rather than only temperature/utilization. If host energy is unavailable, continue software work and report the missing capability; do not present GPU-only observations as evidence for total CPU-tool energy savings. No ordinary CI run, opened PR or planner invocation should launch a GPU campaign.

## Three different meanings of done

**Component complete:** its stated behavior is implemented, relevant positive/negative tests pass, required live checks are documented or completed, and its reviewed interface/artifacts can be consumed by the next person. If hardware evidence is required but absent, that acceptance criterion remains open.

**Engineering pipeline complete:** one real goal and then the bounded pilot execute through all components with correct verification, valid energy boundaries, complete records and reproducible outputs. Passing separate unit tests is insufficient.

**Research contribution supported:** a specified method makes useful decisions on held-out verified goals more economically or reliably than credible simple alternatives, with profiling costs, success, latency, uncertainty and limitations reported. Finishing all software tasks does not automatically establish this result or SIGMETRICS significance. A measured no-benefit result is valid evidence and can require revising the idea.
