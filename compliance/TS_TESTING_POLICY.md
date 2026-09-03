# TS_TESTING_POLICY.md
# Rule family: TS — Test Strategy
# Location: alems-platform/compliance/TS_TESTING_POLICY.md
# Full strategy and tier definitions: alems-test-framework/TESTING_STRATEGY.md
# Read this when: opening a PR, writing a new hardware config, writing a new
# function that can return None, or running a pre-prod promotion.

---

## TS-1 — Hardware column mapping coverage

Every new hardware column mapping added to any config file must have a
corresponding Tier B capability profile entry in
`alems-test-framework/configs/machines/` for every machine that uses
that mapping.
A PR to `integration` is blocked until all profile entries are committed
to `alems-test-framework`.

## TS-2 — None-path test coverage

Every function that can legitimately return `None` must have a Tier A
pytest test covering the None-path at every call site.
A PR to `integration` is blocked until the test exists and passes in CI.

## TS-3 — CI before human review

Tier A (pytest `checks/tier_a/`) must pass in GitHub Actions before any
PR to `integration` receives a human review.
Reviewer time is not spent on code that fails automated checks.

## TS-4 — Tier B and C results required before pre-prod merge

Tier B and Tier C results for all target machines must be posted as PR
comments before any `integration`-to-`pre-prod` merge is approved.
Required comment format: machine ID, pass/fail, timestamp, log tail on failure.

## TS-5 — Promotion gate: pre-prod to main

Promotion from `pre-prod` to `main` requires one successful full experiment
run on each target machine with `test_exp_integrity.py --latest` returning
exit 0 on all machines.
Promotion is run-based. Calendar soak periods are not used.
