# What exists in the inspected A-LEMS code

Upstream: `deepakpanigrahy03/alems-platform`. Reviewed reference: `ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56`. Selected files were read; no complete build or local model execution was performed for this handoff. Inspect the team's actual chosen revision and revise this map when it differs.

| Existing path | Evidence and assignment relevance |
|---|---|
| `core/models_loader.py` | Reads `config/models.yaml`, expands defaults and caches the registry. Start here for configuration routing. |
| `config/models.yaml` | Active registry includes `ollama_local`, `vllm_local`, local/remote metadata and legacy mappings. vLLM entries include Mistral 7B and Qwen models; registration is not installation or execution proof. |
| `config/models.json` | Older registry still present. Do not change it alone and assume the active model changed. |
| `core/execution/model_factory.py` | Provider resolution and legacy remapping. Ollama and OpenAI-compatible HTTP providers route through the common adapter. |
| `core/execution/adapters/openai_compat.py` | HTTP payloads, stream parsing, request timing and response normalization. First runtime defect investigation belongs here. |
| `core/execution/agentic.py` | Existing planning/tool execution; imports instrumented real tools. `execute(..., tool_graph=...)` accepts a graph-like list but the inspected main execution loop is sequential. This is not a ready general concurrent DAG engine. |
| `core/execution/harness.py` | Measurement orchestration, execution endpoints and result persistence. Shared integration surface: coordinate edits. |
| `core/energy_engine.py` | Collection lifecycle and energy snapshots. Inspect endpoint timing, perf fallback and shutdown ordering. |
| `core/readers/perf_reader.py`, `core/readers/interfaces.py` | Reader interfaces and perf-backed acquisition; permissions and timing require node-side testing. |
| `core/thermal/thermal_reader_v2.py`, `thermal_writer_v2.py`, `thermal_discovery.py` | Existing thermal stack; extend timing/quality semantics rather than create a second collector. |
| `core/database/schema.py` | Existing goal, attempt, LLM-interaction and thermal records. Prefer additive sidecar exports before changing production schema. |
| `core/execution/failure_injector.py` | Existing deterministic validation injection. It is not the proposed diagnostic selector or a complete retry experiment. |

## Concrete issues to reproduce

1. **Ollama stream mismatch.** At the reviewed adapter, `_endpoint_url` chooses `/api/chat` for Ollama. `_http_call` forces streaming and reads only SSE lines beginning `data:`, interprets OpenAI `choices`, and reconstructs that response shape. `_parse_response` then expects Ollama `message.content`. Standard Ollama streaming needs a compatible parser. Test empty content, terminal token counts, errors and tool-plan data. Do not claim a reproduced failure until a fixture/live test shows it. Inspect how agent planning encodes tool requests; do not assume native function calling is already wired because registry flags say tools are supported.
2. **Token/timing fidelity.** The Ollama response path estimates tokens with whitespace splitting at this baseline. Preserve actual API token counters where exposed and label estimates. Non-streaming round-trip time is not measured TTFT. Do not silently make a second model call after partial streaming without recording its work and energy.
3. **Locality classification.** The harness contains an `is_cloud` check comparing the provider to the literal `ollama`, while the registry/factory use richer provider names. Trace whether this affects the selected execution path. Locality must follow actual execution location, not merely adapter family.
4. **Endpoint ordering.** Reviewed harness paths record task completion before stopping measurement, but take some energy endpoints after stop. Energy-engine shutdown can stop perf before the endpoint snapshot. A duration-dependent perf fallback may extend the interval. Test with deliberately delayed teardown; do not assert every run has inflated energy.
5. **Clock and invalid-sample semantics.** Several collector paths use epoch `time.time_ns()`, with serial sensor reads and quality flags. Add monotonic acquisition brackets while retaining wall-clock anchors and original source values. Unsupported/invalid numeric values must not become real zero observations.
6. **Independent correctness.** Execution status and goal/attempt bookkeeping exist, but they do not replace an independent task verifier. Preserve status, verifier result and measurement validity as separate fields.

## Reuse and extension boundary

Keep A-LEMS as the execution/measurement base. Introduce a small study-specific namespace for task adapters, contracts, replay, runner and analysis after checking repository conventions. Do not invent names that collide with existing modules. Student 2 owns the bounded tool/dependency executor; Student 3 owns its campaign invocation. Stephen owns the diagnostic algorithm and cross-module schema decisions.

The supplied `starter/make_run_plan.py` and `starter/campaign.json` are a copied planning utility and an unfilled template. They do not execute workloads, acquire telemetry or enforce runtime isolation. `goal_thermal_schema.sql` in the older review was a draft analysis schema, not an installed production migration; do not apply it as part of setup.

## Source anchors

- [Loader](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/core/models_loader.py)
- [Active registry](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/config/models.yaml)
- [Adapter](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/core/execution/adapters/openai_compat.py)
- [Agent executor](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/core/execution/agentic.py)
- [Harness](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/core/execution/harness.py)
- [Energy engine](https://github.com/deepakpanigrahy03/alems-platform/blob/ce8e299a7322849fc6a94a3b2f21ad04ff4fdd56/core/energy_engine.py)

