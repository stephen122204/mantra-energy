# Alex: human guide

## Your whole assignment—not only the first PR

**Your full responsibility is: model adapter → trustworthy measurement session → real Grace validation → integration and campaign measurement support → reproducible measurement evidence.** The first issue below is only the entry milestone. Read the [complete milestone checklist](FULL_ASSIGNMENT.md): it states every deliverable, what must be tested, who depends on it, and the final completion criteria. Later ready software milestones are already assigned; they do not require another invitation to begin. Pilot expansion and hardware runs keep their explicit gates.

At the next check-in, have your agent show the status of **every milestone**, including later work and dependencies, so you can check the full scope together. Do not report the role complete based only on the first PR.

**Your work:** Runtime and measurement reliability. **First task:** [ED-02, issue #2](https://github.com/stephen122204/alems-energy-diagnosis/issues/2).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [alex.txt](alex.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/06-alex-runtime-measurement.md) is supporting detail for you and required reading for the agent.

## What to expect from your agent

Give the agent the updated prompt and let it work through the **entire assigned implementation**, tests, debugging and integration. It should not stop after a PR or ask you to assign the next listed milestone. You inspect representative behavior, help with actual access or consequential decisions, and review its full-role evidence; you should not have to keep prompting “continue” after every component. The agent should fix failures in its own work and progress on other items while a dependency or PR review is pending. Report only real blockers. Preparing the software for later evaluation is part of the work now; actual large experiments still depend on the pilot and approved resources.

## The machine this work is for

**Develop on your existing laptop or desktop; deploy the real experiment to a scheduled Linux compute node in Texas A&M HPRC’s Grace cluster.** The proposed study allocation uses **one NVIDIA A100 with 40GB GPU memory**, with **16 allocated CPU cores and 64GB host RAM** as an initial resource target. The CPU/RAM allocation is our proposal, subject to scheduler policy, isolation and measured requirements. It is not a reservation. [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/)

The GPU runs the selected local language model. CPU cores run tool computations, verification and supporting processes. A-LEMS and the measurement collector run alongside them in the same allocation. Your development computer is where you edit and inspect; laptop energy is not the target measurement. Here “local model” means inference on the experimental compute node, not an external paid API. The model/runtime choice still needs validation; a 7B-class model is the current pilot direction.

The three assignments build cooperating pieces of one experiment on this platform. Keep one goal and one model request active at a time initially; the proposed controlled parallelism is in independent CPU tool work. A100 allocation alone does not isolate CPU-package readings, so coordinate whole-node isolation or another validated arrangement before energy comparisons. Start with software fixtures now; Alex has reported CPU RAPL reads without sudo; individual access, session budgets, actual domain/device coverage and isolation still require session checks. No separate GPU purchase, H100 migration or multi-node training is part of your starting task. See the [technical hardware plan](../../docs/agent-context/05-hardware-and-access.md).

## Picture what you are building

Think of your part as the model connection and measurement boundary around one real task. Aldric’s executor requests a model response; your existing A-LEMS adapter reaches the model server on the assigned A100, returns usable output and records what actually happened. The collector supplies timed CPU/GPU observations around the actual workload. Nitheesh’s ledger links those outputs to the run that caused them.

A concrete first demonstration is a small model request with an inspectable answer, response/timing metadata and a declared runtime configuration. A later demonstration shows one task’s start/end events joined to raw energy readings, including an honest explanation of any unavailable domain. You should be able to point to the allocated device, actual response and raw evidence—not just a green test summary. The adapter fixtures can be built on any development machine; physical energy validation must occur on Grace.

## Your question and purpose

You make the model response and energy record trustworthy enough for an experiment. First establish that the existing local-provider path produces the right output and honest timing/token information. Then establish what CPU/GPU energy the Grace setup can actually measure. This supports the validity of every later comparison; it is not by itself the claimed research novelty.

## Work you own as a human

Read the assignment and explain the difference between a software fixture, a real model response and validated energy measurement. Confirm the team's working runtime with Stephen, arrange your individual Grace access/session, and inspect one real response and the sensor capability report. Identify exactly which energy domains are readable and whether other jobs share them. Escalate missing CPU energy rather than substituting temperature or utilization. No hardware purchase is assigned.

## Work your agent should execute

Have the agent inspect the active YAML model registry and existing adapter, reproduce the suspected Ollama response-format mismatch using fixtures, and make a minimal compatible repair if reproduced. It should test streamed/non-streamed responses, terminal token counts, malformed/interrupted output and the existing OpenAI-compatible route. Later ED-05 work checks measurement endpoints, delayed collector teardown, missing values, clock domains and counter behavior. Source-review suspicions must be tested before being called observed defects.

## Hardware, dependencies and handoff

Start on your development computer without a GPU for provider fixtures. Full ED-02 completion needs a real local-model response; arrange this in the agreed environment. Grace A100 is the intended live runtime and measurement platform, subject to access, session and capability checks. You need Stephen's agreed interface shape, but can reproduce response-format concerns independently. Aldric needs your model interface; Nitheesh needs your event/energy records.

## First milestone versus full-role completion

Your first PR should contain the reproduced defect (if present), minimal fix, focused tests and actual resolved configuration evidence. Keep live validation explicitly open if it has not run. Your later handoff includes a capability/domain report, tested interfaces, example success/failure/missing-energy records and exact hardware/runtime versions. A passing parser test does not finish telemetry validation.

## Start and finish each session

Read your issue and the current shared context; state any unresolved contract assumption. Your agent works on a named issue branch from current integration, opens a draft PR early, tests on that branch and pushes scoped changes autonomously. Stephen reviews and decides merges. Review a representative output yourself and report a specific blocker rather than waiting silently. When another PR is pending, continue independent work in a separate issue branch.

At the end, provide the PR link, tested commit, exact test results, example artifact, remaining evidence and next action. Have the agent publish its reviewable context summary with author `alex` after every completed turn using the [shared protocol](../README.md). Context publication is separate from code review; it does not merge implementation changes. See [dependencies and hardware](../DEPENDENCIES_AND_HARDWARE.md) for the later gates.

## Timing and effort

Follow the [Fall timeline](../FALL_TIMELINE.md). Start the agent after a short orientation to your objective and checks; a complete codebase read is unnecessary. Agents own most implementation, test execution and PR/context preparation. Your work centers on hardware/access, functional logic, independent output checks and debugging real failures. First reviewable components are targeted for 10 September, integrated execution for 12 September, usable pilot data for 15 September and core evaluation data for 25 September. Report a threatened milestone promptly; dates do not waive evidence requirements.
