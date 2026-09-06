# Alex: human guide

**Your work:** Runtime and measurement reliability. **First task:** [ED-02, issue #2](https://github.com/stephen122204/alems-energy-diagnosis/issues/2).

Start with the [human overview](../HUMAN_START_HERE.md), read this guide, then give your agent [alex.txt](alex.txt) with your repository checkout. The [technical assignment](../../docs/agent-context/06-alex-runtime-measurement.md) is supporting detail for you and required reading for the agent.

## Your question and purpose

You make the model response and energy record trustworthy enough for an experiment. First establish that the existing local-provider path produces the right output and honest timing/token information. Then establish what CPU/GPU energy the Grace setup can actually measure. This supports the validity of every later comparison; it is not by itself the claimed research novelty.

## Work you own as a human

Read the assignment and explain the difference between a software fixture, a real model response and validated energy measurement. Confirm the team's working runtime with Stephen, arrange your individual Grace access/session, and inspect one real response and the sensor capability report. Identify exactly which energy domains are readable and whether other jobs share them. Escalate missing CPU energy rather than substituting temperature or utilization. No hardware purchase is assigned.

## Work your agent should execute

Have the agent inspect the active YAML model registry and existing adapter, reproduce the suspected Ollama response-format mismatch using fixtures, and make a minimal compatible repair if reproduced. It should test streamed/non-streamed responses, terminal token counts, malformed/interrupted output and the existing OpenAI-compatible route. Later ED-05 work checks measurement endpoints, delayed collector teardown, missing values, clock domains and counter behavior. Source-review suspicions must be tested before being called observed defects.

## Hardware, dependencies and handoff

Start on your development computer without a GPU for provider fixtures. Full ED-02 completion needs a real local-model response; arrange this in the agreed environment. Grace A100 is the intended live runtime and measurement platform, subject to access, session and capability checks. You need Stephen's agreed interface shape, but can reproduce response-format concerns independently. Aldric needs your model interface; Nitheesh needs your event/energy records.

## What done means

Your first PR should contain the reproduced defect (if present), minimal fix, focused tests and actual resolved configuration evidence. Keep live validation explicitly open if it has not run. Your later handoff includes a capability/domain report, tested interfaces, example success/failure/missing-energy records and exact hardware/runtime versions. A passing parser test does not finish telemetry validation.

## Start and finish each session

Read your issue and the current shared context; state any unresolved contract assumption. Your agent works on a named issue branch from current integration, opens a draft PR early, tests on that branch and pushes scoped changes autonomously. Stephen reviews and decides merges. Review a representative output yourself and report a specific blocker rather than waiting silently. When another PR is pending, continue independent work in a separate issue branch.

At the end, provide the PR link, tested commit, exact test results, example artifact, remaining evidence and next action. Have the agent publish its reviewable context summary with author `alex` after every completed turn using the [shared protocol](../README.md). Context publication is separate from code review; it does not merge implementation changes. See [dependencies and hardware](../DEPENDENCIES_AND_HARDWARE.md) for the later gates.

## Timing and effort

Follow the [Fall timeline](../FALL_TIMELINE.md). Start the agent after a short orientation to your objective and checks; a complete codebase read is unnecessary. Agents own most implementation, test execution and PR/context preparation. Your work centers on hardware/access, functional logic, independent output checks and debugging real failures. First reviewable components are targeted for 10 September, integrated execution for 12 September, usable pilot data for 15 September and core evaluation data for 25 September. Report a threatened milestone promptly; dates do not waive evidence requirements.

