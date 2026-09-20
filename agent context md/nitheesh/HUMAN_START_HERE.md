# Nitheesh: keeping the complete run record

Your part is making sure we can tell exactly what happened after a batch finishes, including when something fails. We should be able to start the approved batch, leave it running, then inspect its results without manually starting every task.

## Where to begin

Read [the current team handoff](../CURRENT_HANDOFF.md) for connection steps, the shared machine and who is doing what. Then give your agent [nitheesh.txt](nitheesh.txt). It must read [the detailed acceptance checklist](../BATCH_ACCEPTANCE.md) and [your complete assignment](FULL_ASSIGNMENT.md), inspect existing code and keep finished work. Older first-task instructions are historical starting points, not an instruction to start over.

Use the existing runner and record store. Connect Alex’s measurements and Aldric’s tasks/checkers. Test one success, one wrong answer, one missing reading, and one interrupted run. Check that restarting preserves old results and does not accidentally repeat completed work.

## What you hand over

Give Stephen one tested launch command, its configuration, clear progress/error logs, and a verified copy of all outputs. Include the time limit and safe resume procedure. The handoff is finished when another person can run the small batch, understand every attempt and verify the saved files.

## Human and agent work

You inspect representative saved records and confirm the backup is readable. Your agent builds and tests scheduling, recovery and exports. You do not need to watch every model call; the runner must track progress and stop at its assigned limit.

Develop on your own computer. Actual model/tool execution and energy readings happen on the assigned Linux node; Stephen supplies access, environment and run budget. Work can be written in parallel, but measured jobs use one shared queue. Do not start an additional model job, build or download during someone else's measurement.

Keep working through ready assigned software tasks while reviews are pending. Use separate PRs and record the exact tested version. A genuine access or runtime blocker affects the dependent test, not every task. Stephen decides merges and changes to shared run definitions.

## How to report

Say what ran, what passed, what failed or remains untested, where the evidence is, and what comes next. Keep failed results. A slow result is not automatically a software bug. If measurements or saved files cannot be trusted, pause affected runs and send the evidence to Stephen. Continue independent work. Publish implementation notes and code only; research discussion and real result files stay in private storage.
