---
**Document:** MIGRATION_GUIDE.md
**Location:** compliance/MIGRATION_GUIDE.md
**Status:** PRODUCTION
**Last updated:** 2026-08-29
**Applies to:** All platforms — Intel x86 (UBUNTU2505), NVIDIA Grace GB10 (GN100), Apple Silicon (Mac), AMD Ryzen
---

# A-LEMS Migration System Guide

**Every developer and agent must read this before creating or applying any migration.**

---

## 1. Overview

A-LEMS enforces schema consistency across all platforms mechanically via
`scripts/tools/alems_migrate.py`.
This is not a convention.
It is enforced via version tracking, SHA-256 checksums, and gap detection.

The migration system solves a core research integrity problem: when a paper
reports cross-platform queries, every platform the query runs on must have
an identical schema.
Schema drift across platforms produces silent wrong answers that no query
error can detect.
The migration system makes drift mechanically impossible.

This is a first-class architectural contribution of A-LEMS.
CodeCarbon, Scaphandre, PowerAPI, and EnergiBridge have no equivalent
mechanism.
Schema drift across platforms is silent and undetectable in those tools.
In A-LEMS it is prevented by construction and cryptographically verified
via per-file SHA-256 checksums stored in `migration_history`.

---

## 2. Directory Structure

```
migrations/
  schema/           DDL only — ALTER TABLE, CREATE TABLE, CREATE INDEX
  seed/             Data only — INSERT, UPDATE (never DDL)
  platform/         Platform-specific DDL — applies to named platform only
    gn100/
    intel_x86/
    apple_m1/
    amd_x86/
  deprecated/       Legacy series v1-v80 — never touch, never re-apply
    legacy/
  migration_manifest.json   Cross-platform sync artifact — never edit manually
```

---

## 3. Version Series

| Range | Location | Status | Notes |
|-------|----------|--------|-------|
| v001-v048 | deprecated/legacy | DEPRECATED | Pre-production series, never re-apply |
| v049-v081 | migrations/schema/ | PRODUCTION | Current active series |
| v082+ | migrations/schema/ | PRODUCTION | All new migrations go here |
| v9000 | migrations/schema/ | SENTINEL | Marks boundary between deprecated and current series |
| sNNN | migrations/seed/ | PRODUCTION | Seed data, separate numbering |

**Version 9000 is a sentinel.**
It exists solely to mark the boundary between the deprecated legacy series
and the current series.
The migrate tool handles it automatically.
Never create v082 through v8999 gaps intentionally.

---

## 4. How the System Works

### Apply flow (every platform, every new migration)

```
Developer creates migrations/schema/vNNN_description.sql
         ↓
Developer updates core/database/schema.py to match (SC-1, SC-2)
         ↓
Developer runs: python3 scripts/tools/alems_migrate.py
         ↓
Tool reads migration_history to find applied versions
         ↓
Tool discovers repo files via version number glob
         ↓
Tool detects gaps via check_gaps_and_extras() — FATAL if gap found
         ↓
Tool applies pending versions in order inside transactions
         ↓
Tool records version + SHA-256 checksum in migration_history
         ↓
Tool regenerates migration_manifest.json
         ↓
Developer commits migration file + schema.py + manifest
         ↓
Other platforms pull and run: python3 scripts/tools/alems_migrate.py
         ↓
Each platform applies the new version and reaches schema parity
```

### Check flow (verify a platform is current)

```bash
python3 scripts/tools/alems_migrate.py --check
```

Reads `migration_manifest.json` and compares against `migration_history`.
Exits non-zero if any version in the manifest is not applied.
Run this before any experiment sweep on any platform.

### Verify flow (checksum integrity)

```bash
python3 scripts/tools/alems_migrate.py --verify
```

Recomputes SHA-256 of every applied migration file and compares against
stored checksums.
A mismatch means a migration file was edited after application — a
MSC-1 violation.

---

## 5. Rules

### MSC-1: Migration files are immutable after first commit
Every file in `migrations/schema/` and `migrations/seed/` is immutable
after first commit.
Fix forward with a new version number.
Never edit an applied migration file.
Editing a file after application causes `--verify` to flag a checksum
mismatch on every platform that has applied it.

### MSC-2: Always use alems_migrate, never raw sqlite3
```bash
# WRONG — bypasses version tracking and checksum recording
sqlite3 $DB < migrations/schema/v082_foo.sql

# RIGHT — applies with full tracking
python3 scripts/tools/alems_migrate.py
```

Manual application creates silent drift.
`--check` and `--verify` will flag the platform as corrupt.

### MSC-3: Always update schema.py alongside migration file
Every `ALTER TABLE` or `CREATE TABLE` in a migration file MUST have a
matching change in `core/database/schema.py`.
Fresh checkout + `create_tables()` must produce an identical schema to
the production DB on any platform.
This is SC-1 and SC-2 from COMPLIANCE.md.

### MSC-4: Never skip version numbers
`check_gaps_and_extras()` detects gaps in the applied version set below
`MAX(applied)`.
A gap causes a FATAL error that blocks migration on all platforms.
If a version was mistakenly skipped, fix forward by creating the missing
version as a no-op migration.

### MSC-5: Platform-specific DDL goes in migrations/platform/
DDL that applies only to one platform (e.g. power rail tables on GN100)
goes in `migrations/platform/<hostname>/`, not in `migrations/schema/`.
Schema migrations apply to ALL platforms.
Putting platform-specific DDL in schema/ causes failures on platforms
where the hardware does not exist.

### MSC-6: Seed and schema are strictly separated
`migrations/schema/` contains DDL only: `CREATE`, `ALTER`, `DROP`, `CREATE INDEX`.
`migrations/seed/` contains data only: `INSERT`, `UPDATE`, `DELETE`.
A schema file with `INSERT` is a violation.
A seed file with `ALTER TABLE` is a violation.

### MSC-7: migration_manifest.json is the cross-platform sync artifact
The manifest is committed to the repo.
When a new platform clones the repo and runs alems_migrate, it reads the
manifest to discover which versions exist and applies any pending ones.
Never edit `migration_manifest.json` manually.
It is regenerated automatically after every successful apply.

---

## 6. Step-by-Step: Creating a New Migration

```bash
# Step 1: Find the next version number
ls migrations/schema/ | sort | tail -3
# e.g. shows v081_cpu_active_ratio.sql → next is v082

# Step 2: Create the migration file (DDL only)
cat > migrations/schema/v082_description.sql << 'EOF'
-- v082: Short description of what this adds and why
-- Root cause: why this column/table was missing
-- Applies to: ALL platforms
ALTER TABLE some_table ADD COLUMN new_col TYPE;
EOF

# Step 3: Update core/database/schema.py
# Add the matching column to the CREATE TABLE statement for some_table

# Step 4: Apply on current platform
python3 scripts/tools/alems_migrate.py

# Step 5: Verify
python3 scripts/tools/alems_migrate.py --check
python3 scripts/tools/alems_migrate.py --verify

# Step 6: Commit all three files together
git add migrations/schema/v082_description.sql
git add core/database/schema.py
git add migrations/migration_manifest.json
git commit -m "v082: description"

# Step 7: Other platforms pull and apply
git pull
python3 scripts/tools/alems_migrate.py
```

---

## 7. Backfilling Existing Data

When a migration adds a column that should be populated from existing data,
include the `UPDATE` in the migration file itself.
This ensures every platform backfills identically on first apply.

```sql
-- v082: Add interval columns to some_table
ALTER TABLE some_table ADD COLUMN sample_start_ns INTEGER;
ALTER TABLE some_table ADD COLUMN sample_end_ns INTEGER;

-- Backfill existing rows from the runs table
-- NULL values after this UPDATE indicate runs with no timing data (acceptable)
UPDATE some_table
SET sample_start_ns = (SELECT start_time_ns FROM runs WHERE runs.run_id = some_table.run_id),
    sample_end_ns   = (SELECT end_time_ns   FROM runs WHERE runs.run_id = some_table.run_id)
WHERE sample_start_ns IS NULL;
```

---

## 8. Platform Coverage

| Platform | Migration Apply Command | Check Command | Status |
|----------|------------------------|---------------|--------|
| NVIDIA Grace GB10 (GN100, aarch64) | `python3 scripts/tools/alems_migrate.py` | `--check` | VERIFIED |
| Intel i7-1165G7 (UBUNTU2505, x86_64) | same | same | VERIFIED |
| Apple Silicon (Mac, arm64) | same | same | PENDING |
| AMD Ryzen (x86_64) | same | same | PENDING |

The migrate tool is platform-agnostic.
The same command applies on all platforms.
Platform detection is handled by the DB path resolver, not the migrate tool.

---

## 9. Known Limitations

- **No rollback**: SQLite does not support transactional DDL rollback on
  `ALTER TABLE`. Fix forward with a new version. Never delete an applied migration.
- **No central coordinator**: Platforms sync via the committed manifest file.
  If two developers create v082 simultaneously on different branches, the merge
  will conflict on the manifest. Resolve by renaming one to v083.
- **Deprecated series gap**: Versions 1-48 exist in `deprecated/legacy/` and
  are not in `migrations/schema/`. The migrate tool skips the deprecated
  directory. Version 9000 is the sentinel that bridges the gap. Do not create
  migrations between v082 and v8999 that depend on the deprecated series.

---

## 10. Reference to COMPLIANCE.md

This guide covers migration mechanics (Section 16 of COMPLIANCE.md).
For schema naming rules see SC-1 through SC-4 in COMPLIANCE.md.
For methodology registry requirements when adding new measurement columns
see MPC-1 through MPC-6 in COMPLIANCE.md.
For publication-grade documentation of new methods see PDS-1 through PDS-9
in COMPLIANCE.md.
