# Network Energy Attribution — Cross-Platform Methodology
**Document:** `research/28-network-energy-cross-platform-methodology.md`
**Method IDs:** `network_wait_rapl_slice_v2`, `network_wait_spbm_fraction_v1`, `network_wait_time_fraction_v1`
**Schema version:** v77 (`network_energy_attribution`)
**Spec:** SPEC_03_NETWORK_ENERGY_CROSS_PLATFORM
**Conservation role:** NONE — diagnostic signal, not a conservation partition

---

## Overview

SPEC_03 replaces the single `network_wait_energy_v1` method with a
platform-independent strategy pattern. The old formula multiplied RAPL
by `alpha_cpu`, which approached zero during network blocking — zeroing
out the very energy being measured.

Three strategies cover the current platform matrix:

| Strategy | Platform | Method ID | Confidence |
|----------|----------|-----------|------------|
| A — RAPL slice | UBUNTU2505 (Intel x86_64, AX201) | `network_wait_rapl_slice_v2` | 0.93 |
| B — SPBM DC_INPUT | GN100 (aarch64, Grace GB10) | `network_wait_spbm_fraction_v1` | 0.70 |
| C — Time fraction | All others (fallback) | `network_wait_time_fraction_v1` | 0.50 |

---

## What This Measures

Energy consumed by the system during LLM API blocking windows
`[request_start_ns, first_token_time_ns]` from `llm_interactions`.

This includes: NIC DMA activity, PCH power delivery, DRAM refresh,
uncore fabric maintenance during CPU-idle wait.

**Key finding:** Energy is NON-ZERO even when `cpu_percent_during_wait≈0`
because uncore/NIC/PCH remain active during streaming token receipt.

This is an AXIS 3A physical observable — NOT a conservation partition.
Do NOT sum with `orchestration_energy_uj`.

---

## Section 3.1 — Strategy A: RAPL Slice

**Applies to:** UBUNTU2505 (Intel i7-1165G7, AX201 WiFi, PCI 00:14.3)

AX201 is PCH-integrated — inside RAPL uncore domain (bus 0).

$$E_{network} = \sum_{i} \sum_{s \in [t^i_{req}, t^i_{first}]} (pkg\_end\_uj_s - pkg\_start\_uj_s)$$

**Key fix over v1:** No `alpha_cpu` multiplication. During blocking,
CPU cores are idle but pkg is non-zero due to NIC DMA, PCH, uncore.
Multiplying by alpha_cpu≈0 was zeroing out the measurement.

**Confidence:** 0.93

---

## Section 3.2 — Strategy B: SPBM DC_INPUT

**Applies to:** GN100 (NVIDIA Grace GB10, aarch64, no RAPL)

$$E_{network} = \sum_{i} \sum_{s \in [t^i_{req}, t^i_{first}]} E_{DC\_INPUT,s}$$

DC_INPUT (domain_id=28) captures total board input power.

**Known overestimate:** GPU idle draw included during blocking period.
Report as conservative upper bound in paper. Future v2: subtract
GPU_DCGM (domain_id=6) before attribution.

**Fallback:** When DC_INPUT has no data (pre-v76 runs), GPU_SPBM (domain_id=7)
is used. GPU_SPBM captures the broad GPU power rail and is available for all
GN100 runs including early groq experiments.

**Confidence:** 0.70

---

## Section 3.3 — Strategy C: Time Fraction Fallback

**Applies to:** Apple M1 Pro, AMD without RAPL, VMs, unknown platforms.

$$E_{network} = \frac{non\_local\_ms}{task\_duration\_ms} \times E_{dynamic}$$

Uses `dynamic_energy_uj` NOT `attributed_energy_uj` — attributed has
`alpha_cpu` baked in which would double-suppress the estimate.

**Conservative lower bound.** Misses uncore/NIC activity during CPU-idle wait.

**Confidence:** 0.50

---

## Strategy Selection Logic
NIC topology detection (sysfs, no subprocess):

PCI bus 0 → pch_integrated

PCI bus > 0 → discrete

no sysfs → unknown
Strategy selection (pure function, testable):

pch_integrated + has_rapl  → Strategy A

has_spbm (any topology)    → Strategy B

otherwise                  → Strategy C

---

## DB Table

`network_energy_attribution` (migration v77):
- `strategy_used` — method_id of selected strategy
- `energy_uj` — NULL if unmeasurable (MIC-3)
- `confidence` — strategy confidence score
- `measurement_type` — MEASURED | INFERRED
- `window_count` — number of LLM blocking windows
- `coverage_fraction` — fraction of windows with energy data
