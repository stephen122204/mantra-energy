# ENV_POLICY.md
# Rule family: ENV — Environment Isolation
# Location: alems-platform/compliance/ENV_POLICY.md
# Read this when: setting up a new machine, switching environments,
# running experiments, or modifying path_loader.py.

---

## ENV-1 — Four environments, one machine

Every physical machine running A-LEMS maintains four isolated environments.
Each environment has its own database and log directory.
No environment shares data with another.

```
/mnt/alems-data/<machine-id>/envs/
  dev/
    experiments.db
    logs/
    sandbox/
  test/
    experiments.db
    logs/
  preprod/
    experiments.db
    logs/
  prod/
    experiments.db
    logs/
```

## ENV-2 — ALEMS_ENV controls active environment

The environment variable `ALEMS_ENV` determines which database and log
path `path_loader.py` resolves.
Valid values: `dev`, `test`, `preprod`, `prod`.
Default when unset: `prod`.

The default is intentional. An unset environment variable means production.
This prevents accidental writes to dev or test from an unconfigured shell.

## ENV-3 — Environment switching

Switch environments by setting `ALEMS_ENV` before running any script.

```bash
# Switch to dev
export ALEMS_ENV=dev

# Confirm active environment
echo $ALEMS_ENV

# Run any script — it will resolve the dev DB automatically
python scripts/test_exp_integrity.py --latest
```

Recommended shell aliases (add to `~/.bashrc` or `~/.zshrc` on each machine):

```bash
alias alems-dev='export ALEMS_ENV=dev && echo "Active: dev"'
alias alems-test='export ALEMS_ENV=test && echo "Active: test"'
alias alems-preprod='export ALEMS_ENV=preprod && echo "Active: preprod"'
alias alems-prod='export ALEMS_ENV=prod && echo "Active: prod"'
alias alems-env='echo "Active environment: ${ALEMS_ENV:-prod (default)}"'
```

## ENV-4 — path_loader.py contract

`path_loader.py` must:
- Read `ALEMS_ENV` from the environment.
- Resolve the DB path as `/mnt/alems-data/<machine-id>/envs/<ALEMS_ENV>/experiments.db`.
- Default to `prod` if `ALEMS_ENV` is unset or empty.
- Raise a named error (`UnknownEnvironmentError`) if `ALEMS_ENV` is set to
  an unrecognized value. Never silently fall back to prod on an invalid value.

## ENV-5 — Branch to environment mapping

Each git branch corresponds to one environment.
Experiments and test runs execute against the environment that matches
the currently checked-out branch.

| Branch | Environment | DB |
|---|---|---|
| `dev/<name>` | `dev` | envs/dev/experiments.db |
| `integration` | `test` | envs/test/experiments.db |
| `pre-prod` | `preprod` | envs/preprod/experiments.db |
| `main` | `prod` | envs/prod/experiments.db |

When checking out a branch, set `ALEMS_ENV` to the corresponding value.
Do not run production experiments on a dev or test branch checkout.
Do not run dev experiments against the prod database.

## ENV-6 — Database provisioning

A new environment DB is provisioned by running the full migration sequence
against an empty database at the environment path.
Do not copy the prod DB to seed dev or test.
Schema must be applied clean from migrations, not from a prod snapshot.
This ensures the migration sequence itself is validated in lower environments
before it reaches prod.

## ENV-7 — Sandbox directory

The `dev` environment includes a `sandbox/` subdirectory for scratch runs,
ad hoc queries, and experimental scripts that are not yet part of any
formal workflow.
Sandbox contents are never committed to any branch.
Add `envs/*/sandbox/` to `.gitignore`.

## ENV-8 — New machine provisioning

When a new physical machine is added to the fleet:
1. Create the full `envs/` directory tree (all four environments).
2. Provision each environment DB by running the migration sequence.
3. Write a capability profile in `alems-test-framework/configs/machines/<machine-id>.yaml`.
4. Run Tier D health check manually to confirm the environment snapshot is clean.
5. Run Tier B checks against the new machine's profile before any experiment data
   is collected on that machine.
No experiment data from an unprovisioned machine is valid.
