# Human start here: the A-LEMS energy-diagnosis study

**Before starting or resuming:** follow the [required context-loading checklist](STARTUP_CHECKLIST.md). Read the complete current shared and named context; demonstrate all-role understanding, then continue implementation in the same session. This applies even with an old kickoff attachment or an agent that does not automatically load AGENTS.md.

**Required full scope:** read [complete team assignments and merge gates](COMPLETE_ASSIGNMENTS.md) and your named full-role checklist. The first issue is only the first milestone. At the next agent session, account for every milestone and continue ready assigned work; retain explicit hardware and pilot-expansion gates.

## What we are investigating

Can a small amount of profiling tell us how to run an AI-agent task using less measured energy while still completing it correctly and within acceptable time? A-LEMS provides the execution and measurement foundation. Our intended contribution is a useful, economical recommendation about execution, validated on new goals against simple alternatives. A larger configuration sweep or another hardware comparison would not establish that contribution.

We are targeting SIGMETRICS, but neither novelty nor publication readiness is established. The first work builds the trustworthy evidence needed to decide whether the idea deserves a full evaluation. Read the [implementation validation boundaries](SIGMETRICS_ASSESSMENT.md) for what each kind of test establishes.

## Background before you start the agent

An **agentic goal** is a complete useful task: for example, inspect fixed data, compute the requested summaries and return a reconciled answer. It may involve several model requests and tool calls. An **independent verifier** checks the answer against fixed rules or reference computations; the model saying it succeeded is not enough.

A **configuration** changes how the same task executes. Our proposed initial controls vary concurrent independent tool calls and tool workers while keeping the model and allocated resources fixed. More parallel work can shorten a task but also change power use. Energy is accumulated over time, so neither lower power nor shorter duration alone guarantees lower energy.

**Profiling** means spending measured work to learn which configuration to choose. That expense must be included when judging the recommendation. Our method must earn its complexity against simple choices such as a fixed setting or a small ordinary configuration test. A **baseline** is one of these explicit comparison methods, not a deliberately weak opponent.

**Energy per verified completion** relates measured energy spent across the specified attempts, including failures, to the number of independently verified completions. If there are no verified completions, this ratio is undefined. We also report success, latency, profiling expense and measurement coverage; a favorable ratio alone is not enough. A **held-out goal** is a task reserved for evaluation that was not used to tune the decision rule.

A **fixture** is a small controlled test input, such as a saved model response or simulated interrupted run. Fixtures let us build and test components without a GPU. The **pilot** is a small real experiment that checks whether the assembled system produces valid data and whether the proposed method has a useful opportunity. Fixture success is software evidence; it does not demonstrate energy savings.

A concrete proposed example: several independent data summaries might run together or sequentially, with different worker counts. Aldric establishes that each setting still computes the correct answer; Alex establishes that the runtime and measured energy boundaries are credible; Nitheesh preserves every attempted execution; Stephen evaluates whether limited profiling can select a worthwhile setting on new tasks. This is an illustration of the experiment, not a reported result.

## Read in this order

Read the [Fall timeline and practical work split](FALL_TIMELINE.md): first usable real pilot data by **15 September**, core evaluation data by **25 September**, a **26 September–1 October** experimental buffer, abstract registration **2 October**, and paper submission **9 October**. These are targets subject to the stated evidence/access gates.


1. This overview, then your personal human guide: [Alex](alex/HUMAN_START_HERE.md), [Aldric](aldric/HUMAN_START_HERE.md), or [Nitheesh](nitheesh/HUMAN_START_HERE.md).
2. The [dependencies and hardware guide](DEPENDENCIES_AND_HARDWARE.md). The first tasks can proceed mostly in parallel; real measured experiments require integration.
3. Open your linked first issue. Use the `.txt` attached to the kickoff email: Alex uses `alex.txt`, Aldric uses `aldric.txt`, and Nitheesh uses `nitheesh.txt`. Repository copies are linked in each personal guide. Give your entire `name.txt` to your coding agent with access to your own checkout. The agent must read the full role, report all milestones and begin the next ready bounded task. You do not need to paste every technical document yourself.

Skim the overview and your own assignment, focusing on the task, correctness checks and handoff; do not read the entire codebase before starting. Let the agent investigate implementation details. Spend human time on hardware, consequential logic checks, debugging behavior and inspecting representative evidence. Then attach or paste the whole prompt into a new coding-agent session opened on your own repository checkout. The prompt tells the agent to inspect the complete assignment and existing progress, then begin the next ready bounded task; it should return a tested PR or a precise blocker. You review a representative result and the stated limitations.

The named guides and earlier PR workflow documents are merged. Use current repository prompts rather than stale email attachments. Read the full assignment before choosing the next bounded milestone; do not restart an already completed first issue.

## Human responsibilities and agent responsibilities

Each person owns the meaning and credibility of their result. Read your assignment, make sure you can explain what a passing test establishes, inspect a representative output and a failure, and flag assumptions you cannot verify. Arrange your own repository/cluster access and coordinate resource use with Stephen. Decide with Stephen when a component is ready for real integration. An agent's confident summary is not experimental evidence.

Your agent can inspect existing code, reproduce defects, implement scoped changes, create meaningful tests and small fixtures, run those tests, and prepare reproducible handoffs. It should push its scoped branch changes autonomously, open/update a draft PR, and publish a reviewable context summary after every completed implementation turn using the supplied helper. Shared notes contain understanding, hypotheses, concise rationale and evidence, never private internal reasoning transcripts. Agents do not merge their own PRs or run an unbudgeted campaign.

At the first check-in, provide your GitHub username if access is pending, your development environment, a short explanation of your assigned question, and the first PR or a specific blocker. At each handoff, provide the PR, tested commit, exact test results, a small example artifact, missing evidence and the next action. Keep one issue per PR; test on your branch while Stephen reviews and start another independent issue separately if useful. Coordinate changes to shared interfaces before implementing incompatible versions.

## Picture the system you are building

Your laptop or desktop is the development and inspection machine. The measured experiment runs inside an assigned Grace compute-node job: the A100 runs the language model; host CPUs run tools and the verifier; A-LEMS observes execution and energy; the ledger saves the attempt and its artifacts. Alex makes the runtime and measurements trustworthy, Aldric makes one useful task executable and checkable, and Nitheesh makes repeated runs reliable and traceable. The personal guides include concrete examples and the proposed resource allocation.

## Hardware and completion gates

Start on existing development computers with small synthetic fixtures; no new GPU purchase is needed for those tasks. The proposed primary experimental platform is a characterized Grace A100 allocation. Team access and no-sudo CPU RAPL reads have been reported by Alex; confirm each individual session, remaining allocation, actual energy-domain coverage and isolation. FASTER/Lonestar and ACCESS H100/H200 are not required to begin this work.

Use individually authorized accounts and scheduled sessions. Do not run model inference on login nodes. A separate branch does not isolate shared CPU/GPU energy measurements. Alex validates the runtime and sensors, Aldric supplies verifiable goals and execution controls, and Nitheesh integrates them into the campaign record; Stephen coordinates contracts and scientific decisions.

The sequence is: agreed interface examples and parallel component tests → one real verified and measured goal on Grace → a bounded pilot → a decision about whether the method beats fair simple baselines → frozen evaluation on new goals. Do not skip to a large campaign because the fixtures pass. Failed goals, missing energy and profiling cost remain in the record. Missing energy is not zero, and CPU-package plus GPU-board readings do not claim whole-machine energy.
