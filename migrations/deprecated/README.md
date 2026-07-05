# migrations/deprecated/

## What this directory is

`legacy/` contains every migration file that built the A-LEMS schema
before the current checksummed, set-based migration framework
(scripts/tools/alems_migrate.py) existed. These files are historical
artifacts only. None of them are executed by any current tool.

## Why they are here instead of deleted

Deleting them would remove the only readable record of which change
introduced which table, before the framework existed to track that
properly. Git history alone is harder to search than a real filename
and its content sitting in the repo. Keep them for provenance lookup.

## Why they will never run again

On 2026-07-05, the live schema on three independent machines, GN100,
UBUNTU2505 (core schema, excluding 27 tables created by a Directus
instance that has only ever pointed at UBUNTU2505, not part of A-LEMS
core), and a completely fresh machine built purely by
core/database/schema.py's create_tables(), were directly compared,
table by table. All three produced an identical set of 100 tables, zero
differences. create_tables() is the confirmed, current, cross platform
source of structural truth. Replaying these ~76 files individually would
only reproduce something that already exists correctly.

See migrations/schema/v9000_baseline_adoption.sql for the full
reasoning behind treating this as the framework's starting point rather
than reconstructing history migration by migration.

## If you're looking for where a table came from

Grep this directory by table name, then check `git log` or `git blame`
on the matching file for the original commit and its context. That is
the real provenance record, not migration_history, which only begins
tracking from v9000 onward.

## Important, do not run these directly

Several files in `legacy/` use PostgreSQL syntax (BIGSERIAL,
DEFAULT NOW(), etc) mixed with SQLite-targeted files in the same old
directory. Running one of the PostgreSQL-flavored files against SQLite
via `sqlite3 file.sql <` will fail. This was true before this cleanup
too, it is not a regression, just now clearly labeled instead of
silently mixed in with everything else.

## Seed data that was still needed

Two files' seed data was still required going forward, since
create_tables() only builds empty table structure, it does not insert
rows. That content was extracted, verified against real live data on
GN100 and UBUNTU2505 first, and split into the current framework:
- migrations/seed/s001_energy_sources.sql
- migrations/seed/s002_energy_domains.sql

Their original combined DDL+seed source files, v49_energy_sources.sql
and v50_energy_domains.sql, are preserved unchanged in this directory
alongside everything else, for reference only.
