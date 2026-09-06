# Human start here: the A-LEMS energy-diagnosis study

## What we are investigating

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

## Read in this order

1. This overview, then your personal human guide: [Alex](alex/HUMAN_START_HERE.md), [Aldric](aldric/HUMAN_START_HERE.md), [Nitheesh](nitheesh/HUMAN_START_HERE.md), or [Stephen](stephen/HUMAN_START_HERE.md).
2. The [dependencies and hardware guide](DEPENDENCIES_AND_HARDWARE.md). The first tasks can proceed mostly in parallel; real measured experiments require integration.
3. Open your linked first issue. Give your entire `name.txt` to your coding agent with access to your own checkout. The agent should read the technical context and begin the bounded task. You do not need to paste every technical document yourself.

The kickoff documents are proposed in [PR #14](https://github.com/stephen122204/alems-energy-diagnosis/pull/14). Until merged, read them on that PR's branch; implementation branches still start from current `research/energy-diagnosis`. The prompts contain the essential workflow even if some new guides are not yet on integration. Do not merge an unreviewed documentation branch into your work just to start fixtures.

## Human responsibilities and agent responsibilities

Each person owns the meaning and credibility of their result. Read your assignment, make sure you can explain what a passing test establishes, inspect a representative output and a failure, and flag assumptions you cannot verify. Arrange your own repository/cluster access and coordinate resource use with Stephen. Decide with Stephen when a component is ready for real integration. An agent's confident summary is not experimental evidence.

Your agent can inspect existing code, reproduce defects, implement scoped changes, create meaningful tests and small fixtures, run those tests, and prepare reproducible handoffs. It should push its scoped branch changes autonomously, open/update a draft PR, and publish a reviewable context summary after every completed turn using the supplied helper. Shared notes contain understanding, hypotheses, concise rationale and evidence, never private internal reasoning transcripts. Agents do not merge their own PRs or run an unbudgeted campaign.

At the first check-in, provide your GitHub username if access is pending, your development environment, a short explanation of your assigned question, and the first PR or a specific blocker. At each handoff, provide the PR, tested commit, exact test results, a small example artifact, missing evidence and the next action. Keep one issue per PR; test on your branch while Stephen reviews and start another independent issue separately if useful. Coordinate changes to shared interfaces before implementing incompatible versions.

## Hardware and completion gates

Start on existing development computers with small synthetic fixtures; no new GPU purchase is needed for those tasks. The proposed primary experimental platform is a characterized Grace A100 allocation. Team access is reported, but individual permissions, available allocation, CPU-energy readings and isolation still need confirmation. FASTER/Lonestar and ACCESS H100/H200 are not required to begin this work.

Use individually authorized accounts and scheduled sessions. Do not run model inference on login nodes. A separate branch does not isolate shared CPU/GPU energy measurements. Alex validates the runtime and sensors, Aldric supplies verifiable goals and execution controls, and Nitheesh integrates them into the campaign record; Stephen coordinates contracts and scientific decisions.

Integrate and verify one real goal before any larger bounded run. Preserve failures, missing measurements and actual costs. Stephen supplies the approved configuration and run budget.
