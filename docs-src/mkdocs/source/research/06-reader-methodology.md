# Reader Methodology

## IOKit Power Reader (macOS)

Reads hardware power sensors on macOS via the IOKit framework.
Converts instantaneous power (watts) to cumulative energy (µJ) by integrating
over time: E = P × Δt × 10⁶. Supports both Intel (SMC) and Apple Silicon (PMGR)
power management interfaces. Current implementation is a stub returning zeros
pending full IOKit integration (Chunk 1.1).

## Estimator (ML-Based Energy Estimation)

Used on ARM VMs and platforms without RAPL access. Predicts package energy
using a trained XGBoost model with features: CPU utilisation, frequency,
instruction count, and task type. Current implementation returns zeros
pending model training (Chunk 7). All results marked INFERRED with
confidence=0.0.

## Dummy Energy Reader

Safe fallback for completely unsupported platforms (Windows, WSL, unknown OS).
Returns zero for all domains. Never raises exceptions — system stability
guaranteed on any platform. All results marked LIMITED with confidence=0.0.
