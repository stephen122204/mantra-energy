# Model Factory Architecture — Chunk 7

## Overview

Chunk 7 introduced a centralized model dispatch system replacing scattered
if/else provider chains in `linear.py` and `agentic.py`.

## Architecture

```
models.yaml          human-editable, ~150 lines, defaults inherited
    ↓
models_loader.py     expands defaults at runtime, cached per process
    ↓
config_loader.py     get_model_config_v2(provider, model_id) → flat dict
                     get_model_config("cloud","linear") still works via _legacy_map
    ↓
ModelFactory         get_adapter(provider, flat_config) → adapter instance
    ↓
Adapter              call(prompt, temperature) → standard result dict
    ↓
LinearExecutor       _execute_provider() delegates to adapter
AgenticExecutor      _call_llm() delegates to adapter
```

## Provider Ontology

```
PROVIDER         IS_LOCAL  NETWORK    ENERGY_SIDE    ACCESS_METHOD
ollama_local     true      loopback   full           api_http
ollama_remote    false     internet   client_only    api_http
groq             false     internet   client_only    api_http
openai           false     internet   client_only    api_http
anthropic        false     internet   client_only    api_http
gemini           false     internet   client_only    api_http
deepseek_cloud   false     internet   client_only    api_http
llama_cpp        true      none       full           direct_file
kokoro           true      none       full           local_process
indic_parler     true      none       full           local_process
indic_f5         true      none       full           local_process
faster_whisper   true      none       full           local_process
```

Key definitions:
- `is_local`: true ONLY if workload executes on THIS measured host (UBUNTU2505)
- `ollama_remote` = false — runs on Oracle VM, unmeasured server energy
- `energy_side`: full = client+server same machine, client_only = remote inference

## Adapter Dispatch Logic

```python
# model_factory.py
access_method == "direct_file"   → LlamaCppAdapter
access_method == "local_process" → KokoroAdapter / IndicParlerAdapter / etc
access_method == "api_http"
    openai_compat == true        → OpenAICompatAdapter (groq, openai, ollama*)
    provider == "anthropic"      → AnthropicAdapter
    provider == "gemini"         → GeminiAdapter
```

## Standard Adapter Return Dict

Every adapter's `call()` returns:

```python
{
    "content":        str,
    "tokens":         {"prompt": int, "completion": int, "total": int},
    "total_time_ms":  float,
    "phase_metrics":  {
        "total_time_ms":           float,
        "preprocess_ms":           float,
        "non_local_ms":            float,   # 0 for local
        "local_compute_ms":        float,   # 0 for cloud
        "postprocess_ms":          float,
        "app_throughput_kbps":     float,
        "cpu_percent_during_wait": float,
        "ttft_ms":                 None,    # Chunk 4
        "tpot_ms":                 None,    # Chunk 4
    },
    "bytes_sent":      int,
    "bytes_recv":      int,
    "tcp_retransmits": int,
}
```

## New DB Columns

```sql
runs.ttft_ms   REAL DEFAULT NULL  -- time-to-first-token, Chunk 4 streaming
runs.tpot_ms   REAL DEFAULT NULL  -- time-per-output-token, Chunk 4 streaming
```

Migration: `scripts/migrations/v11_chunk7_ttft.sql`
