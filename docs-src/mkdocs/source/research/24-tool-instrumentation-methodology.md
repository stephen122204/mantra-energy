# Tool Instrumentation Methodology

## Scope

This document covers tool execution implementations, resource measurement,
and the three-tier task architecture. For failure injection design and retry
policy see `22-retry-tool-failure-methodology.md`. For energy attribution ETL
and research views see `20-tool-failure-methodology.md`.

---

## Tool Architecture

Tools are energy-instrumented execution primitives. They do not own energy
measurement. Each tool captures resource metadata (CPU time, memory delta,
I/O bytes) and emits it into `_emit_event()`, which creates an
`orchestration_events` row. The existing `phase_attribution_etl` pipeline
then attributes energy to that event based on RAPL counter deltas during
the event window.

```
Tool executes
    → captures: start_time, end_time, io_bytes, payload_hash, cpu_time_ns
    → calls _emit_event(phase='execution', event_type='tool_call')
    → orchestration_events row created with tool_* columns (migration 035)
    → phase_attribution_etl attributes energy to this event
    → tool_failure_events row created if failed
```

---

## Three-Tier Task Architecture

### Tier 1 — Standard Benchmarks

Real datasets (GSM8K, HumanEval, TriviaQA) loaded from HuggingFace via
`BenchmarkLoader`. Exact sample IDs recorded in `tasks.yaml` — same ID
produces the same prompt and expected answer across all runs, providers, machines.

Evaluation: deterministic judges only (exact match, unit test). No LLM
judges for Tier 1. Ensures external validity — results comparable with
published benchmark scores.

### Tier 2 — Controlled Tool Graph Tasks

Fixed graph topology in `tasks.yaml`. LLM generates tool arguments dynamically
but cannot change graph structure. This separates graph structure (our paper
variable) from model capability (controlled).

SQL guardrails for `DatabaseQueryTool`:
- SELECT-only whitelist
- Table/view whitelist: 8 tables + 3 research views
- `MAX_JOIN_DEPTH=2` — prevents non-deterministic query plans

### Tier 3 — No-Tool Baseline

Zero tool calls. Pure inference energy baseline. The difference between
Tier 3 and Tier 2 energy directly quantifies orchestration overhead.

---

## Tool Implementations

### DatabaseQueryTool

Real SQLite queries against `experiments.db`. `sqlparse` AST validation
before execution. `LIMIT 100` injected. 5s timeout.
Measures: rows returned, I/O bytes, CPU time.

### FileProcessorTool

Real file I/O bounded to `data/test_files/`. Path traversal blocked via
absolute path resolution before any I/O. 1MB max file size.
Measures: bytes read, bytes written, CPU time.

### WebSearchTool

Real HTTP GET to local stub server (`localhost:8765`). Not real web search.

**Paper framing**: "We implement a controlled information retrieval primitive
that issues real HTTP requests to a local deterministic endpoint. This design
provides real network I/O timing and energy attribution while maintaining
experimental reproducibility. We explicitly do not claim this represents
real-world web search energy — it represents the orchestration cost of an
information retrieval tool call."

### CodeExecutorTool

`subprocess` sandbox, 10s timeout. AST validation blocks: `os`, `sys`,
`subprocess`, `socket`, `shutil`, `pathlib`, `importlib`, `ctypes`.

**Paper framing**: "Code execution is sandboxed via subprocess with explicit
resource limits. No system calls, file I/O, or network access are permitted
inside the sandbox. This ensures security and measurement validity — all
energy consumption is attributable to computation only."

### CalculatorTool

`sympy.sympify` — safe symbolic math. No `eval()`. Replaces hardcoded stub.

### APIQueryTool

Real HTTP GET to stub server (`localhost:8765`).
Endpoints: `/metrics`, `/energy_summary`, `/health`.
Measures: bytes sent, bytes received, latency.

---

## Parallel Tool Graph Execution

Steps declared as parallel (`depends_on=[]`) execute sequentially.

**Paper justification**: "Tool graph steps declared as parallel execute
sequentially in our instrumentation environment. This design ensures precise
per-tool energy attribution without interference between concurrent processes.
Our measurements represent an upper bound on orchestration energy for
parallel-capable deployments."

---

## Stub Server

FastAPI stub (`core/execution/tools/stub_server.py`) on `localhost:8765`.
Started as daemon thread before any Tier 2 experiment. Returns deterministic
responses from live `experiments.db` — non-trivial, representative content.

---

## Resource Measurement Pattern

Every tool:

```
before = _get_resource_snapshot()   # CPU ns + VmRSS KB
... execute tool ...
after  = _get_resource_snapshot()
result.cpu_time_ns     = after.cpu_ns - before.cpu_ns
result.memory_delta_kb = max(0, after.vmrss_kb - before.vmrss_kb)
```

CPU: `resource.getrusage(RUSAGE_SELF)` — Linux and macOS.
Memory: `/proc/self/status` VmRSS — Linux only, 0 on macOS (documented).

---

## Failure Injection — Validation Test

For full injection methodology see `22-retry-tool-failure-methodology.md`.

Before any paper run using failure injection, validate the injector:

```python
from core.execution.failure_injector import FailureInjector, _evenly_spaced_slots

# Verify slot spacing — must be evenly distributed, not clustered
assert sorted(_evenly_spaced_slots(6, 2)) == [2, 4], \
    "Slot algorithm broken — check _evenly_spaced_slots()"

# Verify deterministic mode produces exactly N failures
fi = FailureInjector(
    {'enabled': True, 'mode': 'deterministic_validation',
     'min_failures': 2, 'total_draws_estimate': 6},
    'failure_injection'
)
fi.set_exp_id(999, total_draws=6)
for rep in range(1, 4):
    for att in range(1, 3):
        fi.maybe_inject_timeout(rep, att)

summary = fi.injection_summary()
planned  = summary['by_kind']['timeout']['planned_failures']
realized = summary['by_kind']['timeout']['realized_failures']
assert planned == realized, \
    f"Injection schedule not met: planned={planned} realized={realized}. " \
    f"Increase repetitions or fix total_draws_estimate."
print("Injector OK — schedule:", summary['by_kind']['timeout']['schedule'])
```

Expected output: `Injector OK — schedule: [2, 4]`

---

## Provenance

All tool instrumentation columns on `orchestration_events` are attributed to
`tool_instrumentation_v1` — MEASURED directly during tool execution, not ETL-derived.

| Column | Method | Type |
|---|---|---|
| `oe.tool_name` | `tool_instrumentation_v1` | MEASURED |
| `oe.io_bytes_read` | `tool_instrumentation_v1` | MEASURED |
| `oe.io_bytes_written` | `tool_instrumentation_v1` | MEASURED |
| `oe.input_payload_hash` | `tool_instrumentation_v1` | MEASURED |
| `oe.output_payload_hash` | `tool_instrumentation_v1` | MEASURED |
| `oe.tool_success` | `tool_instrumentation_v1` | MEASURED |
| `oe.tool_result_rows` | `tool_instrumentation_v1` | MEASURED |
| `oe.tool_cpu_time_ns` | `tool_instrumentation_v1` | MEASURED |
| `oe.tool_memory_delta_kb` | `tool_instrumentation_v1` | MEASURED |
