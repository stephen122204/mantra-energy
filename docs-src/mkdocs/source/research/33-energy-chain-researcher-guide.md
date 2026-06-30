# Energy Chain Validation: Researcher Guide

When A-LEMS reports that an agentic run consumed 70.7J of attributed energy,
what does that number actually mean and how confident should you be in it?
This guide explains the conservation framework that answers those questions,
what the validation output tells you about measurement quality, and how to
read the output when you are building a paper result from A-LEMS data.

## Why Conservation Matters

Every energy measurement tool produces numbers. What distinguishes A-LEMS
from tools like CodeCarbon, Zeus, and ML.ENERGY is that A-LEMS can prove
its numbers are internally consistent from the measurement artifacts alone.
Internal consistency is not the same as absolute accuracy: a system that
consistently underreports energy by 5 percent is internally consistent but
not accurate. What the conservation framework guarantees is that the
decomposition of a number is correct relative to the total: if we report
that planning consumed 6.7 percent of attributed energy, that fraction
closes against the measured total within 1 millijoule.

The validation output answers a question a reviewer will always ask: how
do you know your decomposition numbers sum to the right total? The answer
is that conservation is checked as a runtime SQL assertion on every
experiment, and any run that fails is excluded before it can appear in a
paper result.

## The Measurement Layers

A-LEMS measures energy at three levels of the hardware hierarchy, named ML0,
ML1, and ML2. Understanding these layers is essential for interpreting any
validation output.

ML0 is the board level. On the NVIDIA GN100 developer kit, ML0 sensors are
physical current monitors on the circuit board, similar to a clamp meter
on a power supply line. They measure everything: the SoC chip, the memory
modules, the storage, the cooling fans, the USB and display controllers,
and all the losses in the voltage regulators between the DC input and the
actual silicon. The ML0 measurement is the most complete picture of what
the machine draws from its power supply, but it is also the least specific
because it cannot tell you what portion went to the CPU versus the GPU
versus the fans.

ML1 is the SoC level. On ARM GN100, ML1 sensors are inside the Grace
Blackwell chip itself, reading hardware registers that accumulate energy
counts for named power domains. The SPBM interface (Spark Board Management)
exposes these via Linux sysfs. On Intel x86, the equivalent is RAPL (Running
Average Power Limit), which reads similar registers via MSR instructions.
On Apple Silicon, IOKit provides a package-level reading without domain
breakdown. ML1 is where most A-LEMS energy attribution happens: the
attributed_energy_uj value in the runs table is derived from ML1 readings.

ML2 is the accelerator level. DCGM (Data Center GPU Manager) reads an
internal GPU counter called field 156 that covers only the compute complex
inside the GPU: the streaming multiprocessors, the L2 cache, and the warp
schedulers. It does not cover GPU memory, the interconnect between the CPU
and GPU, or GPU voltage regulation. ML2 is the most specific but also the
most incomplete view of GPU energy.

On Intel x86, there is no ML0 equivalent (no board-level shunt monitor in
a standard desktop or laptop). On Apple M1, there is no ML2 equivalent
because Apple does not expose GPU energy separately from package energy via
IOKit.

## Conservation Checks and What They Tell You

The validator runs three named conservation checks. Each check name encodes
which measurement layers it spans.

**ML1-INT** is an intra-source check at the SoC level. It asks whether the
sum of named SoC power domains is less than or equal to the package total.
On GN100, this is: package >= cpu_p + cpu_e + gpu_spbm + dla. On Intel x86,
RAPL guarantees that core + uncore + dram equals the package total exactly,
so this becomes an exact equality check. On ARM, the Grace Blackwell chip
has internal domains that NVIDIA does not expose via SPBM: the CMN-700 mesh
interconnect connecting all the cores, the L3 cache slices, and the memory
controllers on the CPU side of the C2C bridge. These typically consume about
30 percent of the package energy on inference workloads, which is why the
ML1-INT residual on GN100 runs consistently around 31 percent. This is not
a measurement gap or a bug; it is a hardware architecture fact. The 31 percent
residual being consistent across linear runs (31.5 percent) and agentic runs
(31.2 percent) is actually evidence that the unmetered fabric behaves
predictably regardless of workload, which strengthens the claim that the
metered portions are trustworthy.

**ML0-ML1** is a cross-source check spanning the board sensor and the SoC
sensor. It asks whether the DC input energy is at least as large as the SoC
package energy. The difference is real energy consumed by everything outside
the SoC chip: memory DIMMs, NVMe storage, USB and DisplayPort controllers,
Ethernet PHY, cooling fans, and all voltage regulator conversion losses
including those in the external power brick. On GN100, this is around 30
percent of DC input. This means that of every watt consumed from the power
supply, roughly 0.7W reaches the SoC and 0.3W is consumed by board-level
components. This is a relevant number for anyone making sustainability claims
about agentic AI: the energy consumption that matters for carbon accounting is
the DC input, not just the SoC package.

**ML1-ML2** is a cross-source check spanning the SoC GPU sensor and the GPU
internal sensor. It asks whether the SPBM GPU broad rail is at least as large
as the DCGM compute energy. The difference is the NVLink-C2C interconnect
energy, the HBM3e memory PHY energy, and GPU voltage regulator overhead. On
GN100 running Mistral-7B inference, the ratio is approximately 1.31x: DCGM
sees 871J while SPBM sees 1144J, with the 273J difference attributable to
memory and fabric. This ratio is workload-dependent. A compute-saturated
training kernel with high SM utilization and low memory bandwidth would have
a lower ratio (closer to 1.1x) because the memory PHYs are not the bottleneck.
A memory-bandwidth-dominated workload (large KV-cache, frequent token
sampling) would have a higher ratio (potentially 2x to 3x). The ratio itself
is a diagnostic signal: tracking it across workload types tells you how
memory-bound versus compute-bound your inference workload is.

## Reading the Confidence Scores

Every conservation check carries a confidence score between 0 and 1, with
HIGH above 0.8, MEDIUM between 0.5 and 0.8, and LOW below 0.5.

The score has three components weighted as 40 percent sample count,
40 percent calibration against history, and 20 percent source accuracy.

The sample component rewards longer runs. A 10-second run at 10Hz SPBM
produces 100 samples and gets a perfect sample score. A 2-second run
produces 20 samples and gets a score of 0.6. This matters for paper
results: headline claims should use runs with HIGH confidence, which
typically means runs longer than 10 seconds.

The calibration component compares this run's conservation residual to
the historical distribution from prior runs of the same type on the same
platform. If the current run falls within one standard deviation of the
historical mean, the calibration score is 1.0. This component becomes
more informative as the corpus grows. With fewer than five historical
runs, the calibration score is neutral (0.5). With 50 or more runs, it
becomes a sensitive detector of anomalies.

The source component is fixed for each check on each platform. ML1-INT
on ARM gets 0.9 because SPBM is a silicon-internal measurement but lacks
a published accuracy specification. ML1-INT on x86 RAPL gets 1.0 because
Intel publishes measurement accuracy for RAPL. Cross-source checks (ML0-ML1,
ML1-ML2) get 0.7 because they combine measurements from different sensors
with different clocks, different sampling rates, and different accuracy
properties.

For a paper result, you should prefer runs where all conservation checks
show HIGH confidence. A MEDIUM confidence on ML1-ML2 due to sparse
calibration history is acceptable if you are reporting aggregate results
across many runs; the individual run uncertainty averages out. A LOW
confidence on ML1-INT due to very few samples indicates the run is too
short to produce reliable phase-level decomposition.

## PROC-ATTR: What Process Attribution Actually Means

The attributed_energy_uj value in the runs table represents the energy
attributed to the A-LEMS measurement process. Understanding how this is
computed on each platform is important for interpreting paper results.

On all platforms, CPU attribution follows the same formula: cpu_fraction
(computed from /proc/{pid}/stat tick deltas) multiplied by the dynamic CPU
energy (package energy minus idle baseline energy). On ARM GN100, the
dynamic CPU energy uses only the SPBM cpu_p and cpu_e domains (CPU cores
only), not the GPU rail. On Intel x86, it uses the full package dynamic
energy. This means the attributed_energy_uj on ARM does not include GPU
energy; GPU energy is tracked separately.

GPU attribution uses direct metering from DCGM. On GN100, the assumption
is single active workload: the entire DCGM energy is attributed to the
A-LEMS process because no other GPU processes are running. This assumption
is stated explicitly in the validation output with its confidence level.
When multi-tenant GPU scenarios arise, the confidence drops and the fraction
changes.

The PROC-ATTR-COMBINED block shows CPU plus GPU attributed energy and its
share of the total SoC package. On GN100, this is typically 45 to 50 percent
of the package: the process uses about 45 percent of the full SoC energy,
with the remaining 55 percent going to background processes, the unmetered
SoC fabric, and idle power.

## The Phase Partition and the E/T Ratio

The PHASE-PARTITION section shows how attributed energy distributes across
the four workflow phases: planning, execution, synthesis, and inter-phase
coordination. The inter-phase residual is energy consumed between named phase
boundaries — the time when the orchestration layer is scheduling the next
step, checking tool outputs, routing results, and staging the next prompt.

The E/T ratio shown for each phase is the energy fraction divided by the
time fraction. A ratio above 1.0 means the phase consumes disproportionate
energy relative to its duration (compute-intensive). A ratio below 1.0 means
the phase runs mostly idle relative to the energy it would consume if it
were compute-intensive throughout.

On GN100 running Mistral-7B with vLLM, the named phases (planning, execution,
synthesis) all show E/T ratios around 0.1, meaning they consume far less
energy than their duration would suggest if they were compute-intensive.
The inter-phase coordination window shows an extremely high E/T ratio
(over 2000x on some runs) because it concentrates a large fraction of the
energy in a very short time window. This is the scheduling and dispatch cost
of the orchestration layer: it does a burst of CPU and GPU work in a few
milliseconds to set up the next step.

This finding matters for system designers. If you want to reduce the energy
cost of an agentic workflow, the named phases are not the primary target.
The inter-phase transitions are where the energy is concentrated, and reducing
orchestration overhead (faster tool dispatch, fewer round trips, batched
scheduling) has more impact than reducing time in any named phase.

A resolution warning appears when the shortest named phase is less than
twice the sampling interval. On GN100 with 10Hz SPBM, a phase shorter than
200ms cannot be reliably measured at the phase boundary level. The energy
total for that phase is still valid (it is the integral of the sampling
interval that overlaps the phase window), but the exact boundary timing is
uncertain by up to one sample interval. This does not invalidate the phase
result; it provides context for interpreting the precision of the number.

## What DATA MISSING Means

When the validator shows DM (data missing) on the ACTIVITY-DECOMP check,
it means the energy_attribution_etl.py has not run for that experiment.
The E_llm_window value is zero not because the LLM consumed no energy
but because the ETL that computes it from LLM call timestamps has not
been executed. Run the ETL and revalidate. This distinction matters: a
zero is not the same as a fact.

Similarly, a DM on GOAL-AGGREGATION means the goal_execution ETL has not
linked attempt energies to goal totals. The run-level attribution is valid
but the goal-level rollup is incomplete.

## Cross-Platform Comparability

When comparing results across platforms, pay attention to which measurement
layer each metric comes from. The attributed_energy_uj on x86 comes from
RAPL package energy times cpu_fraction: it includes CPU cores, uncore
logic, and DRAM. The attributed_energy_uj on ARM GN100 comes from SPBM
cpu_p + cpu_e times cpu_fraction: it includes only CPU performance and
efficiency cores, not the GPU. Comparing these numbers directly would be
comparing different physical quantities.

For cross-platform comparison, use either the pkg_energy_uj (total package
energy from ML1, available on both platforms) or the EpG metric (Energy per
Goal, which aggregates at the goal level and includes GPU energy via
gpu_total_energy_uj). The EpG metric is designed for cross-platform
comparison and its definition is stable across platforms.

## Summary for Paper Results

When reporting a result from A-LEMS data in a paper:

Check that ML1-INT, ML0-ML1, and ML1-ML2 all pass for the experiments you
are citing. A failure on any of these means the measurement has an
unresolved data integrity issue and the run should not be cited.

Check that IDLE-SPLIT and PROC-ATTR both pass. These ensure the baseline
subtraction and process attribution are mathematically consistent.

Check that ACTIVITY-DECOMP shows OK, not DM. If it shows DM, run
energy_attribution_etl.py and revalidate before using activity-level
decomposition numbers.

For phase-level results (planning, execution, synthesis, inter-phase),
check PHASE-PARTITION passes and that phase_coverage_pct is above 90
percent. Low phase coverage means the sampling rate missed a significant
fraction of the phase boundaries.

Use runs with HIGH confidence on all checks for headline numbers. MEDIUM
confidence is acceptable for aggregate results across many runs. LOW
confidence runs should not be used for individual run citations.

Report the conservation residuals alongside your results when they add
context. A reader who knows the ML1-INT residual on GN100 is consistently
31 percent understands that the 31 percent is structural overhead, not
measurement error, and can interpret the per-domain results accordingly.
