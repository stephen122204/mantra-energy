# A-LEMS Quick Start

## Prerequisites

- Python 3.9 or later
- Git
- SQLite3 (pre-installed on macOS and most Linux)
- sudo access (for energy measurement permissions)

## One Command Install

```bash
git clone https://github.com/deepakpanigrahy03/alems-platform.git
cd alems-platform
bash scripts/install.sh
```

The installer detects your platform automatically and walks you through
data directory setup and model configuration.

## After Install

```bash
source venv/bin/activate

# Verify everything works
python -m core.execution.tests.test_llm_setup --provider all --verbose

# Run your first experiment
python -m core.execution.tests.test_harness \
  --task-id gsm8k_basic --repetitions 1 --save-db
```

## Supported Platforms

| Platform | OS | Architecture | Energy Source |
|---|---|---|---|
| Intel/AMD Linux | Ubuntu 24+ | x86_64 | RAPL sysfs counters |
| NVIDIA Grace (GN100) | Ubuntu 24+ | aarch64 | SPBM hwmon + DCGM |
| Apple Silicon Mac | macOS 26+ | arm64 | IOKit via powermetrics |

## Troubleshooting

**Permission denied on energy readings:**
Re-run the permissions step:
```bash
bash scripts/platforms/<your_platform>/provision.sh permissions
```

**Database not found:**
Check ~/.alemsrc has ALEMS_DATA_ROOT set:
```bash
cat ~/.alemsrc
python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())"
```

**Model not loading:**
Re-run model setup:
```bash
bash scripts/platforms/<your_platform>/provision.sh models
```

For the full installation guide with platform-specific details, see
[Installation Guide](installation-guide.md).
