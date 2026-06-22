#!/usr/bin/env python3
"""
A-LEMS Migration Runner

Implements SPEC_MIGRATION_SYSTEM.md Chunks M1 (runner core) and M2 (safety
gates). SQLite only, set based version tracking, checksum enforced.

Entry point convention matches scripts/tools/path_loader.py.
Usage:
    python3 scripts/tools/alems_migrate.py              # apply pending
    python3 scripts/tools/alems_migrate.py --check       # manifest check
    python3 scripts/tools/alems_migrate.py --verify      # checksum only
    python3 scripts/tools/alems_migrate.py --status      # print history
    python3 scripts/tools/alems_migrate.py --plan        # dry run
    python3 scripts/tools/alems_migrate.py --adopt       # one time adoption
"""

import argparse
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

TOOL_VERSION = "alems-migrate-1.0"

# scripts/tools/alems_migrate.py -> repo root is two parents up
REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
SCHEMA_DIR = MIGRATIONS_DIR / "schema"
SEED_DIR = MIGRATIONS_DIR / "seed"
MANIFEST_PATH = MIGRATIONS_DIR / "migration_manifest.json"
MACHINE_SETUP_ROOT = REPO_ROOT / "scripts" / "machine_setup"
ALEMSRC_PATH = Path.home() / ".alemsrc"


class MigrationError(Exception):
    """Raised for any block condition. main() catches this, prints to
    stderr, and exits 1. Every message includes the fix command per
    spec Section 9, so this is the only error type the CLI surfaces."""
    pass


# ---------------------------------------------------------------------------
# Identity and provenance
# ---------------------------------------------------------------------------

def get_hostname() -> str:
    return socket.gethostname()


def get_machine_id():
    """Reads machine_id from ~/.alemsrc. Returns None gracefully if the
    file or key is absent, supporting early adoption before every machine
    has run setup_new_machine.sh (spec Section 4.3)."""
    if not ALEMSRC_PATH.exists():
        return None
    for line in ALEMSRC_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("machine_id"):
            parts = line.replace(":", "=").split("=", 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"').strip("'")
    return None


def get_repo_commit():
    """git rev-parse HEAD for reproducibility provenance. Returns None on
    failure rather than raising, a missing commit hash should never block
    a migration, only be absent from the record (MSC-2 allows NULL)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return None


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def parse_version(filename: str, prefix: str):
    """Parses the integer version from the filename prefix only (spec
    Section 3). v061_add_nvlink_columns.sql with prefix 'v' returns 61.
    Returns None for non matching files so stray files (README, .gitkeep)
    are skipped instead of crashing the scan."""
    if not filename.endswith(".sql"):
        return None
    if not filename.startswith(prefix):
        return None
    digits = ""
    for ch in filename[len(prefix):]:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    return int(digits)


def discover_repo_files(directory: Path, prefix: str):
    """Scans one migrations subdirectory, returns {version: filepath}.
    Only called by alems migrate itself, the startup check in Section 7
    must never directory scan."""
    result = {}
    if not directory.exists():
        return result
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        version = parse_version(entry.name, prefix)
        if version is None:
            continue
        result[version] = entry
    return result


def discover_machine_setup_files(hostname: str):
    """Machine setup scripts use free naming (spec Section 3) and are
    tracked by filename, not version, since machine_setup_history has
    UNIQUE(filename) rather than UNIQUE(version, type)."""
    host_dir = MACHINE_SETUP_ROOT / hostname
    if not host_dir.exists():
        return []
    return sorted(p for p in host_dir.iterdir() if p.is_file() and p.suffix == ".sql")


# ---------------------------------------------------------------------------
# Table bootstrap
# ---------------------------------------------------------------------------

def ensure_tables(conn: sqlite3.Connection) -> None:
    """Creates migration_history and machine_setup_history if absent.
    Runs outside the per migration transaction model because these two
    tables are the ground truth every later comparison depends on."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS migration_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        version         INTEGER NOT NULL,
        type            TEXT NOT NULL CHECK(type IN ('schema', 'seed')),
        filename        TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        applied_at      TEXT NOT NULL DEFAULT (datetime('now')),
        tool_version    TEXT NOT NULL,
        duration_ms     INTEGER NOT NULL,
        status          TEXT NOT NULL CHECK(status IN ('pending', 'running', 'applied', 'failed')),
        hostname        TEXT NOT NULL,
        machine_id      TEXT,
        repo_commit     TEXT,
        UNIQUE(version, type)
    );

    CREATE TABLE IF NOT EXISTS machine_setup_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        filename        TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        applied_at      TEXT NOT NULL DEFAULT (datetime('now')),
        tool_version    TEXT NOT NULL,
        duration_ms     INTEGER NOT NULL,
        status          TEXT NOT NULL CHECK(status IN ('pending', 'running', 'applied', 'failed')),
        hostname        TEXT NOT NULL,
        machine_id      TEXT,
        repo_commit     TEXT,
        UNIQUE(filename)
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# State queries. Set based only, MAX(version) never appears (Design
# Principle 7).
# ---------------------------------------------------------------------------

def applied_versions(conn: sqlite3.Connection, mtype: str):
    rows = conn.execute(
        "SELECT version FROM migration_history WHERE type=? AND status='applied'",
        [mtype],
    ).fetchall()
    return {r[0] for r in rows}


def running_versions(conn: sqlite3.Connection, mtype: str):
    rows = conn.execute(
        "SELECT version FROM migration_history WHERE type=? AND status='running'",
        [mtype],
    ).fetchall()
    return {r[0] for r in rows}


def applied_checksums(conn: sqlite3.Connection, mtype: str):
    """Returns {version: (filename, checksum)} for every applied record."""
    rows = conn.execute(
        "SELECT version, filename, checksum_sha256 FROM migration_history "
        "WHERE type=? AND status='applied'",
        [mtype],
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def applied_setup_filenames(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT filename, checksum_sha256 FROM machine_setup_history WHERE status='applied'"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Safety gates, Chunk M2
# ---------------------------------------------------------------------------

def verify_checksums(conn: sqlite3.Connection, mtype: str, repo_files: dict):
    """Recomputes SHA256 for every applied migration's on disk file and
    compares to the stored hash. A mismatch means the file changed after
    being applied somewhere, the exact silent divergence scenario this
    gate exists to catch. Returns formatted strings, empty list means
    clean."""
    problems = []
    for version, (filename, stored_hash) in applied_checksums(conn, mtype).items():
        filepath = repo_files.get(version)
        if filepath is None:
            problems.append(
                f"Applied {mtype} version {version} ({filename}) is missing from disk."
            )
            continue
        current_hash = sha256_file(filepath)
        if current_hash != stored_hash:
            problems.append(
                f"Checksum mismatch: {filepath.relative_to(REPO_ROOT)}\n"
                f"  Applied:  sha256:{stored_hash}\n"
                f"  Current:  sha256:{current_hash}"
            )
    return problems


def check_gaps_and_extras(applied: set, repo: set):
    """Full set comparison. A machine with applied {1,2,4} and repo
    {1,2,3,4,5} has a true gap at 3 even though MAX(applied)=4 looks
    almost current. gaps = repo versions missing from applied, below the
    highest applied version. extra = applied versions absent from repo,
    meaning wrong branch or stale data."""
    missing = repo - applied
    gaps = set()
    if applied and missing:
        max_applied = max(applied)
        gaps = {v for v in missing if v < max_applied}
    extra = applied - repo
    return gaps, extra


# ---------------------------------------------------------------------------
# Migration application, Chunk M1 core
# ---------------------------------------------------------------------------

def apply_one(conn, filepath: Path, version: int, mtype: str,
              hostname: str, machine_id, commit):
    """Applies one schema or seed migration inside one BEGIN IMMEDIATE
    transaction (Design Principle 9). BEGIN IMMEDIATE also serves as the
    cross process migration lock, a second concurrent run blocks here
    until this one commits or rolls back."""
    checksum = sha256_file(filepath)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO migration_history "
        "(version, type, filename, checksum_sha256, tool_version, duration_ms, "
        " status, hostname, machine_id, repo_commit) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [version, mtype, filepath.name, checksum, TOOL_VERSION, 0,
         "running", hostname, machine_id, commit],
    )
    record_id = cur.lastrowid
    # commit the running marker before the migration transaction starts,
    # so a crash mid migration is visibly distinguishable on restart
    conn.commit()

    start = time.monotonic_ns()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(filepath.read_text())
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        conn.execute(
            "UPDATE migration_history SET status='applied', duration_ms=? WHERE id=?",
            [duration_ms, record_id],
        )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        conn.execute(
            "UPDATE migration_history SET status='failed', duration_ms=? WHERE id=?",
            [duration_ms, record_id],
        )
        conn.commit()
        raise MigrationError(f"Migration {filepath.name} failed: {e}") from e


def apply_machine_setup(conn, filepath: Path, hostname: str, machine_id, commit):
    """Same transaction pattern as apply_one, keyed by filename instead
    of version since machine setup scripts are not sequentially ordered
    relative to each other."""
    checksum = sha256_file(filepath)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO machine_setup_history "
        "(filename, checksum_sha256, tool_version, duration_ms, status, "
        " hostname, machine_id, repo_commit) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [filepath.name, checksum, TOOL_VERSION, 0, "running", hostname, machine_id, commit],
    )
    record_id = cur.lastrowid
    conn.commit()

    start = time.monotonic_ns()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(filepath.read_text())
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        conn.execute(
            "UPDATE machine_setup_history SET status='applied', duration_ms=? WHERE id=?",
            [duration_ms, record_id],
        )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        conn.execute(
            "UPDATE machine_setup_history SET status='failed', duration_ms=? WHERE id=?",
            [duration_ms, record_id],
        )
        conn.commit()
        raise MigrationError(f"Machine setup {filepath.name} failed: {e}") from e


# ---------------------------------------------------------------------------
# Manifest, Section 6
# ---------------------------------------------------------------------------

def generate_manifest(conn, hostname: str) -> None:
    """Regenerates migration_manifest.json from migration_history after
    every successful run. Data, not code, the experiment runner's startup
    check reads this file only, never scans directories or imports
    Python (Design Principle 10)."""
    schema_versions = sorted(applied_versions(conn, "schema"))
    seed_versions = sorted(applied_versions(conn, "seed"))
    manifest = {
        "schema_versions": schema_versions,
        "seed_versions": seed_versions,
        "tool_version": TOOL_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generated_by": hostname,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=4) + "\n")


# ---------------------------------------------------------------------------
# Shared preflight, spec Section 5.5 steps 3 through 5
# ---------------------------------------------------------------------------

def preflight(conn, mtype: str, repo_files: dict):
    """Runs the interrupted check, checksum verification, and set
    comparison for one migration type. Raises MigrationError on any
    block condition. Returns the sorted list of pending versions on
    success."""
    interrupted = running_versions(conn, mtype)
    if interrupted:
        raise MigrationError(
            f"Interrupted {mtype} migration detected: {sorted(interrupted)}\n"
            f"A previous run was interrupted (power loss or crash).\n"
            f"Inspect the database manually and resolve before proceeding."
        )

    problems = verify_checksums(conn, mtype, repo_files)
    if problems:
        raise MigrationError(
            "FATAL: Migration checksum mismatch.\n\n" + "\n\n".join(problems) +
            "\n\nApplied migration differs from repository version. Refusing to "
            "continue.\nFix: revert the file change, or create a new migration "
            "to apply the correction as the next version."
        )

    applied = applied_versions(conn, mtype)
    repo = set(repo_files.keys())
    gaps, extra = check_gaps_and_extras(applied, repo)
    if gaps:
        raise MigrationError(
            f"Migration gap detected ({mtype}).\n"
            f"  Applied: {sorted(applied)}\n"
            f"  Missing: {sorted(gaps)}\n"
            f"Cannot proceed with gaps in migration history."
        )
    if extra:
        raise MigrationError(
            f"Applied {mtype} migrations not found in repository: {sorted(extra)}\n"
            f"This machine has migrations from a different branch.\n"
            f"Check your branch and pull latest code."
        )

    return sorted(repo - applied)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_migrate(conn, hostname: str, machine_id, commit) -> None:
    ensure_tables(conn)
    schema_files = discover_repo_files(SCHEMA_DIR, "v")
    seed_files = discover_repo_files(SEED_DIR, "s")

    pending_schema = preflight(conn, "schema", schema_files)
    for version in pending_schema:
        apply_one(conn, schema_files[version], version, "schema", hostname, machine_id, commit)
        print(f"Applied schema {schema_files[version].name}")

    pending_seed = preflight(conn, "seed", seed_files)
    for version in pending_seed:
        apply_one(conn, seed_files[version], version, "seed", hostname, machine_id, commit)
        print(f"Applied seed {seed_files[version].name}")

    applied_setup = applied_setup_filenames(conn)
    setup_files = discover_machine_setup_files(hostname)
    pending_setup = [f for f in setup_files if f.name not in applied_setup]
    for filepath in pending_setup:
        apply_machine_setup(conn, filepath, hostname, machine_id, commit)
        print(f"Applied machine setup {filepath.name}")

    generate_manifest(conn, hostname)
    print(
        f"\nTotal applied: {len(pending_schema)} schema, {len(pending_seed)} seed, "
        f"{len(pending_setup)} machine setup."
    )


def cmd_check(conn) -> int:
    """Manifest only comparison, no directory scan, this is the cheap
    startup gate from Section 7. Returns 0 if compatible, 1 otherwise."""
    if not MANIFEST_PATH.exists():
        print("FATAL: migration_manifest.json not found. Run: alems migrate")
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    expected_schema = set(manifest["schema_versions"])
    expected_seed = set(manifest["seed_versions"])
    actual_schema = applied_versions(conn, "schema")
    actual_seed = applied_versions(conn, "seed")

    ok = True
    if actual_schema != expected_schema:
        ok = False
        missing = expected_schema - actual_schema
        extra = actual_schema - expected_schema
        if missing:
            print(f"Database behind code. Missing schema versions: {sorted(missing)}.\nRun: alems migrate")
        if extra:
            print(f"Database ahead of code. Extra schema versions: {sorted(extra)}.\nPull latest code or check your branch.")
    if actual_seed != expected_seed:
        ok = False
        missing = expected_seed - actual_seed
        extra = actual_seed - expected_seed
        if missing:
            print(f"Database behind code. Missing seed versions: {sorted(missing)}.\nRun: alems migrate")
        if extra:
            print(f"Database ahead of code. Extra seed versions: {sorted(extra)}.\nPull latest code or check your branch.")

    if ok:
        print("Schema compatible.")
    return 0 if ok else 1


def cmd_verify(conn) -> int:
    """Checksum verification only, no new migrations applied."""
    ensure_tables(conn)
    schema_files = discover_repo_files(SCHEMA_DIR, "v")
    seed_files = discover_repo_files(SEED_DIR, "s")
    problems = verify_checksums(conn, "schema", schema_files) + verify_checksums(conn, "seed", seed_files)
    if problems:
        print("FATAL: Migration checksum mismatch.\n")
        print("\n\n".join(problems))
        return 1
    print("All checksums verified clean.")
    return 0


def cmd_status(conn) -> None:
    ensure_tables(conn)
    print("=== migration_history ===")
    rows = conn.execute(
        "SELECT id, version, type, filename, status, applied_at, hostname, duration_ms "
        "FROM migration_history ORDER BY type, version"
    ).fetchall()
    for r in rows:
        print(f"  [{r[2]:6s}] v{r[1]:<4} {r[3]:<40} {r[4]:<8} {r[5]} {r[6]} {r[7]}ms")
    print("\n=== machine_setup_history ===")
    rows = conn.execute(
        "SELECT id, filename, status, applied_at, hostname, duration_ms "
        "FROM machine_setup_history ORDER BY applied_at"
    ).fetchall()
    for r in rows:
        print(f"  {r[1]:<40} {r[2]:<8} {r[3]} {r[4]} {r[5]}ms")


def cmd_plan(conn, hostname: str) -> None:
    ensure_tables(conn)
    schema_files = discover_repo_files(SCHEMA_DIR, "v")
    seed_files = discover_repo_files(SEED_DIR, "s")

    pending_schema = preflight(conn, "schema", schema_files)
    pending_seed = preflight(conn, "seed", seed_files)

    applied_setup = applied_setup_filenames(conn)
    setup_files = discover_machine_setup_files(hostname)
    pending_setup = [f for f in setup_files if f.name not in applied_setup]

    print("Pending schema migrations:")
    for v in pending_schema:
        print(f"  {schema_files[v].name}")
    if not pending_schema:
        print("  (none)")

    print("\nPending seed migrations:")
    for v in pending_seed:
        print(f"  {seed_files[v].name}")
    if not pending_seed:
        print("  (none)")

    print(f"\nPending machine setup ({hostname}):")
    for f in pending_setup:
        print(f"  {f.name}")
    if not pending_setup:
        print("  (none)")

    total = len(pending_schema) + len(pending_seed) + len(pending_setup)
    print(f"\nTotal: {total} migrations to apply.")
    if total:
        print("Run 'alems migrate' to execute.")


def cmd_adopt(conn, hostname: str, machine_id, commit) -> None:
    """One time explicit adoption for UBUNTU2505 and GN100, spec Section
    8.2/8.3. No auto detection, every file currently in schema/ and
    seed/ is marked applied as is. This assumes schema_version on this
    machine already reflects every file in those directories, true for
    both production machines per spec Section 8.3. Verify file count
    against schema_version before running this if in doubt."""
    ensure_tables(conn)
    schema_files = discover_repo_files(SCHEMA_DIR, "v")
    seed_files = discover_repo_files(SEED_DIR, "s")

    already = applied_versions(conn, "schema") | applied_versions(conn, "seed")
    if already:
        raise MigrationError(
            "migration_history already has applied records. --adopt is for a "
            "one time transition from schema_version only. Refusing to run "
            "again, use 'alems migrate' for normal operation."
        )

    for version, filepath in sorted(schema_files.items()):
        checksum = sha256_file(filepath)
        conn.execute(
            "INSERT INTO migration_history "
            "(version, type, filename, checksum_sha256, tool_version, duration_ms, "
            " status, hostname, machine_id, repo_commit) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [version, "schema", filepath.name, checksum, TOOL_VERSION, 0,
             "applied", hostname, machine_id, commit],
        )
    for version, filepath in sorted(seed_files.items()):
        checksum = sha256_file(filepath)
        conn.execute(
            "INSERT INTO migration_history "
            "(version, type, filename, checksum_sha256, tool_version, duration_ms, "
            " status, hostname, machine_id, repo_commit) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [version, "seed", filepath.name, checksum, TOOL_VERSION, 0,
             "applied", hostname, machine_id, commit],
        )
    conn.commit()

    # drop schema_version last, only after every record is committed,
    # two sources of truth is worse than one
    conn.execute("DROP TABLE IF EXISTS schema_version")
    conn.commit()

    generate_manifest(conn, hostname)
    print(
        f"Adopted {len(schema_files)} schema + {len(seed_files)} seed migrations as "
        f"applied. schema_version table dropped. migration_manifest.json generated."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    """Delegates to the existing get_alems_db_path() path resolution so
    this tool never hardcodes a DB location. path_loader.py lives in the
    same scripts/tools/ directory as this file, Python already puts the
    running script's own directory at sys.path[0], so no extra path
    manipulation is needed."""
    from path_loader import get_alems_db_path
    return get_alems_db_path()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="alems_migrate.py",
        description="A-LEMS migration runner, SQLite only, set based version tracking.",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--adopt", action="store_true")
    args = parser.parse_args()

    hostname = get_hostname()
    machine_id = get_machine_id()
    commit = get_repo_commit()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        if args.check:
            return cmd_check(conn)
        if args.verify:
            return cmd_verify(conn)
        if args.status:
            cmd_status(conn)
            return 0
        if args.plan:
            cmd_plan(conn, hostname)
            return 0
        if args.adopt:
            cmd_adopt(conn, hostname, machine_id, commit)
            return 0
        cmd_migrate(conn, hostname, machine_id, commit)
        return 0
    except MigrationError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
