# Nitheesh: human guide

**Your work:** Campaign records and reproducibility. **First task:** [ED-04, issue #4](https://github.com/stephen122204/alems-energy-diagnosis/issues/4).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [nitheesh.txt](nitheesh.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/08-nitheesh-campaign-reproducibility.md) is supporting detail for you and required reading for the agent.

## Your question and purpose

You make every attempted run traceable and reproducible. First build the run ledger with simulated outcomes; later use it to coordinate the real pilot. The scientific purpose is to prevent retries, failures, interrupted work or missing measurements from disappearing and biasing the comparison.

## Work you own as a human

Explain how a planned run becomes an actual attempt and a recorded outcome. Inspect a success, a failure and an interrupted/resumed example yourself. Verify that missing measurements remain visibly missing and that retries remain attributable. Before real jobs, confirm the session budget, artifact storage, runtime versions and isolation with Stephen and Alex. Do not treat a generated plan as executed data.

## Work your agent should execute

Have the agent implement the execution ledger around synthetic fixtures, separate from the planning generator. Test restart/resume, duplicate prevention, interrupted attempts, model/verifier failures and missing energy. Record stable identities and artifact links, then implement validated export and bounded scheduling. Later integrate Alex's runtime/measurement interface and Aldric's single-goal executor, preserving randomized order and every outcome.

## Hardware, dependencies and handoff

Begin on your own computer; ledger fixtures need no GPU. The real pilot runs on an assigned Grace A100 session after runtime, measurements, tasks and controls are ready. Stephen supplies the shared contract and approved plan. You can develop the ledger independently now; actual integration depends on both Alex and Aldric.

## What done means

The first PR delivers a resumable fixture ledger, tests, and a small inspectable export showing successes, failures, interruptions and missing values. The later pilot handoff includes a complete run disposition record, validated raw/derived data, exact tested versions, measurement coverage and actual time/resource costs. Run the bounded pilot only after the integration gate and assigned budget; do not launch the full planning matrix automatically.

## Start and finish each session

Read your issue and the current shared context; state any unresolved contract assumption. Your agent works on a named issue branch from current integration, opens a draft PR early, tests on that branch and pushes scoped changes autonomously. Stephen reviews and decides merges. Review a representative output yourself and report a specific blocker rather than waiting silently. When another PR is pending, continue independent work in a separate issue branch.

At the end, provide the PR link, tested commit, exact test results, example artifact, remaining evidence and next action. Have the agent publish its reviewable context summary with author `nitheesh` after every completed turn using the [shared protocol](../README.md). Context publication is separate from code review; it does not merge implementation changes. See [dependencies and hardware](../DEPENDENCIES_AND_HARDWARE.md) for the later gates.

