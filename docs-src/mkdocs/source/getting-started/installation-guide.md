# Installation Guide

Complete setup for A-LEMS on all supported platforms.

---

## Prerequisites

### System Requirements

| Requirement | Linux (Intel x86) | Linux (ARM/GN100) | macOS (Apple Silicon) |
|---|---|---|---|
| **OS** | Ubuntu 24+ / any Linux | Ubuntu 24+ | macOS 26+ |
| **CPU** | Intel 6th gen+ (RAPL) | NVIDIA Grace GB10 | Apple M1/M2/M3 |
| **RAM** | 8 GB min, 16 GB rec | 16 GB+ | 16 GB+ |
| **Storage** | 10 GB free | 20 GB free | 10 GB free |
| **Python** | 3.9+ | 3.9+ | 3.9+ |
| **Energy source** | RAPL sysfs counters | SPBM hwmon + DCGM | IOKit via powermetrics |

### Package Installation

**Ubuntu / Debian (Intel or ARM):**
```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv git build-essential \
    linux-tools-common linux-tools-generic sqlite3
```

**macOS (Apple Silicon):**
```bash
xcode-select --install
# Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 sqlite3
```

---

## Automated Install (Recommended)

The unified installer detects your platform and runs every step in the
correct order.

```bash
git clone https://github.com/deepakpanigrahy03/alems-platform.git
cd alems-platform
bash scripts/install.sh
```

The installer will:

1. Create a Python virtual environment and install dependencies
2. Install platform-specific packages (Metal on Mac, CUDA deps on ARM)
3. Configure hardware access permissions
4. Run hardware detection (produces hw_config.json)
5. Set up your data directory (~/.alemsrc with ALEMS_DATA_ROOT)
6. Initialize the database with all tables
7. Apply universal seed data (8 seed files, all lookup tables)
8. Run schema migrations
9. Apply platform-specific seed data (power rails on GN100)
10. Detect your software environment
11. Seed the methodology registry
12. Guide you through model and API key setup

After install completes, the verification step runs automatically and
reports pass/fail for every check.

---

## Manual Install (Step by Step)

Use this if you need to run individual steps, debug a partial install,
or understand what the automated installer does.

### Step 1: Clone and Create Virtual Environment

```bash
git clone https://github.com/deepakpanigrahy03/alems-platform.git
cd alems-platform
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Platform-Specific Dependencies

**Intel x86 Linux:** No extra pip packages needed.

**ARM Linux (GN100):**
```bash
# vLLM for local GPU inference (requires CUDA toolkit)
pip install vllm
# GN100-specific requirements if present
pip install -r requirements-gn100.txt 2>/dev/null || true
```

**macOS Apple Silicon:**
```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python \
    --force-reinstall --no-cache-dir
```

### Step 3: Permissions

```bash
sudo bash scripts/fix_permissions.sh
```

What this does per platform:

| Platform | Permissions configured |
|---|---|
| Intel x86 | RAPL sysfs read access, MSR module, turbostat |
| ARM (GN100) | hwmon sysfs read access, DCGM |
| macOS | sudoers rule for non-interactive powermetrics |

Verify permissions work (macOS):
```bash
sudo -n powermetrics --samplers cpu_power -n 1 -i 100 > /dev/null 2>&1 && echo "OK" || echo "FAILED"
```

### Step 4: Hardware Detection

```bash
python3 scripts/detect_hardware.py
```

Produces hw_config.json with your complete hardware fingerprint:
CPU model/vendor/cores, GPU model/driver, RAPL domains (Intel),
SPBM channels (GN100), thermal zones, and architecture flags.

The detection is fully automatic. No manual configuration needed.

### Step 5: Data Directory Setup

A-LEMS stores experiment data outside the repo, resolved per machine
via ~/.alemsrc and path_loader.py.

```bash
# Choose your data root (default: /mnt/alems-data)
mkdir -p /mnt/alems-data/$(hostname | tr '[:upper:]' '[:lower:]')

# Write the config
cat >> ~/.alemsrc << 'EOF'
# A-LEMS environment (sourced by path_loader.py)
export ALEMS_DATA_ROOT=/mnt/alems-data
EOF
```

Verify the path resolves correctly:
```bash
python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())"
```

### Step 6: Database Initialization

```bash
source ~/.alemsrc

DB_PATH=$(python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())")

python3 -c "
from core.database.sqlite_adapter import SQLiteAdapter
db = SQLiteAdapter('${DB_PATH}')
db.create_tables()
print('Tables created')
"
```

### Step 7: Seed Data

Universal seed data (identical on every platform):
```bash
for f in migrations/seed/s*.sql; do
    sqlite3 "$DB_PATH" < "$f"
    echo "Applied $(basename $f)"
done
```

Platform-specific seed data (GN100 only):
```bash
# GN100: apply SPBM power rail definitions
sqlite3 "$DB_PATH" < migrations/platform/gn100/power_rails.sql
```

### Step 8: Migrations

```bash
python3 scripts/tools/alems_migrate.py
```

### Step 9: Environment Detection

**Must run after Step 8.** Environment detection reads the
schema_version table, which migrations create.

```bash
python3 scripts/detect_environment.py
```

### Step 10: Methodology Seeding

```bash
python3 scripts/seed_methodology.py
```

### Step 11: Model and API Setup

**Local inference (Mac with Metal or GN100 with CUDA):**

Download a GGUF model:
```bash
mkdir -p ~/models
cd ~/models
wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf
```

Update config/models.yaml local section with the model path.

**Cloud inference (all platforms):**

Create core/.env with your API key:
```bash
cp core/.env.example core/.env
# Edit core/.env:
#   NVIDIA_NIM_API_KEY=your-key-here
```

---

## Verification

Run the platform verification script:
```bash
DB_PATH=$(python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())")
bash scripts/platforms/<your_platform>/verify.sh "$DB_PATH"
```

Where `<your_platform>` is one of: `apple_m1`, `linux_arm`, `intel_x86`.

Then test the LLM setup:
```bash
python -m core.execution.tests.test_llm_setup --provider all --verbose
```

And run your first experiment:
```bash
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 1 --save-db
```

Verify experiment data was recorded:
```bash
DB_PATH=$(python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())")
sqlite3 "$DB_PATH" "SELECT run_id, workflow_type, core_energy_uj, gpu_total_energy_uj FROM runs ORDER BY run_id DESC LIMIT 3;"
```

---

## Idle Baseline Measurement

After installation is verified, capture your idle power baseline.
This is used to separate dynamic (workload) energy from static (idle)
energy in all subsequent experiments.

```bash
python -m core.utils.idle_baseline --duration 10 --samples 3
```

---

## Post-Installation Workflow

Daily usage after installation:

```bash
cd alems-platform
source venv/bin/activate

# Run experiments
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 5 --save-db

# Check results
DB_PATH=$(python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())")
sqlite3 "$DB_PATH" "SELECT run_id, total_energy_uj, dynamic_energy_uj, total_tokens FROM runs ORDER BY run_id DESC LIMIT 5;"
```

---

## Adding a New Machine

When onboarding a new machine of an existing platform type:

1. Clone the repo
2. Run `bash scripts/install.sh`
3. The installer handles everything, including the data directory,
   which gets a unique path per hostname via path_loader.py

When onboarding a new platform type (e.g., AMD):

1. Create `scripts/platforms/<platform_name>/provision.sh` and `verify.sh`
2. If hardware has power rails, create `migrations/platform/<platform_name>/power_rails.sql`
3. Add platform detection branch to install.sh
4. Run `bash scripts/install.sh`

See SPEC_MIGRATION_M4.md for the full platform extension guide.

---

## Troubleshooting

| Issue | Likely Cause | Solution |
|---|---|---|
| Permission denied on energy readings | Hardware access not configured | `sudo bash scripts/fix_permissions.sh` |
| ModuleNotFoundError | venv not activated | `source venv/bin/activate` |
| RAPL not found (Intel) | CPU too old for RAPL | Need Intel 6th gen+ (Sandy Bridge+) |
| powermetrics fails (Mac) | Sudoers rule missing | `bash scripts/platforms/apple_m1/provision.sh permissions` |
| Database not found | ~/.alemsrc not set up | Check `cat ~/.alemsrc` and re-run Step 5 |
| NormalizedWriter: unknown domain | Seed data missing | Re-run Step 7 (seed files) |
| ggml_metal_init missing (Mac) | llama-cpp not built with Metal | `CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --force-reinstall` |
| schema_version error | Steps run out of order | Run Step 8 (migrations) before Step 9 (environment detection) |
| energy_sample_domains empty | Domain seed rows missing | Verify s002 applied: `sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains;"` should be 29 |
