# Set up the shared repository before implementation

**Repository setup is now complete:** read [00-setup-status.md](00-setup-status.md) for the actual repository, baseline, branches, issues and remaining access tasks. The setup instructions below are retained as rationale and future reference.

## Recommendation

Use one team research repository with Stephen maintaining the integration branch. Give each student a feature branch and an issue. Do not start with three divergent platform forks.

For unpublished work, a private research repository containing the permitted A-LEMS source/history is a practical default. A native public GitHub fork stays public; it cannot independently become private. If public development is intended, one team fork is fine. A separate public fork can later carry selected general-purpose fixes upstream. These are different publication choices, not technical requirements of the experiment. [GitHub fork visibility](https://docs.github.com/en/pull-requests/reference/forks)

The reviewed upstream root LICENSE is MIT. Preserve its license and copyright notices; inspect dependency, model and dataset licenses separately. Do not import Stephen's entire exploration folder: it includes unrelated research and private evidence. This pack contains curated context only.

## Stephen's preparation checklist

1. With Deepak, identify the actual working execution revision and environment. Compare it with reviewed commit `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`. Choose and record a baseline; do not force the older review revision if important fixes already exist.
2. Create the intended repository in the correct user/organization namespace and select its visibility. No destination owner or repository has been created by this pack.
3. Seed it from a fresh upstream checkout with history and license preserved. Avoid a mirror push, which can publish unrelated refs. Inspect tracked files/history for material that does not belong in the destination before the first push.
4. Set `origin` to the team repository and `upstream` to `https://github.com/deepakpanigrahy03/alems-platform.git`. Use repository permissions to control upstream writes; merely naming a remote upstream does not make it read-only.
5. Establish `research/energy-diagnosis` as the proposed integration branch, tag the selected baseline, and record the full commit in a provenance file. Branch/tag names here are recommendations, not claims they exist.
6. Add this pack under `docs/agent-context/`; merge its applicable rules into root AGENTS.md without overwriting existing instructions. Fill the team fields below.
7. Add students with the access needed for branches/PRs. Require review before integration where repository settings support it. Stephen owns shared-interface and measurement-boundary changes; do not bypass existing upstream rules.
8. Open the initial issues from 10-first-issues-and-milestones.md. Freeze the v0 interface definitions before students implement dependent components.
9. Configure a local/CI fixture suite with no model downloads, API keys or GPU reservation required. Real hardware checks are a separate, explicitly scheduled tier.

## Safe remote layout example

Run only in a newly created disposable clone after selecting the destination. Replace the placeholders; these commands have not been executed. Verify `git status` and `git remote -v` before adapting them to an existing checkout.

```bash
git clone https://github.com/deepakpanigrahy03/alems-platform.git alems-energy-diagnosis
cd alems-energy-diagnosis
git remote rename origin upstream
git remote add origin TEAM_REPOSITORY_URL
git fetch upstream
git switch -c research/energy-diagnosis CHOSEN_BASELINE_COMMIT
git remote -v
git rev-parse HEAD
```

After reviewing the destination and seed contents, Stephen can make the first push to the team repository. Students then clone that repository and branch from the agreed integration branch. Do not paste the placeholders as real values, share credentials, or have multiple people edit one live cluster checkout.

## Proposed branch ownership

| Owner | Branch prefix | Main change boundary |
|---|---|---|
| Student 1 | `student1/runtime-measurement` | Model adapter, registry override, collectors and preflight |
| Student 2 | `student2/workloads-verifiers` | Task assets, tool controls, verifiers and narrow trace executor |
| Student 3 | `student3/campaign-runner` | Manifest handling, ledger, scheduling, exports and validation |
| Stephen | `lead/diagnostic-method` | Selector, evaluation, common schema/interface integration |

Each person should use separate issue branches when a change is reviewable on its own. Student 1 owns edits to shared harness boundaries initially; others extend through agreed interfaces or coordinate a small PR. Stephen is the merge owner. Rebase/merge upstream intentionally between experiment phases, never silently during a frozen campaign.

## Data and cluster layout

Track code, small synthetic fixtures, manifests, lockfiles and schema versions in Git. Keep weights, credentials, scheduler tokens, full experimental databases and large logs in approved storage. Record content hashes and stable artifact identifiers. Do not commit personal absolute paths as portable configuration. Copy data off ephemeral node storage; one writer per run/database file is simplest initially.

Each student has an individual local checkout and an individually authorized cluster account. Deploy the same frozen commit into separate job working directories. Use a shared reservation calendar; no simultaneous energy experiments on the same measured domains.

## Fill before handoff

```text
Team repository URL: UNSET
Visibility and publication decision: UNSET
Chosen baseline commit: UNSET
Integration branch: research/energy-diagnosis (proposed)
Student 1 / issue / branch: UNSET
Student 2 / issue / branch: UNSET
Student 3 / issue / branch: UNSET
Approved cluster account/allocation for each person: UNSET
Small-job budget and who launches jobs: UNSET
Artifact storage location and access: UNSET
Root instructions merged and interfaces reviewed by: UNSET
```

