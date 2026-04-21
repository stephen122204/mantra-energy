# How to Add a Provider

## Step 1 — Add to models.yaml

```yaml
providers:
  new_provider:
    provider_meta:
      is_local:            false         # true only if runs on THIS host
      access_method:       api_http      # api_http | direct_file | local_process
      network_type:        internet      # none | loopback | internet
      captures_network_io: true
      energy_side:         client_only   # full | client_only
      openai_compat:       true          # speaks /chat/completions format?
      base_url:            https://api.newprovider.com/v1
      api_key_env:         NEW_PROVIDER_API_KEY
      cost_class:          paid          # free | paid | metered
      priority:            8
      rate_limit_tpm:      null
    defaults:
      temperature: 0.7
      max_tokens: 2048
    models:
      - id: model-name
        name: Model Human Name
        tasks: [text-generation]
        modes: [linear, agentic]
        tools_supported: true
```

## Step 2 — Create Adapter (if needed)

If `openai_compat: true` → no adapter needed. `OpenAICompatAdapter` handles it.

If SDK-based (like anthropic, gemini):

```python
# core/execution/adapters/new_provider.py
from core.execution.adapters.base import TextGenABC

class NewProviderAdapter(TextGenABC):
    def __init__(self, provider_config, model_config):
        super().__init__(provider_config, model_config)
        self._api_key_env = provider_config.get("api_key_env", "")

    def get_name(self): return f"NewProviderAdapter({self.model_id})"

    def is_available(self):
        import os
        return bool(os.getenv(self._api_key_env))

    def call(self, prompt, temperature):
        # implement API call
        # return standard result dict (see base.py TextGenABC.call docstring)
        pass

    def _error_result(self, error_msg, preprocess_ms):
        phase_metrics = self._make_phase_metrics(
            total_time_ms=preprocess_ms, preprocess_ms=preprocess_ms,
            non_local_ms=0.0, local_compute_ms=0.0, postprocess_ms=0.0,
            app_throughput_kbps=0.0, cpu_percent_during_wait=0.0,
        )
        return {
            "content": f"Error: {error_msg}",
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "total_time_ms": preprocess_ms,
            "phase_metrics": phase_metrics,
            "bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0,
        }
```

## Step 3 — Register in model_factory.py

```python
# In _NON_COMPAT_CLOUD dict:
from core.execution.adapters.new_provider import NewProviderAdapter
_NON_COMPAT_CLOUD = {
    "anthropic":    AnthropicAdapter,
    "gemini":       GeminiAdapter,
    "new_provider": NewProviderAdapter,  # add this
}
```

## Step 4 — Test

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.execution.model_factory import ModelFactory
providers = ModelFactory.list_providers()
print('new_provider' in providers)
"

python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('new_provider', 'model-name')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('tokens:', result.get('tokens'))
print('error:', result.get('error'))
"
```

## Step 5 — Regression

```bash
bash scripts/test_provenance.sh
bash scripts/test_runs_regression.sh 2>&1 | grep FAIL
```
