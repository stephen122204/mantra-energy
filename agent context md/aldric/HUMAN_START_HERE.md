# Aldric: checking the work and answers

Your part is making sure the computer actually completes the requested task correctly. If two settings are compared, both must do equivalent useful work and have access to the same tools. We cannot rely on the model saying that it succeeded.

## Where to begin

Read [the current team handoff](../CURRENT_HANDOFF.md) for connection steps, the shared machine and who is doing what. Then give your agent [aldric.txt](aldric.txt). It must read [the detailed acceptance checklist](../BATCH_ACCEPTANCE.md) and [your complete assignment](FULL_ASSIGNMENT.md), inspect existing code and keep finished work. Older first-task instructions are historical starting points, not an instruction to start over.

Start from the existing tasks and answer checkers. Pick a supplied task, work out its expected answer independently, and deliberately try wrong and incomplete answers. Make sure they fail. Connect the task to the shared runner and record what its tools actually do.

## What you hand over

Give Nitheesh runnable task definitions, versioned answer checkers and clear correct/incorrect examples. Help Stephen prepare inputs that actually exercise moving model pieces. This handoff is finished when the tasks work through the shared runner and a human can understand why each answer passed or failed.

## Human and agent work

You check a representative answer yourself and assess whether the task makes sense. Your agent writes and tests the task/checker code and fixes integration issues. You are not being assigned model training or a Windows/Android port.

Develop on your own computer. Actual model/tool execution and energy readings happen on the assigned Linux node; Stephen supplies access, environment and run budget. Work can be written in parallel, but measured jobs use one shared queue. Do not start an additional model job, build or download during someone else's measurement.

Keep working through ready assigned software tasks while reviews are pending. Use separate PRs and record the exact tested version. A genuine access or runtime blocker affects the dependent test, not every task. Stephen decides merges and changes to shared run definitions.

## How to report

Say what ran, what passed, what failed or remains untested, where the evidence is, and what comes next. Keep failed results. A slow result is not automatically a software bug. If measurements or saved files cannot be trusted, pause affected runs and send the evidence to Stephen. Continue independent work. Publish implementation notes and code only; research discussion and real result files stay in private storage.
