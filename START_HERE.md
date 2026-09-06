# Start here: A-LEMS energy diagnosis

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

This is the team's private development repository, based on A-LEMS. The research method and experiments remain to be implemented and validated. GPU access is team-reported; telemetry, individual accounts and isolation require preflight.

## Pick your starting point

| Person | Read | Work area | First issue |
|---|---|---|---|
| Stephen | [Method and integration](docs/agent-context/09-stephen-method-integration.md) | Shared interfaces and `studies/energy_diagnosis/analysis/` | ED-01, then ED-10 |
| Runtime/measurement student | [Assignment](docs/agent-context/06-student-runtime-measurement.md) | Existing adapters/readers/harness; `studies/energy_diagnosis/runtime/` | ED-02 |
| Workloads/verifiers student | [Assignment](docs/agent-context/07-student-workloads-verifiers.md) | `studies/energy_diagnosis/workloads/` | ED-03 |
| Campaign student | [Assignment](docs/agent-context/08-student-campaign-reproducibility.md) | `studies/energy_diagnosis/campaign/` | ED-04 |

Use the [issue tracker](https://github.com/stephen122204/alems-energy-diagnosis/issues). Student names and accounts are not assigned yet; roles identify the work in the meantime.

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

