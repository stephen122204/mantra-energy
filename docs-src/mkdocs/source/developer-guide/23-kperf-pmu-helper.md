# kperf PMU Helper: Developer Guide

---
**Component:** `scripts/helpers/kperf_reader.c`
**Compiled binary:** `/usr/local/bin/alems_kperf_reader`
**Python reader:** `core/readers/darwin/kperf_pmu_reader.py`
**Applies to:** Apple Silicon (arm64) running bare metal macOS 12+
**Schema version:** No new columns (columns pre-exist in runs table)
**Status:** DRAFT
**Last updated:** 2026-08-13
---

## What It Does

Apple Silicon has no `perf` subsystem. The equivalent is Apple's private
`kperf.framework` and `kperfdata.framework`, which expose the ARM PMU
(Performance Monitoring Unit) through undocumented but stable C functions.

`kperf_reader.c` is a minimal C program that:

1. Loads kperf and kperfdata at runtime via `dlopen` (no link-time dependency)
2. Uses `kpep_db_create(NULL)` to auto-detect the current chip and load
   its event plist from `/usr/share/kpep/` (e.g. `a14.plist` for M1)
3. Configures 6 PMU counters: 2 fixed (CYCLES, INSTRUCTIONS) and 4
   configurable (L1D cache miss variants, L1D TLB access)
4. Reads all counter values across all CPU cores
5. Sums across cores for system-wide totals
6. Prints one line of JSON to stdout and exits

The Python reader `KPerfPMUReader` calls this binary via `sudo -n` at
measurement start and stop, then computes deltas. Two subprocess calls
per measurement, ~50ms each, ~100ms total overhead.

### Why a compiled C helper instead of Python ctypes?

`kpc_set_config()` and `kpc_force_all_ctrs_set()` require root (EPERM
without it). Running the entire A-LEMS Python process as root is
unacceptable — it would affect all other readers. The C helper isolates
privilege to a single minimal binary called via `sudo -n`, matching the
existing pattern used for `powermetrics`.

---

## Fixed vs Configurable Counters

Apple Silicon PMUs have two counter types:

**Fixed counters** (slots 0 and 1, always available, no config needed):

| Slot | Event | A-LEMS column |
|------|-------|---------------|
| 0 | FIXED_CYCLES | cycles |
| 1 | FIXED_INSTRUCTIONS | instructions |

**Configurable counters** (require `kpc_set_config`, hence root):

| Event name | A-LEMS column | Notes |
|------------|---------------|-------|
| L1D_CACHE_MISS_LD | cache_misses (partial) | L1D load misses |
| L1D_CACHE_MISS_ST | cache_misses (partial) | L1D store misses |
| L1D_CACHE_MISS_LD_NONSPEC | l1d_cache_misses_total | Retired only, most accurate |
| L1D_TLB_ACCESS | cache_references | Proxy — no direct total-accesses event on M1 |

Combined: `cache_misses = L1D_CACHE_MISS_LD + L1D_CACHE_MISS_ST`

Total: 2 fixed + 4 configurable = 6 counters. Apple Silicon supports up
to 10 (2 fixed + 8 configurable).

---

## How kpep Auto-Detection Works

`kpep_db_create(NULL, &db)` with a NULL path causes kperfdata to
automatically detect the current chip and load the corresponding plist:

| Chip | Core arch | Plist |
|------|-----------|-------|
| M1, M1 Pro, M1 Max, M1 Ultra | a14 | /usr/share/kpep/a14.plist |
| M2, M2 Pro, M2 Max, M2 Ultra | a15 | /usr/share/kpep/a15.plist |
| M3, M3 Pro, M3 Max, M3 Ultra | a16 | /usr/share/kpep/a16.plist |
| M4, M4 Pro, M4 Max | a17 | /usr/share/kpep/a17.plist |

The C helper looks up event names via `kpep_db_event(db, name, &ev)`.
If an event name is not in the chip's plist, the helper prints a stderr
warning and outputs 0 for that field — no crash, graceful degradation.

---

## How to Compile and Install

### Prerequisites

Xcode Command Line Tools only (no full Xcode needed):

```bash
xcode-select --install
```

### Compile

From the repo root on the Mac:

```bash
cc -O2 -o scripts/helpers/kperf_reader scripts/helpers/kperf_reader.c
```

No special flags needed. kperf and kperfdata are loaded at runtime via
`dlopen` — no `-framework` linker flags required. Links only against
`libSystem` (implicit). Compatible with Xcode CLT on macOS 12 through 15+.

If the compiler warns about `sysctl` being implicit, add:

```bash
cc -O2 -include sys/sysctl.h -o scripts/helpers/kperf_reader scripts/helpers/kperf_reader.c
```

### Install to system path

```bash
sudo cp scripts/helpers/kperf_reader /usr/local/bin/alems_kperf_reader
sudo chown root:wheel /usr/local/bin/alems_kperf_reader
sudo chmod 755 /usr/local/bin/alems_kperf_reader
```

Must be owned by root so that the sudoers rule is secure.

### Install sudoers rule

Either run `scripts/fix_permissions.sh` (which now includes this), or
manually:

```bash
echo "%admin ALL=(root) NOPASSWD: /usr/local/bin/alems_kperf_reader" \
    | sudo tee /etc/sudoers.d/alems_kperf > /dev/null
sudo chmod 0440 /etc/sudoers.d/alems_kperf
```

### Verify

```bash
sudo -n /usr/local/bin/alems_kperf_reader
# Expected output (one JSON line):
# {"instructions":12345678,"cycles":9876543,"l1d_miss_ld":1234,
#  "l1d_miss_st":567,"l1d_miss_nonspec":1100,"l1d_tlb_access":45000}
```

---

## Output JSON Format

The helper always outputs exactly one JSON line to stdout:

```json
{
  "instructions": <uint64>,
  "cycles":       <uint64>,
  "l1d_miss_ld":  <uint64>,
  "l1d_miss_st":  <uint64>,
  "l1d_miss_nonspec": <uint64>,
  "l1d_tlb_access":   <uint64>
}
```

All values are system-wide totals (sum across all CPU cores) since the
last counter reset. The Python reader takes two snapshots and computes
deltas. Values of 0 for a configurable field mean the event was not
found in the chip's plist (expected for some events on some chips).

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Framework load failed (kperf/kperfdata not found) |
| 2 | kpep database creation failed |
| 3 | Counter configuration failed (usually: not running as root) |
| 4 | Counter read failed |

---

## Maintaining Across macOS Versions

### When macOS upgrades (same chip)

No action needed. The binary uses `dlopen` to load kperf/kperfdata at
runtime — it does not link against them at compile time. If Apple changes
internal function signatures in a major release, `is_available()` in the
Python reader will detect the failure and fall back to DummyCPUReader.

### When a new chip is deployed (M2, M3, M4)

1. Check available events on the new chip:
```bash
plutil -p /usr/share/kpep/*.plist | grep -i "L2\|L3\|LLC\|cache"
```

2. If L2/L3 events appear with new names, add them to `CFG_EVENT_NAMES[]`
   in `kperf_reader.c` and add corresponding JSON output fields.

3. Recompile and reinstall the binary on that machine.

4. Update the Python reader to map the new JSON fields to
   `PerformanceCounters` fields.

5. The auto-detection via `kpep_db_create(NULL)` handles the new chip's
   plist automatically — no chip-specific code path needed.

### When a developer rebuilds after a git pull

The compiled binary is NOT tracked in git (binaries don't belong in git).
Only the source `scripts/helpers/kperf_reader.c` is tracked.

After `git pull` on the Mac, recompile if the source changed:

```bash
git diff HEAD~1 scripts/helpers/kperf_reader.c
# If changed:
cc -O2 -o scripts/helpers/kperf_reader scripts/helpers/kperf_reader.c
sudo cp scripts/helpers/kperf_reader /usr/local/bin/alems_kperf_reader
sudo chown root:wheel /usr/local/bin/alems_kperf_reader
sudo chmod 755 /usr/local/bin/alems_kperf_reader
```

Add to your Mac setup checklist: recompile kperf_reader after any
`git pull` that touches `scripts/helpers/kperf_reader.c`.

### On Linux machines (GN100, UBUNTU2505)

Do nothing. The C file is in the repo but compilation only happens on
Mac. The Python reader's `is_available()` returns False immediately on
Linux (platform.system() != "Darwin"). The factory falls through to
PerfReader on Linux — no regression.

---

## Security Notes

- The binary must be owned by root (`chown root:wheel`) and not writable
  by non-root users. The sudoers rule grants passwordless execution only
  for this specific binary path. A world-writable binary at that path
  would be a privilege escalation vector.

- The helper does exactly one thing: read PMU counters and print JSON.
  It has no network access, no file writes, no exec calls. Review the
  source (`scripts/helpers/kperf_reader.c`) to verify this before
  installing.

- The sudoers rule uses `NOPASSWD` scoped to a single absolute path.
  This matches the existing pattern for `powermetrics` in A-LEMS.

---

## Troubleshooting

**`is_available()` returns False — helper exists but sudo fails:**
```bash
# Check sudoers rule is installed:
sudo cat /etc/sudoers.d/alems_kperf
# Should show: %admin ALL=(root) NOPASSWD: /usr/local/bin/alems_kperf_reader

# Check file ownership:
ls -la /usr/local/bin/alems_kperf_reader
# Should show: -rwxr-xr-x  1 root  wheel
```

**Helper returns exit code 3 (counter config failed):**
```bash
# Verify running as root via sudo:
sudo /usr/local/bin/alems_kperf_reader
# If this works but sudo -n fails, sudoers rule not installed correctly.
```

**Running in a VM (Parallels, VMware, UTM):**
kperf is not available in virtualized macOS. `is_available()` returns
False, reader falls back to DummyCPUReader. Expected behavior.

**Helper output missing some fields (e.g. l1d_miss_nonspec = 0):**
The event was not found in the chip's plist. Check stderr output from
the helper for WARN lines. This is expected for events not present in
older chip plists. The Python reader handles missing fields as 0.
