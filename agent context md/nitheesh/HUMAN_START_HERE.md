# Nitheesh: human guide

**Your work:** Campaign records and reproducibility. **First task:** [ED-04, issue #4](https://github.com/stephen122204/alems-energy-diagnosis/issues/4).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [nitheesh.txt](nitheesh.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/08-nitheesh-campaign-reproducibility.md) is supporting detail for you and required reading for the agent.

## The machine this work is for

**Develop on your existing laptop or desktop; deploy the real experiment to a scheduled Linux compute node in Texas A&M HPRC’s Grace cluster.** The proposed study allocation uses **one NVIDIA A100 with 40GB GPU memory**, with **16 allocated CPU cores and 64GB host RAM** as an initial resource target. The CPU/RAM allocation is our proposal, subject to scheduler policy, isolation and measured requirements. It is not a reservation. [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/)

The GPU runs the selected local language model. CPU cores run tool computations, verification and supporting processes. A-LEMS and the measurement collector run alongside them in the same allocation. Your development computer is where you edit and inspect; laptop energy is not the target measurement. Here “local model” means inference on the experimental compute node, not an external paid API. The model/runtime choice still needs validation; a 7B-class model is the current pilot direction.

The three assignments build cooperating pieces of one experiment on this platform. Keep one goal and one model request active at a time initially; the proposed controlled parallelism is in independent CPU tool work. A100 allocation alone does not isolate CPU-package readings, so coordinate whole-node isolation or another validated arrangement before energy comparisons. Start with software fixtures now; hardware access, readable CPU energy and session budgets remain preflight items. No separate GPU purchase, H100 migration or multi-node training is part of your starting task. See the [technical hardware plan](../../docs/agent-context/05-hardware-and-access.md).

## Picture what you are building

Think of your part as the experiment’s run controller and record book. It reads the agreed task/configuration plan, invokes Aldric’s single-goal executor using Alex’s runtime/measurements inside the assigned Grace job, and records each attempt’s outcome and artifact locations. It must survive interruption without losing failures or accidentally presenting duplicate executions as fresh evidence.

A concrete first demonstration is a tiny exported run table containing a success, a verifier failure, an interrupted attempt and a missing measurement, all traceable to their inputs and test artifacts. Later, replace those simulated calls with the real Grace execution interface and collect the bounded pilot. Your laptop can develop and inspect the ledger; actual measured workload execution belongs on the allocated compute node, with durable artifacts saved off temporary job storage. Starting another measured goal concurrently is not a way to speed up the initial study because it can mix energy attribution.

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

## Timing and effort

Follow the [Fall timeline](../FALL_TIMELINE.md). Start the agent after a short orientation to your objective and checks; a complete codebase read is unnecessary. Agents own most implementation, test execution and PR/context preparation. Your work centers on hardware/access, functional logic, independent output checks and debugging real failures. First reviewable components are targeted for 10 September, integrated execution for 12 September, usable pilot data for 15 September and core evaluation data for 25 September. Report a threatened milestone promptly; dates do not waive evidence requirements.

