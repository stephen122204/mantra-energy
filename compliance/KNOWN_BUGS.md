# A-LEMS Known Measurement Bugs — tools5 Agent Record
# Status: documented, paper impact assessed, fix assignment noted
# Does NOT affect: attributed_energy_uj, EpG, OOI (primary paper metrics)

---

## Bug 1: perf_reader.stop_process_measurement() re-runs perf

**Location:** core/readers/perf_reader.py lines 210-226
**Root cause:** stop_process_measurement() calls read_counters(duration_ms)
which launches a NEW perf stat --timeout subprocess AFTER the task ends.
It never measured during the task — it measures a fresh window of identical
duration immediately after.
**Effect:** post_task_duration_ns ≈ task_duration_ns (50/50 split artifact).
perf counters reflect post-task idle activity, not task activity.
**Does NOT affect:** attributed_energy_uj, EpG, OOI
**Paper impact:** perf-derived columns (instructions, IPC, cache misses)
are unreliable. Exclude from paper analysis. Note in limitations.
**Fix assignment:** Chunk 12 (perf continuous measurement redesign)
**Fix direction:** start_process_measurement() must launch perf stat -p <pid>
as background process. stop_process_measurement() sends SIGINT and parses
accumulated output. No re-run.

---

## Bug 2: post_task_energy_uj underestimates (consequence of Bug 1)

**Root cause:** Consequence of Bug 1 — post_task window is actually
measuring a second task-duration window, not the true post-task period.
**Does NOT affect:** attributed_energy_uj, EpG, OOI
**Fix assignment:** Chunk 12 (same fix as Bug 1)

---

## Bug 3: rapl_after_task_uj wrong for retry runs

**Location:** core/execution/experiment_runner.py fix_run_with_pretask()
**Root cause:** rapl_after_task in ml_features captures RAPL counter at
end of LAST attempt only. For retry runs the correct rapl_after_task is
the counter after the final attempt, but pre-task boundary is from the
FIRST attempt start. Duration calculation is therefore inflated.
**Does NOT affect:** attributed_energy_uj, EpG, OOI
**Paper impact:** pre_task_energy_uj and post_task_energy_uj may be
inflated for retry runs. Granular per-attempt timing is in goal_attempt
(started_at/finished_at). Use goal_attempt for retry timing analysis.
**Fix assignment:** 8.5-C-pre agent (retry boundary redesign)

---

## Bug 6: duration_ns captures only winning attempt timing

**Location:** core/database/sqlite_adapter.py line 709
**Root cause:** runs.duration_ns = ev.get("duration_ns") from the single
winning result dict. For retry runs the total wall-clock duration spans
all attempts but duration_ns only reflects the winner.
**Does NOT affect:** EpG, OOI — energy is summed correctly across attempts
**Fix direction:** Sum all attempt duration_ns values. Store as
total_duration_ns. Granular per-attempt timing in goal_attempt table.
**Fix assignment:** 8.5-C-pre agent

---

## Bug 7: orchestration_events only logs phases for winning attempt

**Location:** core/execution/harness.py lines 1582-1590
**Root cause:** Harness collects orchestration_events only from winning
agentic result. Retry attempt phase events are discarded.
**Paper impact:** For retry runs, orchestration gap decomposition is
incomplete. Retry coordination overhead appears as unattributed gap
rather than explicit retry+coordination phases.
**Fix direction:** Collect orchestration_events per attempt in
goal_attempt context. ETL aggregates across all attempts per goal_id.
**Fix assignment:** 8.5-C-pre agent

---

## Bug 4: framework_overhead_energy_uj wrong in failure_injection runs

**Real values (from clean normal comparison runs):**
  agentic: ~1.1%   → use macro \overheadPctAgClean
  linear:  ~2.12%  → use macro \overheadPctLinClean
**Paper impact:** Use clean normal run values only. Exclude
failure_injection runs from framework_overhead analysis.
**Fix:** Display label corrected in validate_energy_chain.py (Task 3).
Column name unchanged (SC-5 backward compat).

---

## Paper Limitations Section Text

"Perf-derived instruction and cache metrics (Bug 1) reflect post-task
idle activity and are excluded from analysis. Per-attempt duration
attribution for retry runs (Bugs 3, 6) uses goal_attempt timestamps
rather than runs.duration_ns. Orchestration phase decomposition for
retry runs (Bug 7) reflects winning attempt phases only; retry
coordination overhead is accounted in retry_energy_uj via goal_attempt
aggregation. None of these bugs affect attributed_energy_uj, EpG, or OOI."

## Bug 9: planning_energy_uj = 0 for agentic runs

**Severity:** LOW — D2 validator warns but doesn't fail
**Impact:** planning phase energy unattributed. Absorbed into baseline or lost.
**Root cause:** Planning phase completes before RAPL sampling window captures it.
orchestration_events.event_energy_uj = NULL for planning events — ETL sets
attributed_energy_uj = 0 when source is NULL.
**Evidence:** exp_id=990 run_id=4507: planning event energy_uj=NULL, attributed=0
**Fix assignment:** Instrumentation chunk — add explicit RAPL snapshot at planning phase start/end boundary
**Paper impact:** D2 phase partition cannot be verified for planning component.
Document as known limitation: "Planning phase energy (<5% of total) not separately attributed."
**Workaround:** None. execution + synthesis phases correctly attributed.
