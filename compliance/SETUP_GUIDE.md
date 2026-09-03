# SETUP_GUIDE.md
# A-LEMS Environment Setup Guide
# Location: alems-platform/docs/workflow/SETUP_GUIDE.md
# Read this before running any setup script.

---

## Overview

A-LEMS uses four isolated environments. Each environment has its own
code checkout and its own database. No environment shares data with another.

```
Environment    Branch          DB path (on each machine)
───────────────────────────────────────────────────────────────────────
prod           main            $ALEMS_DATA_ROOT/<hostname>/envs/prod/experiments.db
preprod        pre-prod        $ALEMS_DATA_ROOT/<hostname>/envs/preprod/experiments.db
integration    integration     $ALEMS_DATA_ROOT/<hostname>/envs/integration/experiments.db
dev            dev/<name>      $ALEMS_DATA_ROOT/<hostname>/envs/dev/experiments.db
```

The active environment is controlled by a `.alems-env` file in each checkout.
The file contains a single word: `dev`, `integration`, `preprod`, or `prod`.
This file is never committed to git.

---

## Who runs which setup script

| Machine | Script | Role |
|---------|--------|------|
| GN100 (primary) | `setup_gn100.sh` | Creates all branches, worktrees, all environments |
| Other machines | `setup_machine.sh --role developer --name <name>` | Dev checkout only |
| Tester machines | `setup_machine.sh --role tester` | Integration checkout only |

Run `setup_gn100.sh` first. All other machines depend on branches that
GN100 creates and pushes to GitHub.

---

## Before running setup_gn100.sh

Confirm all of the following:

```bash
# 1. Both repos are on main and up to date
cd ~/mydrive/alems-platform && git branch --show-current && git status
cd ~/mydrive/alems-test-framework && git branch --show-current && git status

# 2. Prod DB exists
ls -la /mnt/alems-data/gn100-2b96/experiments.db

# 3. Data drive is mounted
df -h /mnt/alems-data

# 4. GitHub remote is correct
cd ~/mydrive/alems-platform && git remote -v
# Expected: origin https://github.com/deepakpanigrahy03/alems-platform.git

# 5. You are authenticated with GitHub
ssh -T git@github.com
# or: gh auth status
```

Only when all five checks pass: run the script.

```bash
bash setup_gn100.sh
```

---

## After running setup_gn100.sh

```bash
# 1. Reload shell config
source ~/.bashrc

# 2. Verify prompt changes when you cd into a checkout
cd ~/mydrive/alems-platform-dev
# Prompt should show: [alems:dev] dpani@gn100-2b96:...

# 3. Verify DB resolution
alems-git status
# DB path should show envs/dev/experiments.db

# 4. Provision dev and integration DBs (replace with actual migration script)
cd ~/mydrive/alems-platform-dev
python3 scripts/<migration_script>.py

cd ~/mydrive/alems-platform-int
python3 scripts/<migration_script>.py

# 5. Set GitHub branch protection rules (see section below)
```

---

## GitHub branch protection rules

Set these in GitHub UI: Settings → Branches → Add branch protection rule.
Apply to both `alems-platform` and `alems-test-framework`.

### main
- Require a pull request before merging: YES
- Required approvals: 1
- Require status checks to pass: YES
- Do not allow bypassing: YES
- Restrict who can push: your GitHub username only

### pre-prod (alems-platform only)
- Require a pull request before merging: YES
- Required approvals: 1
- Do not allow bypassing: YES
- Restrict who can push: your GitHub username only

### integration (alems-platform only)
- Require a pull request before merging: YES
- Required approvals: 1
- Require status checks to pass: YES (Tier A workflow)
- Do not allow bypassing: YES
- Restrict who can push: your GitHub username only

After setting these, developers can only push to `dev/<name>`.
They cannot push directly to integration, pre-prod, or main.

---

## Before running setup_machine.sh (on other machines)

```bash
# 1. Confirm setup_gn100.sh has already run and pushed branches
# Visit https://github.com/deepakpanigrahy03/alems-platform/branches
# You should see: main, integration, pre-prod, dev/dpani

# 2. Confirm git is installed
git --version

# 3. Confirm Python 3.11+ is installed
python3 --version

# 4. Confirm the data drive path (may differ per machine)
# Edit DATA_ROOT in setup_machine.sh if /mnt/alems-data does not exist
```

---

## Daily workflow

### As the primary developer (GN100)

```bash
# Start work
cd ~/mydrive/alems-platform-dev     # [alems:dev] prompt
alems-git sync                      # pull latest dev branch
alems-git status                    # confirm env and DB

# Code, test, commit normally
git add -p
git commit -m "your message"

# When ready to submit for review
alems-git submit
# Prints PR URL with commit hash — open in browser and create PR
```

### As a developer (any machine)

```bash
cd ~/mydrive/alems-platform-dev     # [alems:dev] prompt
alems-git sync                      # pull latest
# Code, commit
alems-git submit                    # push and get PR URL
```

### As a tester (any machine)

```bash
# When a PR to integration is ready for Tier B1 testing
cd ~/mydrive/alems-platform-int     # [alems:integration] prompt
alems-git sync                      # pull integration branch
alems-git status                    # confirm branch and DB exist

# Run Tier B1
alems-git b1 --machine <your-hostname>
# Produces: reports/b1/<hostname>/<commit>_<timestamp>.json

# Attach the JSON file as a comment on the GitHub PR
# The commit hash in the report must match the PR head commit
```

---

## How the test framework connects to experiments

The test framework (`alems-test-framework`) lives as a git submodule inside
`alems-platform` at `vendor/alems-test-framework`.

When a tester runs `alems-git b1`, it calls
`vendor/alems-test-framework/checks/tier_b1/run_b1.py` from inside the
current platform checkout.

The B1 checks:
1. Read the machine capability profile from `configs/machines/<hostname>.yaml`
2. Run live hardware checks (turbostat, sysfs, RAPL, DCGM as applicable)
3. Optionally read the integration DB for structural validation
4. Produce a JSON report

The tester does not manage the test framework repo directly.
It is versioned and pinned by the submodule. `alems-git sync` keeps it current.

---

## Environment DB provisioning

Each environment DB is provisioned by running the migration stack from scratch
against an empty SQLite file. Never copy the prod DB to seed another environment.

```bash
# On GN100, after setup_gn100.sh:
cd ~/mydrive/alems-platform-dev
# Confirm DB path:
python3 -c "import sys; sys.path.insert(0,'.'); from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())"
# Then migrate:
python3 scripts/<migration_script>.py

# Repeat for integration:
cd ~/mydrive/alems-platform-int
python3 scripts/<migration_script>.py
```

On other machines, each role provisions only its own environment DB.

---

## Troubleshooting

**Prompt does not show [alems:...]**
```bash
source ~/.bashrc
# If still missing, confirm PROMPT_COMMAND is set:
echo $PROMPT_COMMAND
```

**alems-git not found**
```bash
source ~/.bashrc
# Confirm ~/bin is in PATH:
echo $PATH | grep bin
# If not: export PATH="$HOME/bin:$PATH"
```

**DB path resolves to wrong environment**
```bash
cat .alems-env                    # confirm the file exists and has correct value
alems-git status                  # shows resolved DB path
```

**Wrong branch in checkout**
```bash
git branch --show-current         # confirm branch
# If wrong: this should not happen with worktrees
# Each worktree is permanently bound to one branch
```

**Tier B1 lock held**
```bash
alems-git status                  # shows lock state and PID
ps aux | grep <pid>               # check if process is still running
# If process is dead: rm /tmp/alems-tier-b.lock
```

**Submodule out of date**
```bash
alems-git sync                    # pulls branch and updates submodule
```

---

## What is NOT set up by these scripts

The following items require manual action or are part of the build plan:

- GitHub branch protection rules (manual, in browser)
- Machine capability profiles (`configs/machines/<hostname>.yaml`) — build plan Day 3
- Tier A checks (`checks/tier_a/`) — build plan Days 1-2
- Tier B1 checks (`checks/tier_b1/`) — build plan Day 3
- Tier D cron job — add manually using `checks/tier_d/cron_template.sh`
- `~/.alemsrc` on new machines — copy from GN100 and adjust paths
# test PR process Thu Sep  3 12:02:40 PM CDT 2026
