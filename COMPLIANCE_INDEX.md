# COMPLIANCE_INDEX.md
# Location: alems-platform/COMPLIANCE_INDEX.md
# Purpose: entry point for all compliance and policy rules.
# Read this first. Open only the satellite document relevant to your task.
# Do not read COMPLIANCE.md end to end — use this index to find what you need.

---

## Rule families and where they live

| Family | Scope | Document |
|---|---|---|
| SC | Schema invariants, column contracts, migration rules | COMPLIANCE.md §SC |
| MPC | Methodology provenance, citation bindings, registry integrity | COMPLIANCE.md §MPC |
| PDS | Documentation standards, handover files, spec naming | COMPLIANCE.md §PDS |
| MSC | Migration sequencing, manifest, rollback | COMPLIANCE.md §MSC |
| PAC | Platform abstraction, backend contracts, ISA portability | COMPLIANCE.md §PAC |
| DC | Code quality, import discipline, error handling | COMPLIANCE.md §DC |
| TS | Test strategy, branch gates, CI, environment isolation | compliance/TS_TESTING_POLICY.md |
| ENV | Environment setup, DB paths, multi-environment isolation | compliance/ENV_POLICY.md |

---

## Which document to open for common tasks

| Task | Read |
|---|---|
| Opening a PR (any change) | TS_TESTING_POLICY.md — confirm TS-1 through TS-3 |
| Adding a new schema column or table | COMPLIANCE.md §SC |
| Adding a new hardware column mapping | TS_TESTING_POLICY.md (TS-1) |
| Writing a function that can return None | TS_TESTING_POLICY.md (TS-2) |
| Running a pre-prod promotion | TS_TESTING_POLICY.md (TS-4, TS-5) |
| Writing or modifying a migration | COMPLIANCE.md §MSC |
| Adding a new measurement backend | COMPLIANCE.md §PAC |
| Setting up a new machine or environment | ENV_POLICY.md |
| Writing a handover or spec document | COMPLIANCE.md §PDS |
| Adding a provenance binding or citation | COMPLIANCE.md §MPC |

---

## Full rule documents

- `COMPLIANCE.md` — primary rule set (SC, MPC, PDS, MSC, PAC, DC families)
- `compliance/TS_TESTING_POLICY.md` — test strategy rules (TS family)
- `compliance/ENV_POLICY.md` — environment isolation rules (ENV family)
- `alems-test-framework/TESTING_STRATEGY.md` — full tier definitions, build
  priority, CI wiring, branch model (read before writing any check or CI spec)
