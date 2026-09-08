# Independent work, testing and PR review

This is the common workflow for every contributor and model. Stephen reviews integration; agents can continue scoped implementation, testing and feature-branch pushes without waiting for review. The shared notebook protocol is in [README.md](README.md).

## Two publication paths

**Code and maintained documentation:** one bounded issue per feature branch and PR. This includes shared interfaces, scripts, instructions and experiment definitions. Push autonomously to the assigned feature branch; integrate through Stephen's review. Do not self-merge or enable auto-merge merely because CI passes. These instructions do not grant merge permission; an explicit direction from Stephen can authorize a particular merge.

**Per-turn context:** publish an immutable note and your own LATEST.md through the isolated publisher after every completed turn. These narrow updates go straight to integration so collaborators can read them immediately. They do not need a PR. Do not use context notes as a route to install code, change a shared contract or expose hidden evaluation results.

## Lifecycle for each issue

1. Fetch integration, read the four latest context records, inspect working changes and identify the assigned issue, owner, acceptance criteria and dependencies. Confirm which shared interface version the task uses. Agree on unresolved cross-component contracts through ED-01 before inventing incompatible APIs.
2. Create an issue branch from `origin/research/energy-diagnosis`, using an isolated checkout/worktree if another task is in progress. Role branches are starting points; do not pile unrelated issues into a single permanent branch. Never discard someone else's changes.
3. Make a small useful first commit, push it, and open a **draft PR early** against integration. Its title/body explain the intended result, known gaps and dependencies. Later pushes update the same PR. Search existing PRs before creating one to avoid duplicates.
4. Continue implementing and testing on that branch. Commit/push scoped changes after each turn when code changed, with truthful work-in-progress status. Publish context even when no code changed or tests failed. A push does not mean ready for review.
5. Mark the PR **ready for review** when its own acceptance criteria are met, relevant tests have passed, dependencies and remaining limitations are explicit, and the diff contains only intended changes. If the issue requires hardware evidence and only mocks have run, keep it draft or agree with Stephen to split off a completed software-only issue. Never silently weaken the original acceptance criteria.
6. Stephen reviews correctness, evidence, shared-interface impacts and experiment-definition changes. Address comments on the same branch and rerun affected checks. A passing setup workflow is not sufficient evidence for model/measurement behavior.
7. After merge, fetch integration and update dependent work. Resolve conflicts by understanding both changes; do not overwrite the other side wholesale. Run checks affected by the combined change and record the actual tested commit. Close the issue only when its deliverable is complete, not merely because a partial PR merged.

## Progress while waiting for review

Pick another independent issue and create a fresh branch from integration. Do not append it to the PR awaiting review. Useful independent work includes provider fixtures, verifier cases, ledger restart tests, task assets, analysis specifications and documentation of actual observations.

If the next task depends on an unmerged PR, prefer another independent task. When dependent work is necessary, make the dependency explicit in both PRs and context: identify the prerequisite PR and commit, and branch from it. A dependent/stacked PR may temporarily target the prerequisite branch for a readable incremental diff; label that base clearly and do not merge it into the prerequisite branch. After the prerequisite merges, retarget to integration, inspect the entire diff for duplicated or unrelated changes, and rerun affected checks. With squash merges, a fresh branch from integration plus only the dependent commits may be cleaner; preserve the old branch until the replacement is verified and link the superseding PR.

Never silently copy another agent's unfinished code or present tests against a private dependency as tests of the shared integration version. Merge current integration into already published branches rather than rewriting their shared history. No force-pushes under the standing authorization.

## Independent testing and its limits

Runtime work can use representative provider responses and sensor fixtures. Workloads can validate inputs, incorrect answers and independent verifiers without a collector. Campaign work can exercise simulated success, failure and interruption without a model. The fixtures must implement the agreed interface and be labeled simulated; they are not physical measurements.

Use three evidence levels as applicable: focused component tests; cross-component integration tests; actual model/hardware validation. Record exact commands, commit, configuration, results and artifacts. For a hardware run include model/runtime/task/verifier versions, allocation/device identity, isolation status and measured energy domains. An unmerged branch can run a real experiment if its allocation/session is authorized; the resulting evidence must name that branch's exact commit.

Do not run competing energy experiments on the same measured resources. Distinct Git branches do not isolate CPU-package or GPU energy. Coordinate booked sessions and use separate output directories. GPU jobs are not launched by ordinary CI or merely because a PR was opened.

Run tests appropriate to the changed behavior. Recheck affected components after integration/conflict resolution; do not repeat expensive hardware campaigns solely because another author published a context-only commit. If executable code, task/verifier definitions, runtime settings or measurement boundaries changed, assess whether earlier evidence still applies. Frozen campaigns require explicit versioning and impact review.

## Shared files and interface changes

Stephen owns cross-component decisions. Coordinate edits to the harness, schema, shared contracts and experiment manifest before parallel implementations diverge. Put an interface change in a small PR with a compatible transition or an explicit list of consumers that must change. Include both producer and consumer checks where appropriate. The first integration goal should happen early; independent testing alone cannot establish that all components work together.

## What every PR must tell Stephen

- Concrete behavior changed and linked issue.
- Base branch, dependencies, and shared interfaces/files affected.
- Exact test commands/procedures and results, with fixture versus real-runtime/hardware evidence distinguished.
- Failed or unrun tests, remaining uncertainty and any acceptance criteria still outstanding.
- Actual commit/configuration for experimental artifacts, plus implications for other agents or frozen data.

Keep raw large logs and datasets in approved artifact storage with links/hashes. The context note should link the PR and state draft, ready, changes requested, merged or blocked.

## Permissions and enforcement

Contributors must use individually authorized GitHub and cluster accounts. Folder names are not GitHub identities. Branch protection is unavailable under the current private-repository plan, so required approval is a project instruction rather than an enforced GitHub rule. CODEOWNERS and CI do not themselves prevent a direct push.

GitHub does not allow an author to approve their own PR. When a PR is created through Stephen's account, do not fabricate an independent approval; Stephen can review its diff and explicitly decide whether to merge it. Other students' accounts should be used for their own work once provisioned. No student invitation, account sharing or merge is implied by opening a PR.

## Track full-role progress

Before selecting work, read [complete assignments](COMPLETE_ASSIGNMENTS.md) and your personal FULL_ASSIGNMENT.md. In each handoff identify the milestone this PR covers and what remains across the full role. The first PR does not finish the role. At the next session provide a complete milestone/evidence/dependency table in your own context; continue ready independent milestones in separate branches while review proceeds. Local integrated success/failure checks precede the main Grace integration; an early bounded Grace capability check can run alongside component development.

