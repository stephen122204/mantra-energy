# Human start here: the A-LEMS energy-diagnosis study

## What we are investigating

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

## Background before you start the agent

An **agentic goal** is a complete useful task: for example, inspect fixed data, compute the requested summaries and return a reconciled answer. It may involve several model requests and tool calls. An **independent verifier** checks the answer against fixed rules or reference computations; the model saying it succeeded is not enough.

A **configuration** changes how the same task executes. Our proposed initial controls vary concurrent independent tool calls and tool workers while keeping the model and allocated resources fixed. More parallel work can shorten a task but also change power use. Energy is accumulated over time, so neither lower power nor shorter duration alone guarantees lower energy.

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

**Energy per verified completion** relates measured energy spent across the specified attempts, including failures, to the number of independently verified completions. If there are no verified completions, this ratio is undefined. We also report success, latency, profiling expense and measurement coverage; a favorable ratio alone is not enough. A **held-out goal** is a task reserved for evaluation that was not used to tune the decision rule.

A **fixture** is a small controlled test input, such as a saved model response or simulated interrupted run. Fixtures let us build and test components without a GPU. The **pilot** is a small real experiment that checks whether the assembled system produces valid data and identifies remaining integration defects. Fixture success is software evidence; it does not demonstrate energy savings.

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

## Read in this order

Follow the engineering schedule and approved session budgets. Research and submission planning remain private.

1. This overview, then your personal human guide: [Alex](alex/HUMAN_START_HERE.md), [Aldric](aldric/HUMAN_START_HERE.md), or [Nitheesh](nitheesh/HUMAN_START_HERE.md).
2. The [dependencies and hardware guide](DEPENDENCIES_AND_HARDWARE.md). The first tasks can proceed mostly in parallel; real measured experiments require integration.
3. Open your linked first issue. Use the `.txt` attached to the kickoff email: Alex uses `alex.txt`, Aldric uses `aldric.txt`, and Nitheesh uses `nitheesh.txt`. Repository copies are linked in each personal guide. Give your entire `name.txt` to your coding agent with access to your own checkout. The agent should read the technical context and begin the bounded task. You do not need to paste every technical document yourself.

Skim the overview and your own assignment, focusing on the task, correctness checks and handoff; do not read the entire codebase before starting. Let the agent investigate implementation details. Spend human time on hardware, consequential logic checks, debugging behavior and inspecting representative evidence. Then attach or paste the whole prompt into a new coding-agent session opened on your own repository checkout. The prompt tells the agent to inspect context and begin the first bounded task; it should return a tested PR or a precise blocker. You review a representative result and the stated limitations.

The kickoff documents are proposed in [PR #14](https://github.com/stephen122204/alems-energy-diagnosis/pull/14). Until merged, read them on that PR's branch; implementation branches still start from current `research/energy-diagnosis`. The prompts contain the essential workflow even if some new guides are not yet on integration. Do not merge an unreviewed documentation branch into your work just to start fixtures.

## Human responsibilities and agent responsibilities

Each person owns the meaning and credibility of their result. Read your assignment, make sure you can explain what a passing test establishes, inspect a representative output and a failure, and flag assumptions you cannot verify. Arrange your own repository/cluster access and coordinate resource use with Stephen. Decide with Stephen when a component is ready for real integration. An agent's confident summary is not experimental evidence.

Your agent can inspect existing code, reproduce defects, implement scoped changes, create meaningful tests and small fixtures, run those tests, and prepare reproducible handoffs. It should push its scoped branch changes autonomously, open/update a draft PR, and publish a reviewable context summary after every completed turn using the supplied helper. Shared notes contain understanding, hypotheses, concise rationale and evidence, never private internal reasoning transcripts. Agents do not merge their own PRs or run an unbudgeted campaign.

At the first check-in, provide your GitHub username if access is pending, your development environment, a short explanation of your assigned question, and the first PR or a specific blocker. At each handoff, provide the PR, tested commit, exact test results, a small example artifact, missing evidence and the next action. Keep one issue per PR; test on your branch while Stephen reviews and start another independent issue separately if useful. Coordinate changes to shared interfaces before implementing incompatible versions.

## Picture the system you are building

Your laptop or desktop is the development and inspection machine. The measured experiment runs inside an assigned Grace compute-node job: the A100 runs the language model; host CPUs run tools and the verifier; A-LEMS observes execution and energy; the ledger saves the attempt and its artifacts. Alex makes the runtime and measurements trustworthy, Aldric makes one useful task executable and checkable, and Nitheesh makes repeated runs reliable and traceable. The personal guides include concrete examples and the proposed resource allocation.

## Hardware and completion gates

Start on existing development computers with small synthetic fixtures; no new GPU purchase is needed for those tasks. The proposed primary experimental platform is a characterized Grace A100 allocation. Team access is reported, but individual permissions, available allocation, CPU-energy readings and isolation still need confirmation. FASTER/Lonestar and ACCESS H100/H200 are not required to begin this work.

Use individually authorized accounts and scheduled sessions. Do not run model inference on login nodes. A separate branch does not isolate shared CPU/GPU energy measurements. Alex validates the runtime and sensors, Aldric supplies verifiable goals and execution controls, and Nitheesh integrates them into the campaign record; Stephen coordinates contracts and scientific decisions.

Integrate and verify one real goal before any larger bounded run. Preserve failures, missing measurements and actual costs. Stephen supplies the approved configuration and run budget.
