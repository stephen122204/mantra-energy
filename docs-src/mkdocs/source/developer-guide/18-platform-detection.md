# Platform Detection & Measurement Mode

## Overview

A-LEMS runs on multiple hardware configurations — Intel laptop, ARM Oracle VM, macOS.
Each platform has different energy measurement capabilities. The platform detection
system determines the correct measurement mode at startup so the rest of the codebase
never needs to know what hardware it is running on.

---

## Run Order

These three scripts must run in this order before any experiment:

```
1. python scripts/detect_environment.py   → config/environment.json
2. python scripts/detect_hardware.py      → config/hw_config.json
3. (automatic on first import)
   core/utils/platform.py reads both      → config/platform.json
```

`platform.py` runs automatically — it is not a script you call manually.
It is triggered on first import of `ReaderFactory` or `EnergyEngine`.

---

## Measurement Modes

| Mode | When | Energy Source | Reader |
|------|------|---------------|--------|
| `MEASURED` | Linux x86_64 with RAPL | Direct sysfs µJ counter | `RAPLReader` |
| `MEASURED` | macOS (any arch) | IOKit power sensor W→µJ | `IOKitPowerReader` |
| `INFERRED` | Linux aarch64 (ARM VM) | ML model prediction | `EnergyEstimator` |
| `INFERRED` | Linux x86_64, no RAPL | ML model prediction | `EnergyEstimator` |
| `LIMITED` | Windows / WSL / unknown | Zeros + warning | `DummyEnergyReader` |

**Key distinction:** `MEASURED` means real hardware sensor access exists.
The reader may still do arithmetic (IOKit: W×s→µJ) but the underlying
measurement is hardware, not estimated.

---

## Platform Matrix

| Hostname | OS | Arch | Virtualisation | Mode |
|----------|----|------|----------------|------|
| UBUNTU2505 | Linux | x86_64 | none (bare metal) | MEASURED |
| alems-vnic | Linux | aarch64 | kvm | INFERRED |
| macOS (any) | Darwin | x86_64 / arm64 | — | MEASURED |

---

## Decision Logic

```
Linux + x86_64 + RAPL paths present  →  MEASURED
Linux + x86_64 + no RAPL             →  INFERRED  (permissions issue?)
Linux + aarch64 / arm64              →  INFERRED  (ARM VM — RAPL does not exist)
Darwin (any arch)                    →  MEASURED  (IOKit always available)
Windows / WSL / unknown              →  LIMITED
```

Container note: if `container_runtime` is set in `environment.json`
AND RAPL paths exist, the mode stays `MEASURED` but a warning is logged.
`RAPLReader._validate_path()` verifies actual file accessibility at init time.

---

## Config Files

### `config/environment.json`
Written by `detect_environment.py`. Flat structure, no nested dicts.

Key fields used by `platform.py`:

| Field | Purpose |
|-------|---------|
| `torch_version` | `null` = torch not installed → EnergyEstimator ML unavailable |
| `container_runtime` | `null` = bare metal; `"docker"` = may block RAPL |
| `kernel_version` | Used in platform summary / provenance |
| `env_hash` | 16-char fingerprint linking runs to exact software stack |

### `config/hw_config.json`
Written by `detect_hardware.py`. Contains RAPL paths, MSR devices,
thermal zones, turbostat availability.

Key sections used by `platform.py`:

| Section | Field | Purpose |
|---------|-------|---------|
| `metadata` | `machine` | `x86_64` or `aarch64` — determines arch |
| `rapl` | `paths` | Empty = no RAPL → INFERRED mode |
| `msr` | `devices` | List of `/dev/cpu/N/msr` files |
| `thermal` | `paths` | Thermal zone sysfs paths |
| `turbostat` | `available` | Whether turbostat binary was found |

### `config/platform.json`
Written by `PlatformDetector.save()`. Consumed by `ReaderFactory`.
Contains the full `PlatformCapabilities` dict — all fields from both
config files combined with the measurement mode decision.

---

## Reader Architecture

```
EnergyEngine
    │
    └── ReaderFactory.get_energy_reader(config, caps)
            │
            ├── caps.measurement_mode == MEASURED + Linux  →  RAPLReader
            ├── caps.measurement_mode == MEASURED + macOS  →  IOKitPowerReader
            ├── caps.measurement_mode == INFERRED          →  EnergyEstimator
            └── caps.measurement_mode == LIMITED           →  DummyEnergyReader
```

All readers implement `EnergyReaderABC`:

```python
read_energy_uj() → Dict[str, int]   # domain → µJ
get_domains()    → List[str]
is_available()   → bool
get_name()       → str
```

`EnergyEngine` only calls these four methods — never accesses a
concrete reader directly.

---

## Adding a New Platform (3-Step Rule)

To add support for a new OS or hardware type, touch exactly 3 files:

**Step 1 — `core/utils/platform.py`**: add detection in `_decide_mode()`

```python
# Example: Windows with ACPI
if os_name == "Windows" and has_acpi:
    return MEASURED
```

**Step 2 — New reader file** implementing `EnergyReaderABC`:

```
core/readers/windows/acpi_power_reader.py
```

```python
class ACPIPowerReader(EnergyReaderABC):
    def read_energy_uj(self) -> Dict[str, int]: ...
    def get_domains(self)    -> List[str]: ...
    def is_available(self)   -> bool: ...
    def get_name(self)       -> str: ...
```

**Step 3 — `core/readers/factory.py`**: add one dispatch case:

```python
if mode == MEASURED and caps.os == "Windows":
    return cls._make_acpi_reader(config)
```

Nothing else changes. `EnergyEngine`, `harness.py`, database, UI — all untouched.

---

## Reader Status

| Reader | File | Status | Real work when |
|--------|------|--------|----------------|
| `RAPLReader` | `core/readers/rapl_reader.py` | ✅ Production | — |
| `PerfReader` | `core/readers/perf_reader.py` | ✅ Production | — |
| `SensorReader` | `core/readers/sensor_reader.py` | ✅ Production | — |
| `TurbostatReader` | `core/readers/turbostat_reader.py` | ✅ Production | — |
| `MSRReader` | `core/readers/msr_reader.py` | ✅ Production | — |
| `IOKitPowerReader` | `core/readers/darwin/iokit_power_reader.py` | 🔲 Stub (zeros) | Chunk 1.1 |
| `EnergyEstimator` | `core/readers/fallback/energy_estimator.py` | 🔲 Stub (zeros) | Chunk 7 |
| `DummyEnergyReader` | `core/readers/fallback/dummy_energy_reader.py` | ✅ Intentional zeros | — |

---

## Chunk 1 Change Log

| Change | File | Reason |
|--------|------|--------|
| Created `PlatformDetector` | `core/utils/platform.py` | Central mode detection |
| Created `ReaderFactory` | `core/readers/factory.py` | Platform-aware dispatch |
| Created `EnergyReaderABC` etc. | `core/readers/interfaces.py` | Interface contract |
| Created `EnergyEstimator` stub | `core/readers/fallback/energy_estimator.py` | INFERRED mode |
| Created `IOKitPowerReader` stub | `core/readers/darwin/iokit_power_reader.py` | macOS MEASURED |
| Created `DummyEnergyReader` | `core/readers/fallback/dummy_energy_reader.py` | LIMITED mode |
| Fixed container detection | `scripts/detect_environment.py` | Was hardcoded `None` |
| Updated `EnergyEngine.__init__` | `core/energy_engine.py` | Use factory not hardcoded readers |

---

## Verification

```bash
# Run from project root after copying all Chunk 1 files

# Step 1: detect environment
python scripts/detect_environment.py

# Step 2: detect hardware (already done, hw_config.json exists)

# Step 3: platform detection
python -m core.utils.platform

# Step 4: verify factory dispatches correctly
python -c "
from core.readers.factory import ReaderFactory
r = ReaderFactory.get_energy_reader()
print('Reader:', r.get_name())
print('Available:', r.is_available())
print('Domains:', r.get_domains())
"
```

Expected on UBUNTU2505 (x86_64 bare metal):
```
Reader    : RAPLReader
Available : True
Domains   : ['core', 'package-0', 'uncore']
```

Expected on alems-vnic (ARM64 KVM):
```
Reader    : EnergyEstimator
Available : False
Domains   : ['package-0', 'core']
```
