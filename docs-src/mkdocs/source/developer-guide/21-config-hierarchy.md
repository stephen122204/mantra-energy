# Config Hierarchy and DB Path Resolution

**Added:** 2026-06-17
**Relevant files:** `core/config_loader.py`, `~/.alemsrc`, `config/machines/`
**Status:** Implemented in Chunk 16B, session 2026-06-17

---

## Overview

A-LEMS is designed to run identically across heterogeneous hardware targets:
x86 workstations, ARM SoC clusters, Apple Silicon laptops, and HPC nodes.
Each machine has different storage paths, hardware backends, and credentials.

Before this system, the DB path was resolved from `hw_config.json` which
has no database key. The lookup silently fell through to a hardcoded default
on every machine. Energy writes on non-default storage went to the wrong
path and data was lost.

The three-layer config hierarchy eliminates all hardcoded paths. Adding a
new measurement machine requires zero code changes.

---

## The Three Layers

Inspired by the Ab Initio rc file pattern: each layer owns exactly what
it knows, and later layers win on conflict.

```
Layer 1:  ~/.alemsrc                            secrets + machine identity
Layer 2:  config/machines/<hostname>.yaml       platform config (Chunk 17)
Layer 3:  config/experiments/<name>.yaml        experiment parameters
           +
CLI flags                                       highest priority, always wins
```

---

## Layer 1: `~/.alemsrc`

Lives in the user home directory on every measurement machine. Never inside
the project directory. Never committed to version control. Contains secrets
and machine-specific environment variables.

**Format:**

```bash
# ~/.alemsrc — machine-specific config, never committed to git
export ALEMS_DATA_ROOT=/path/to/storage    # omit if using project default
export GROQ_API_KEY=gsk_...
export NVIDIA_API_KEY=nvapi-...
```

`ConfigLoader.__init__` calls `_source_alemsrc()` automatically on startup
before any config is read. Uses `os.environ.setdefault` so the shell
environment always wins over the rc file. Safe to source multiple times.

**`ALEMS_DATA_ROOT`** controls where the DB lives on this machine. Omit it
on machines that use the project default `data/experiments.db`.

**Machines with external or shared storage** set `ALEMS_DATA_ROOT` to the
mount point. The resolved path becomes:

```
$ALEMS_DATA_ROOT/<machine_id>/experiments.db
```

`machine_id` is read from `hw_config.json`, populated by `detect_hardware.py`.
Never set manually.

---

## Layer 2: `config/machines/<hostname>.yaml` (Chunk 17)

Will be auto-loaded by `ConfigLoader` using `socket.gethostname()`. No
manual mapping needed. The machine declares itself by hostname.

```
config/machines/
    TEMPLATE.yaml          committed — documents all valid keys
    <hostname>.yaml        gitignored — one per measurement machine
```

`.gitignore` rule:
```
config/machines/*.yaml
!config/machines/TEMPLATE.yaml
```

Each machine operator copies `TEMPLATE.yaml`, renames it to their hostname,
and fills in the values. Platform config (available backends, resource limits,
sync targets) lives here. Secrets stay in `~/.alemsrc`.

---

## Layer 3: `config/experiments/<name>.yaml`

Task parameters, model selection, repetitions, energy budget. Fully
committed to version control. Reproducible by any operator on any machine.
This layer does not vary per machine.

---

## DB Path Resolution: `get_db_path()`

`ConfigLoader.get_db_path()` is the single authoritative method for
resolving the DB path on any machine. Called once at harness init and
passed into `EnergyEngine`. Never derived from `hw_config.json`.

**Resolution order:**

```
1. Is ALEMS_DATA_ROOT set in the environment?
       YES → $ALEMS_DATA_ROOT/<machine_id>/experiments.db
       NO  → app_settings.yaml database.sqlite.path
                   (default: "data/experiments.db")
```

**Result by storage type:**

| Storage type | `ALEMS_DATA_ROOT` | Resolved path |
|---|---|---|
| Project default (no external storage) | not set | `data/experiments.db` |
| External NVMe mount | `/mnt/alems-data` | `/mnt/alems-data/<machine_id>/experiments.db` |
| Shared network storage | `/shared/alems-data` | `/shared/alems-data/<machine_id>/experiments.db` |
| Home directory storage | `~/alems-data` | `~/alems-data/<machine_id>/experiments.db` |

---

## How It Wires Together

```
ConfigLoader.__init__()
    └── _source_alemsrc()              reads ~/.alemsrc, sets env vars

ExperimentHarness.__init__(config_loader)
    └── EnergyEngine(
            engine_config,
            db_path=config_loader.get_db_path()    ← resolved per machine
        )

EnergyEngine.__init__(config, db_path)
    └── self._db_path = db_path

EnergyEngine._resolve_domain_id_cache()
EnergyEngine._resolve_source_id()
EnergyEngine.start_measurement()
    └── _db_path = self._db_path       ← always correct
        NormalizedWriter(_db_path, ...)
        LegacyWriter(_db_path, ...)
```

`EnergyEngine` never reads the database section of any config file.
It receives a resolved string from the caller. This is the invariant.

---

## Onboarding a New Measurement Machine

1. Run `scripts/detect_hardware.py` to generate `hw_config.json` with
   the correct `machine_id` for this machine.

2. Create `~/.alemsrc` with `ALEMS_DATA_ROOT` if storage is non-default,
   plus any required API keys.

3. Create the DB directory:
   ```bash
   mkdir -p $ALEMS_DATA_ROOT/<machine_id>/
   ```

4. `git pull` and run a test experiment. Platform detects everything else
   automatically from hostname and hw_config.

No code changes required. No config files inside the project need editing.
This is the onboarding invariant.

---

## Future Extension: Remote Execution

`~/.alemsrc` will grow to support distributed measurement across machines
connected via Tailscale or SSH:

```bash
export ALEMS_ROLE=orchestrator       # or: worker
export ALEMS_REMOTE_HOST=<hostname>
export ALEMS_REMOTE_USER=<user>
export ALEMS_REMOTE_DB_SYNC=true
export ALEMS_NETWORK=tailscale
```

`config/machines/<hostname>.yaml` (Layer 2) will declare available backends,
resource limits, and sync targets per machine. The orchestrator reads its
own hostname yaml, discovers remote workers, dispatches via the identity
set in `~/.alemsrc`. The three-layer system supports multi-node measurement
without any code changes.

---

## Compliance Notes

No schema changes. No new readers. No PAC, MPC, or SC rules triggered.

Rule DC-6: this file is registered in `mkdocs.yml` under Developer Guide.
Rule CQC-1: all patches grep-verified before writing.
Rule DC-1: `_source_alemsrc()` and `get_db_path()` carry 30% inline comments.
Rule MIC-1: `get_db_path()` never returns None — always a valid string path.

---

## What Was Broken Before This

| Location | Bug | Impact |
|---|---|---|
| `energy_engine.py` (3 places) | `self.config.get("database")` reads hw_config, always `{}` | DB path always project default on all machines |
| `normalized_writer.py` | `self._db.conn` — `_db` attribute never set | `AttributeError` on every energy write |
| `legacy_writer.py` | Constructor set `self._db`, flush used `self._conn` | `AttributeError` on flush |
| `energy_engine.py` (lines 309-337) | Dead duplicate `_resolve_*` methods using `self.db.conn` | `AttributeError` if reached |

All four fixed in session 2026-06-17.
