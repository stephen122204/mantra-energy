# Aldric: human guide

**Your work:** Verifiable goals and controlled execution. **First task:** [ED-03, issue #3](https://github.com/stephen122204/alems-energy-diagnosis/issues/3).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [aldric.txt](aldric.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/07-aldric-workloads-verifiers.md) is supporting detail for you and required reading for the agent.

## Your question and purpose

You establish what “completed correctly” means and ensure the execution changes preserve the task. Start with one fixed data-analysis goal and an independent checker. Then add meaningful tool concurrency/worker controls and a second repository-analysis family. This makes energy-saving recommendations about equivalent useful work instead of merely shorter or incorrect executions.

## Work you own as a human

Explain the task and independently inspect its expected answer. Check that the verifier rejects a plausible wrong answer as well as malformed or missing output; it must not simply trust the model's success claim. Review the task's realism, input permissions/licenses and which operations can actually run independently. Agree interface details and task semantics with Stephen before broadening the workload set.

## Work your agent should execute

Have the agent inspect existing tools, create small immutable input assets and a versioned independent verifier, and test correct, incorrect, malformed and missing-evidence cases. Subsequent work implements the four proposed controls with observable effects, preserves dependencies/result mapping, and packages a single-goal executor. It should record candidate eligibility, input lineage and replay divergence instead of silently accepting invalid comparisons.

## Hardware, dependencies and handoff

Begin on your own computer; an assigned team Intel machine is optional. Verifier fixtures need no model or GPU. Later validate actual tool execution with Alex's runtime in the shared Grace A100 environment. Use Stephen's common contracts; your initial verifier can be developed independently. Nitheesh's real runner needs your task specification, verifier and single-goal executor.

## What done means

The first PR delivers one fixed goal, immutable inputs, a tested independent verifier and portable task contract. Show a correct example and a deliberately wrong one. The next handoff adds eligible execution controls, their tested semantic equivalence and four pilot assets across two families. Component completion requires evidence about correctness and execution; a generated task list alone is insufficient.

## Start and finish each session

Read your issue and the current shared context; state any unresolved contract assumption. Your agent works on a named issue branch from current integration, opens a draft PR early, tests on that branch and pushes scoped changes autonomously. Stephen reviews and decides merges. Review a representative output yourself and report a specific blocker rather than waiting silently. When another PR is pending, continue independent work in a separate issue branch.

At the end, provide the PR link, tested commit, exact test results, example artifact, remaining evidence and next action. Have the agent publish its reviewable context summary with author `aldric` after every completed turn using the [shared protocol](../README.md). Context publication is separate from code review; it does not merge implementation changes. See [dependencies and hardware](../DEPENDENCIES_AND_HARDWARE.md) for the later gates.
