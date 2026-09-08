# Start here: A-LEMS energy diagnosis

**Required full scope:** read [complete team assignments and merge gates](agent%20context%20md/COMPLETE_ASSIGNMENTS.md) and your named full-role checklist. The first issue is only the first milestone. At the next agent session, account for every milestone and continue ready assigned work; retain explicit hardware and pilot-expansion gates.

**Research question:** Which feasible execution change saves measured energy per correctly completed agentic goal, and can we select it with a small profiling budget?

This is the team's private development repository, based on A-LEMS. The research method and experiments remain to be implemented and validated. GPU access is team-reported; telemetry, individual accounts and isolation require preflight.

Read the [human overview](agent%20context%20md/HUMAN_START_HERE.md) first, then your personal human guide and agent prompt below.

## Pick your starting point

| Person | Read | Work area | First issue |
|---|---|---|---|
| Stephen — orchestration | [Method and integration](docs/agent-context/09-stephen-method-integration.md) | Shared interfaces and `studies/energy_diagnosis/analysis/` | ED-01, then ED-10 |
| [Alex — human guide](agent%20context%20md/alex/HUMAN_START_HERE.md) | [Assignment](docs/agent-context/06-alex-runtime-measurement.md) | Existing adapters/readers/harness; `studies/energy_diagnosis/runtime/` | ED-02 |
| [Aldric — human guide](agent%20context%20md/aldric/HUMAN_START_HERE.md) | [Assignment](docs/agent-context/07-aldric-workloads-verifiers.md) | `studies/energy_diagnosis/workloads/` | ED-03 |
| [Nitheesh — human guide](agent%20context%20md/nitheesh/HUMAN_START_HERE.md) | [Assignment](docs/agent-context/08-nitheesh-campaign-reproducibility.md) | `studies/energy_diagnosis/campaign/` | ED-04 |

Use the [issue tracker](https://github.com/stephen122204/alems-energy-diagnosis/issues). The working assignments are Alex (runtime), Aldric (workloads), Nitheesh (campaign), and Stephen (method/integration). Individual GitHub usernames and repository invitations still need confirmation.

## Clone and begin

Once Stephen grants your GitHub account access:

```bash
git clone https://github.com/stephen122204/alems-energy-diagnosis.git
cd alems-energy-diagnosis
git switch research/energy-diagnosis
python3 scripts/check_energy_diagnosis_setup.py
```

Create an issue branch from the current integration branch. Pre-created role branches are starting points, not independently maintained platform forks. PRs target `research/energy-diagnosis`. Do not install the entire upstream requirements file just to run the bootstrap check; the hardware runtime environment is a separate task.

## Agent context

Read root [AGENTS.md](AGENTS.md), the [context index](docs/agent-context/README.md), your role and the [starting prompt](docs/agent-context/11-agent-prompts.md). The active model registry is `config/models.yaml`; Ollama and vLLM routes already exist. New experiment controls and the diagnostic method are proposed work.

The [setup status](docs/agent-context/00-setup-status.md) records what has actually been prepared. The [provenance manifest](studies/energy_diagnosis/provenance.json) pins the reviewed and chosen source references. Baseline snapshots of the proposed campaign and complete data contract are in [the starter folder](docs/agent-context/starter/README.md).

First team milestone: one real local-model goal, independently verified, with valid linked CPU/GPU measurements and meaningful candidate controls. Do not launch the full planning matrix automatically.

## Continuous context sharing

The repository-root [agent context md](agent%20context%20md/README.md) contains folders for Stephen, Alex, Aldric and Nitheesh. Agents must read shared context at the start of a turn and autonomously publish their decision/evidence/understanding summary before ending it. Use the supplied publisher to avoid accidentally staging code. Scoped code pushes go to feature branches; code still integrates through review.

For a fresh agent session, use the [named kickoff prompts](agent%20context%20md/KICKOFF_PROMPTS.md). They assign the proposed first tasks for Stephen, Alex, Aldric and Nitheesh and link the human team explanation.

The [dependencies and hardware guide](agent%20context%20md/DEPENDENCIES_AND_HARDWARE.md) explains who can start locally, what each person hands off and what must be ready before Grace integration or a scientific pilot.

Read the [PR and independent-testing workflow](agent%20context%20md/PR_WORKFLOW.md) before implementation: early drafts, branch-local testing, parallel issues, explicit dependencies and Stephen-owned merge decisions.
