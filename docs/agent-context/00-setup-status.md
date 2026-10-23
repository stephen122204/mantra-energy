# Actual repository setup — 5 September 2026

This file supersedes the handoff's earlier instructions to create the repository. It records the bootstrap, not scientific implementation or hardware validation.

## Team repository and source

- Repository: [stephen122204/alems-energy-diagnosis](https://github.com/stephen122204/alems-energy-diagnosis), **private**.
- This is a history-preserving research copy with an upstream remote, not a native GitHub fork. The upstream repository is public; its native forks must be public.
- Default/integration branch: `main`.
- `main` retains chosen upstream commit `a67d6583ca2a5ff484e4706284c7b7ce512ef6a0`.
- Reviewed source: `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`. The chosen commit adds one AMD hwmon package-temperature fallback fix in `scripts/detect_hardware.py`; reviewed core files are unchanged.
- Baseline tag: `upstream-baseline-2026-09-05`.
- Bootstrap tag: `study-bootstrap-v0.1`.
- Local clone on Stephen's computer: directory `alems-energy-diagnosis` inside the exploration workspace. Student clones should use their own paths.

## Bootstrap branch inventory (historical names)

| Role | Starting branch | First issue |
|---|---|---|
| Alex: runtime/measurement | `student1/runtime-measurement` | ED-02 |
| Aldric: workloads/verifiers | `student2/workloads-verifiers` | ED-03 |
| Nitheesh: campaign/reproducibility | `student3/campaign-runner` | ED-04 |
| Stephen | `lead/diagnostic-method` | ED-01; later ED-10 |

These numbered branches are existing bootstrap references, retained without renaming or deleting them. New work uses named issue branches from current integration: `alex/ed-02-local-runtime`, `aldric/ed-03-goal-verifier`, and `nitheesh/ed-04-run-ledger`. Role branches start at the common bootstrap. Use separate issue branches and PRs against integration as work progresses. Student usernames were not supplied, so no student invitations or personal issue assignments have been made. Stephen owns the lead issues and initial CODEOWNERS review responsibility. Hardware accounts, reservation budgets and student access remain ED-12.

Directories under `studies/energy_diagnosis/` reserve runtime, workloads, campaign, analysis and small-fixture work areas. They contain ownership/readme scaffolding, not functioning implementations. Do not duplicate the starter manifest or invent module APIs before ED-01's interface review.

## Review settings and validation

- Issues enabled; three milestones: Engineering pilot, Integration validation, Frozen evaluation.
- PR/issue templates and root AGENTS.md installed. CODEOWNERS names Stephen.
- Lightweight GitHub Actions check: `Energy diagnosis setup` / `handoff-and-plan`.
- The initial setup check passed locally and on GitHub: [bootstrap CI run](https://github.com/stephen122204/alems-energy-diagnosis/actions/runs/33990372326).
- Checks cover portable context links, provenance and planning output/readiness integrity. They run no model, paid API call, GPU job or upstream runtime suite.
- **Branch protection is not enabled.** GitHub returned HTTP 403: “Upgrade to GitHub Pro or make this repository public to enable this feature.” The repository remains private. Required approval/status enforcement cannot be assumed; students must follow the documented PR review process. No subscription change was made.
- Merge review is assigned to Stephen by process. Auto-delete after PR merge is enabled; create issue branches so persistent role branches need not be used as PR heads.

## Work tracker

| Issue | Deliverable | Owner role |
|---|---|---|
| [ED-01](https://github.com/stephen122204/alems-energy-diagnosis/issues/1) | Confirm baseline and freeze v0 component interfaces | lead |
| [ED-02](https://github.com/stephen122204/alems-energy-diagnosis/issues/2) | Reproduce and repair local provider response and timing | runtime |
| [ED-03](https://github.com/stephen122204/alems-energy-diagnosis/issues/3) | Build the first data goal and independent verifier | workloads |
| [ED-04](https://github.com/stephen122204/alems-energy-diagnosis/issues/4) | Implement the resumable fixture execution ledger | campaign |
| [ED-05](https://github.com/stephen122204/alems-energy-diagnosis/issues/5) | Validate Grace telemetry and measurement endpoints | runtime |
| [ED-06](https://github.com/stephen122204/alems-energy-diagnosis/issues/6) | Implement four tool controls and bounded dependency execution | workloads |
| [ED-07](https://github.com/stephen122204/alems-energy-diagnosis/issues/7) | Integrate one fully measured and verified Grace goal | integration |
| [ED-08](https://github.com/stephen122204/alems-energy-diagnosis/issues/8) | Add the repository family and four pilot goal assets | workloads |
| [ED-09](https://github.com/stephen122204/alems-energy-diagnosis/issues/9) | Execute and validate the bounded pilot campaign | campaign |
| [ED-10](https://github.com/stephen122204/alems-energy-diagnosis/issues/10) | Validate the supplied policy integration | lead |
| [ED-11](https://github.com/stephen122204/alems-energy-diagnosis/issues/11) | Freeze the held-out selection and evaluation boundary | lead |
| [ED-12](https://github.com/stephen122204/alems-energy-diagnosis/issues/12) | Assign individual accounts, student roles and a pilot session | lead |

## What Stephen needs to do next

1. Confirm Alex's, Aldric's and Nitheesh's GitHub usernames and grant intended repository access. Their named work areas are assigned; names alone do not grant permissions.
2. Review ED-01's exact shared interface and current local-model environment with the team. Baseline selection is prepared; runtime functionality is not asserted.
3. Establish individual HPRC accounts/allocation assignments and a scheduled capability session with Alex/Dr. Tyagi. An award or issue does not reserve GPU time.
4. Let Alex, Aldric and Nitheesh start ED-02/03/04 locally. Keep the research method/evaluation decisions with Stephen.

No cluster workload, model download, hardware setting change or mailbox mutation was performed during repository setup. No experiment result or acceptance claim is supplied.

