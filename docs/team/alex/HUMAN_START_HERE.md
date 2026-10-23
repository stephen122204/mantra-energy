# Alex: checking the measurements

Your part is making sure the numbers describe what the machine actually did. For a task, we need to know when it started and ended, which CPU/GPU energy readings cover that time, and whether anything makes those readings unreliable.

## Where to begin

Read [the current team handoff](../CURRENT_HANDOFF.md) for connection steps, the shared machine and who is doing what. Then give your agent [alex.txt](alex.txt). It must read [the detailed acceptance checklist](../BATCH_ACCEPTANCE.md) and [your complete assignment](FULL_ASSIGNMENT.md), inspect existing code and keep finished work. Older first-task instructions are historical starting points, not an instruction to start over.

Read an example from the current collector. Run its existing tests, repair missing checks, then confirm the readings on the assigned node. Check when model pieces actually move onto the GPU relative to tool execution; a request to move them is not proof they moved.

## What you hand over

Give Nitheesh checked measurement records, an explanation of their fields, and examples of a valid reading and a rejected one. Show the raw evidence behind the totals. You are finished with this handoff when another person can run your check and understand what is measured and what is missing.

## Human and agent work

You inspect a few raw readings and their time boundaries. Your agent does implementation, automated checks and technical writeups. Stephen handles changes to how the model calculates its answers; report any disagreement you find.

Develop on your own computer. Actual model/tool execution and energy readings happen on the assigned Linux node; Stephen supplies access, environment and run budget. Work can be written in parallel, but measured jobs use one shared queue. Do not start an additional model job, build or download during someone else's measurement.

Keep working through ready assigned software tasks while reviews are pending. Use separate PRs and record the exact tested version. A genuine access or runtime blocker affects the dependent test, not every task. Stephen decides merges and changes to shared run definitions.

## How to report

Say what ran, what passed, what failed or remains untested, where the evidence is, and what comes next. Keep failed results. A slow result is not automatically a software bug. If measurements or saved files cannot be trusted, pause affected runs and send the evidence to Stephen. Continue independent work. Publish implementation notes and code only; research discussion and real result files stay in private storage.
