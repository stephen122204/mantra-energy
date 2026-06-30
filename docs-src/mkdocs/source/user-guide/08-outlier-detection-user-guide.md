# Using Outlier Detection

This page is for researchers deciding which A-LEMS data to use for an
analysis. If you want the schema reference, query examples, and
verification steps instead, see
[Outlier Detection Methodology](../research/32-outlier-detection-methodology.md).

## The short version

A-LEMS now tracks two separate things about every run, beyond whether the
experiment itself was a real run (Layer 1) and whether the hardware
sampling was healthy (Layer 2):

1. **Is this value unusual for its kind?** (statistical, Layer 3)
2. **Is this value trustworthy at all?** (data quality, also Layer 3)

These are different questions, and a run can answer them differently for
different columns. The rest of this page is about how to pick the right
view of the data for what you're trying to do.

## The one rule: replace FROM runs

Every paper query you write today probably starts with:

```sql
SELECT ...
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE e.is_valid = 1
```

From now on, replace `FROM runs r` with the view that matches your
analysis. Nothing else in your query changes:

```sql
-- BEFORE: raw table, includes Bug 8 runs, broken measurements,
-- extreme outliers, everything
SELECT r.run_id, e.task_name, r.total_energy_uj, r.attributed_energy_uj
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE e.is_valid = 1

-- AFTER: clean energy analysis, one word change
SELECT r.run_id, e.task_name, r.total_energy_uj, r.attributed_energy_uj
FROM v_runs_clean_energy r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE e.is_valid = 1
```

That single substitution on UBUNTU2505 drops you from 5255 raw runs to
2122 clean energy runs automatically, with the 4 Bug 8 runs (confirmed
`data_quality_failure`, `framework_overhead_energy_uj` inflated by
orders of magnitude due to RAPL boundary capture outside the run) and
the confirmed statistical extremes excluded silently.

For LLM latency analysis:

```sql
FROM v_runs_clean_llm r
```

For CPU microarchitecture analysis:

```sql
FROM v_runs_clean_cpu r
```

For worst-case / tail analysis where you want the extreme-but-real runs:

```sql
FROM v_runs_measured_energy r
```

For raw debugging with no filtering at all:

```sql
FROM v_runs_unfiltered r
```

Never use `FROM runs r` for paper results. Use it only when you
specifically need to see raw unfiltered data, and use `v_runs_unfiltered`
even then, since it attaches layer verdicts as extra columns so you can
see why each run is or isn't excluded.



A run can have good energy data and good LLM interaction data, but an
unexpected CPU frequency reading. That run should not be unusable for an
energy analysis just because something unrelated to energy was off.

A-LEMS now handles this correctly. The CPU frequency anomaly is recorded
against the `cpu_perf` domain only. An energy analysis querying
`v_runs_clean_energy` never sees that flag, because energy measurement
and CPU frequency sampling are different things. A CPU microarchitecture
analysis querying `v_runs_clean_cpu` does exclude that run, because that
is exactly the kind of anomaly a CPU analysis needs to know about.

## Picking a view

Every view name has two parts: a tier and a domain.

```
v_runs_<tier>_<domain>
```

### Domains: what kind of analysis are you doing?

| Domain | Use it for |
|---|---|
| `energy` | EpG, total energy, power, environmental impact (carbon/water/methane) |
| `gpu_energy` | GPU-specific energy (DCGM, SPBM GPU rail) |
| `cpu_perf` | IPC, cache behavior, CPU frequency, microarchitecture |
| `thermal` | Temperature, throttle events |
| `llm_perf` | Token counts, latency, TTFT/TPOT |
| `orchestration` | Steps, tool calls, agent CPU time |
| `system` | OS scheduling, memory, swap, network, disk I/O |

If your analysis doesn't fit one of these cleanly, or spans more than
one, query `run_outliers` directly with the specific metrics you care
about rather than reaching for a pre-built view. The view list is a
convenience for the common cases, not the only way to query this data.

### Tiers: how strict should exclusion be?

| Tier | Excludes | Use it for |
|---|---|---|
| `clean` | Confirmed outliers of **either** kind: bad data AND unusual-but-real data | Mean, CV, EpG averages, anything where you want a representative dataset and don't want a few extreme (but real) runs skewing the average |
| `measured` | Confirmed bad data only. Keeps unusual-but-real runs. | Studying the full distribution, tail behavior, worst-case or best-case arguments, robustness claims |

`clean` is the conservative default. Use it unless you have a specific
reason to want the unusual-but-real runs included.

`measured` is for when the unusual values ARE the thing you're studying.
If you're writing a robustness section in a paper and want to show your
system's worst-case energy behavior, you want the run that genuinely
used far more energy than its peers, not a dataset that has already
thrown that run away.

### Examples

```sql
-- Average energy per goal, representative dataset, exclude both bad
-- data and statistical extremes
SELECT AVG(total_energy_uj) FROM v_runs_clean_energy;

-- Same question, but you want to see the real worst case too
SELECT MAX(total_energy_uj) FROM v_runs_measured_energy;

-- CPU microarchitecture analysis, separate from energy concerns
SELECT AVG(ipc), AVG(cache_miss_rate) FROM v_runs_clean_cpu;

-- LLM latency analysis. Note: a run with bad energy sample coverage
-- still shows up here, because LLM measurement doesn't depend on the
-- energy sampler.
SELECT AVG(ttft_ms), AVG(tpot_ms) FROM v_runs_clean_llm;
```

## Why a coverage problem can still leave a run usable

Some columns (`energy_sample_coverage_pct`, `spbm_sample_coverage_pct`,
and a few others) describe how complete the hardware sampling was during
a run. These are special: if sampling was incomplete, it doesn't just
affect one number, it affects every measurement that depended on that
same sampling pass.

This is why a coverage problem excludes a run from `v_runs_clean_energy`,
`v_runs_clean_cpu`, `v_runs_clean_thermal`, and `v_runs_clean_system`
(all of which depend on the same RAPL/SPBM samples), but does NOT
exclude it from `v_runs_clean_llm` or `v_runs_clean_orchestration`. LLM
client instrumentation and the orchestration framework measure
themselves independently of the energy sampler, so a bad energy sampling
pass says nothing about whether the LLM latency numbers from that same
run are trustworthy.

If you query `runs` directly (not through any `v_runs_*` view) and
wonder why a run looks fine in one analysis but gets excluded in
another, this is almost always why: the run has a confirmed issue in a
domain your current analysis doesn't actually depend on, or does.

## What "confirmed" means, and why nothing is excluded automatically

The detection script (`compute_outliers.py`) only ever flags candidates.
It writes rows with `review_status = 'pending'`. A pending row does NOT
exclude a run from any view. Only a row a human has explicitly marked
`review_status = 'confirmed'` does that.

This means running detection is safe to do at any time, repeatedly, and
will never silently change what data you're working with. Someone has to
look at a flagged run and decide it's real before it affects any
analysis.

If you are the one reviewing flagged runs: look at `run_outliers` for
rows with `review_status = 'pending'`, check whether the flagged value
makes sense given everything else you know about that run, and update
`review_status` to `confirmed` (if you agree it's a real anomaly worth
excluding) or `dismissed` (if you think the detector got it wrong, for
example a population that's naturally bimodal and the statistical method
isn't accounting for that). Always fill in `reviewed_by` and
`review_note` when you do this, so the next person (or the next version
of yourself) knows why a decision was made.

## What if I want everything, no filtering at all?

`v_runs_unfiltered` shows every run with every layer's verdict attached
as extra columns, but excludes nothing. Use this for debugging, or when
you specifically need to see what the detection system thinks about a
run without it affecting what data you're looking at.

## Reporting exclusions in a paper

If you used a `clean` or `measured` view (or any manual exclusion based
on `run_outliers`) for results going into a paper, the methodology
section needs to say so, with separate counts for data quality
exclusions and statistical exclusions. These are different claims to a
reviewer: "we excluded N runs because the measurement was broken" is a
different statement than "we excluded M runs because they were extreme
but real."

```sql
-- Counts for a methodology section
SELECT outlier_class, COUNT(DISTINCT run_id)
FROM run_outliers
WHERE review_status = 'confirmed'
GROUP BY outlier_class;
```
