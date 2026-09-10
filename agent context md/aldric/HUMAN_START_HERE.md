# Aldric: human guide

## Your whole assignment—not only the first PR

**Your full responsibility is: first task/checker → single-goal execution and four controls → four pilot tasks → trace/replay fidelity → Grace integration → conditional expanded task suite and workload evidence.** The first issue below is only the entry milestone. Read the [complete milestone checklist](FULL_ASSIGNMENT.md): it states every deliverable, what must be tested, who depends on it, and the final completion criteria. Later ready software milestones are already assigned; they do not require another invitation to begin. Pilot expansion and hardware runs keep their explicit gates.

At the next check-in, have your agent show the status of **every milestone**, including later work and dependencies, so you can check the full scope together. Do not report the role complete based only on the first PR.

**Your work:** Verifiable goals and controlled execution. **First task:** [ED-03, issue #3](https://github.com/stephen122204/alems-energy-diagnosis/issues/3).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [aldric.txt](aldric.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/07-aldric-workloads-verifiers.md) is supporting detail for you and required reading for the agent.

## What to expect from your agent

Give the agent the updated prompt and let it work through the **entire assigned implementation**, tests, debugging and integration. It should not stop after a PR or ask you to assign the next listed milestone. You inspect representative behavior, help with actual access or consequential decisions, and review its full-role evidence; you should not have to keep prompting “continue” after every component. The agent should fix failures in its own work and progress on other items while a dependency or PR review is pending. Report only real blockers. Preparing the software for later evaluation is part of the work now; actual large experiments still depend on the pilot and approved resources.

## The machine this work is for

**Develop on your existing laptop or desktop; deploy the real experiment to a scheduled Linux compute node in Texas A&M HPRC’s Grace cluster.** The proposed study allocation uses **one NVIDIA A100 with 40GB GPU memory**, with **16 allocated CPU cores and 64GB host RAM** as an initial resource target. The CPU/RAM allocation is our proposal, subject to scheduler policy, isolation and measured requirements. It is not a reservation. [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/)

The GPU runs the selected local language model. CPU cores run tool computations, verification and supporting processes. A-LEMS and the measurement collector run alongside them in the same allocation. Your development computer is where you edit and inspect; laptop energy is not the target measurement. Here “local model” means inference on the experimental compute node, not an external paid API. The model/runtime choice still needs validation; a 7B-class model is the current pilot direction.

The three assignments build cooperating pieces of one experiment on this platform. Keep one goal and one model request active at a time initially; the proposed controlled parallelism is in independent CPU tool work. A100 allocation alone does not isolate CPU-package readings, so coordinate whole-node isolation or another validated arrangement before energy comparisons. Start with software fixtures now; Alex has reported CPU RAPL reads without sudo; individual access, session budgets, actual domain/device coverage and isolation still require session checks. No separate GPU purchase, H100 migration or multi-node training is part of your starting task. See the [technical hardware plan](../../docs/agent-context/05-hardware-and-access.md).

## Picture what you are building

Think of your part as a small runnable experiment task with an answer key. For example, fixed tables require two independent summaries and a reconciliation step. Your executor runs that work and returns an output; your independent verifier decides whether it is correct. The proposed controls change whether eligible CPU tool operations run concurrently and how many workers they use, while preserving the requested answer.

On Grace, the language model uses Alex’s A100-backed runtime, while your data/repository tools and verifier normally execute on the allocated CPU cores. You are building portable task assets, correctness logic and bounded execution controls. Begin with a tiny input you can check yourself: show the correct answer passing, a plausible wrong answer failing, and later evidence that a worker/concurrency change actually changed execution while preserving the answer. Nitheesh then calls this same single-goal executor repeatedly through an agreed interface.

## Your question and purpose

You establish what “completed correctly” means and ensure the execution changes preserve the task. Start with one fixed data-analysis goal and an independent checker. Then add meaningful tool concurrency/worker controls and a second repository-analysis family. This makes energy-saving recommendations about equivalent useful work instead of merely shorter or incorrect executions.

## Work you own as a human

Explain the task and independently inspect its expected answer. Check that the verifier rejects a plausible wrong answer as well as malformed or missing output; it must not simply trust the model's success claim. Review the task's realism, input permissions/licenses and which operations can actually run independently. Agree interface details and task semantics with Stephen before broadening the workload set.

## Work your agent should execute

Have the agent inspect existing tools, create small immutable input assets and a versioned independent verifier, and test correct, incorrect, malformed and missing-evidence cases. Subsequent work implements the four proposed controls with observable effects, preserves dependencies/result mapping, and packages a single-goal executor. It should record candidate eligibility, input lineage and replay divergence instead of silently accepting invalid comparisons.

## Hardware, dependencies and handoff

Begin on your own computer; an assigned team Intel machine is optional. Verifier fixtures need no model or GPU. Later validate actual tool execution with Alex's runtime in the shared Grace A100 environment. Use Stephen's common contracts; your initial verifier can be developed independently. Nitheesh's real runner needs your task specification, verifier and single-goal executor.

## First milestone versus full-role completion

The first PR delivers one fixed goal, immutable inputs, a tested independent verifier and portable task contract. Show a correct example and a deliberately wrong one. The next handoff adds eligible execution controls, their tested semantic equivalence and four pilot assets across two families. Component completion requires evidence about correctness and execution; a generated task list alone is insufficient.

## Start and finish each session

Read your issue and the current shared context; state any unresolved contract assumption. Your agent works on a named issue branch from current integration, opens a draft PR early, tests on that branch and pushes scoped changes autonomously. Stephen reviews and decides merges. Review a representative output yourself and report a specific blocker rather than waiting silently. When another PR is pending, continue independent work in a separate issue branch.

At the end, provide the PR link, tested commit, exact test results, example artifact, remaining evidence and next action. Have the agent publish its reviewable context summary with author `aldric` after every completed implementation turn using the [shared protocol](../README.md). Context publication is separate from code review; it does not merge implementation changes. See [dependencies and hardware](../DEPENDENCIES_AND_HARDWARE.md) for the later gates.

## Timing and effort

Follow the [Fall timeline](../FALL_TIMELINE.md). Start the agent after a short orientation to your objective and checks; a complete codebase read is unnecessary. Agents own most implementation, test execution and PR/context preparation. Your work centers on hardware/access, functional logic, independent output checks and debugging real failures. First reviewable components are targeted for 10 September, integrated execution for 12 September, usable pilot data for 15 September and core evaluation data for 25 September. Report a threatened milestone promptly; dates do not waive evidence requirements.
