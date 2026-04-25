# A-LEMS Agent NFR — Quick Reference
**Read before touching any file. No exceptions.**

---

## Work Style
- Grep before writing — never assume file contents
- Surgical only — find-replace docs, never rewrite whole files
- Low token — 2-3 line greps, not cat of full files
- One question at a time — never ask multiple questions in one message
- No inline code — always produce files
- No chunk/internal names in any file going to platform

## File Operations
- Always `cp` to platform path first, then run from platform
- SQL migrations: `cp` to `scripts/migrations/` then `sqlite3 db < migration.sql`
- Git tracks platform repo — Downloads folder is staging only
- New ETL scripts: `cp` to `scripts/etl/`
- New docs: `cp` to `docs-src/mkdocs/source/research/`
- New YAMLs: `cp` to `config/methodology_refs/`
- New platform modules: `cp` to correct `core/` path

## Code Quality
- 30% inline comments — explain WHY not WHAT
- Docstring on every method
- No print statements — use `logger.debug/info/warning`
- Early return pattern — no deep nesting
- Max 50 lines per function
- No hardcoded paths or thresholds — use named constants with method version comment

## Schema Rules
- Every new table → constant in `schema.py` with description comment on top
- Every constant → imported and called in `sqlite_adapter.py create_tables()`
- Every view → separate constant, never bundled
- Every migration → `cp` to `scripts/migrations/` before running
- Never DROP or RENAME columns
- After every migration: `PRAGMA foreign_key_check;` + `PRAGMA integrity_check;`

## Provenance Rules
- Every new column → one line in `COLUMN_PROVENANCE`
- Every new method → one line in `METHOD_CONFIDENCE`
- Every new method → entry in `seed_methodology.py`
- Every new method → YAML in `config/methodology_refs/`
- Every new method → section in mkdocs doc
- Every new doc → entry in `mkdocs.yml`
- After every change: `bash scripts/test_provenance.sh` must pass

## ETL Rules
- All ETL is sync — no async, no threading
- Every ETL: `process_one(id, conn)` + `backfill_all(db_path)` functions
- Every ETL: `--backfill-all` CLI flag
- ETL columns insert as NULL at run time — UPDATE not INSERT
- Idempotent — safe to rerun
- Always validate invariants before computing — log and skip on violation, never corrupt

## Energy Units
- All energy: REAL in µJ
- All timestamps: UTC
- All durations: ns for precision, ms for human-readable
- NULL = not yet computed, 0 = computed and is zero

## Naming
- No chunk/internal reference names in any platform file
- Method IDs: `meaningful_name_v1` — bump to v2 when logic changes
- ETL scripts: named after what they compute, not which chunk created them
- Constants: named after what they create, not implementation scope

## Integrity Check
- Run `python scripts/test_exp_integrity.py --latest` after every save-db run
- 0 failed required before handoff
- New runtime tables → add check to test_exp_integrity.py
