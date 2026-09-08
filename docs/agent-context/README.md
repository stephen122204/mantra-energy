# A-LEMS energy diagnosis: student and agent handoff

**Repository setup is now complete:** read [00-setup-status.md](00-setup-status.md) for the actual repository, baseline, branches, issues and remaining access tasks. The setup instructions below are retained as rationale and future reference.

Prepared 5 September 2026. Target: SIGMETRICS 2027 Fall. This is a development and research handoff, not a completed implementation or evidence of novelty.

## Start here

Stephen should establish one shared research repository and a common baseline before students make changes. Students own components of one experiment, not separate platform papers. See [repository setup](02-repository-setup.md). This pack does not create a remote repository, invite collaborators, start jobs or change production A-LEMS.

Copy this entire directory into the research repository as `docs/agent-context/`. Its relative links and bundled planning materials are portable. Keep any existing repository instructions; merge the relevant rules from [AGENTS.md](AGENTS.md) into the repository root instructions. A nested AGENTS.md alone will not govern agents editing code elsewhere. For tools that do not automatically read AGENTS.md, explicitly supply it with the assignment prompt.

## Reading order

Everyone: [agent rules](AGENTS.md) → [project brief](01-project-brief.md) → [code map](03-code-map.md) → [interfaces](04-interfaces-and-data.md) → assigned role. Read the hardware guide before cluster work. Do not indiscriminately attach the old thermal proposals or entire historical chat: several assumptions have been superseded.

| File | Use |
|---|---|
| [01-project-brief.md](01-project-brief.md) | Research question, limits, candidates and success criteria |
| [02-repository-setup.md](02-repository-setup.md) | Stephen's preparation, private repository versus fork, remotes and integration |
| [03-code-map.md](03-code-map.md) | Reviewed baseline, existing components, concrete problems to reproduce |
| [04-interfaces-and-data.md](04-interfaces-and-data.md) | Shared module boundaries and measurement semantics |
| [05-hardware-and-access.md](05-hardware-and-access.md) | Alex's updated access report, equipment, preflight and job conditions |
| [06-alex-runtime-measurement.md](06-alex-runtime-measurement.md) | Alex: inference and trustworthy telemetry |
| [07-aldric-workloads-verifiers.md](07-aldric-workloads-verifiers.md) | Aldric: tasks, verifiers and bounded tool execution |
| [08-nitheesh-campaign-reproducibility.md](08-nitheesh-campaign-reproducibility.md) | Nitheesh: runner, validation and reproducibility |
| [09-stephen-method-integration.md](09-stephen-method-integration.md) | Lead's scientific responsibilities, evaluation and decisions |
| [10-first-issues-and-milestones.md](10-first-issues-and-milestones.md) | Dependency order and reviewable first issues |
| [11-agent-prompts.md](11-agent-prompts.md) | Copyable starting prompts for different models |
| [12-progress-template.md](12-progress-template.md) | Evidence-based status handoff |
| [13-sources-and-status.md](13-sources-and-status.md) | Source provenance, evidence limits and superseded assumptions |
| [starter/README.md](starter/README.md) | Existing planning utility, manifest and complete data contract |

## Before distributing

Stephen fills in the repository URL, chosen baseline commit, student names, allowed work directories, integration branch, and who can launch which cluster jobs. These are intentionally not invented here. Each student can inspect code and build local fixtures before hardware access is ready.

There are no raw emails, screenshots, credentials, model weights or experimental databases in this pack. Operational facts from Alex are summarized as reported evidence. Share this research context with the intended team; do not blindly publish it through a public fork.

## Current status in one paragraph

A-LEMS already provides local inference adapters, execution instrumentation, a database and thermal/energy readers. Selected source was reviewed at `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`; this is a review reference, not a claim about today's default branch or best deployment baseline. Alex reports GPU access on Grace/FASTER/Lonestar and approved Explore ACCESS. Stephen's account, remaining balances, exact CPU-energy access and measurement isolation still need verification. The diagnostic runner, workloads, selector and experiment results are not supplied as working implementations. The bundled schedule generator only generates plans.
