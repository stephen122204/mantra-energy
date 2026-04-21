# How to Add a Model

## Add to Existing Provider — 2 Lines

Edit `config/models.yaml` under the provider's `models:` list:

```yaml
providers:
  groq:
    models:
      - id: llama-3.3-70b-versatile    # existing
        name: Llama 3.3 70B
      - id: llama-3.1-70b-specdec      # NEW — add this
        name: Llama 3.1 70B SpecDec
        max_tokens: 4096               # only if different from provider default
        tools_supported: true          # only if different from provider default
```

Fields not specified inherit from `provider.defaults` then `_defaults`. Done.

## Quick Test After Adding

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('groq', 'llama-3.1-70b-specdec')
print('config:', cfg.get('model_id'), cfg.get('api_endpoint'))
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('tokens:', result.get('tokens'))
print('error:', result.get('error'))
"
```

## Add Ollama Remote Model

```bash
# First check what's available on remote VM
curl -s http://129.153.71.47:11434/api/tags | python3 -c "
import sys,json
[print(m['name']) for m in json.load(sys.stdin)['models']]
"

# Then add to models.yaml under ollama_remote:
- id: new-model:latest
  name: New Model Name
```

## Fields Reference

```yaml
id:              string  # exact model_id passed to API
name:            string  # human readable
max_tokens:      int     # override provider default
temperature:     float   # override provider default
tools_supported: bool    # supports function calling
available:       bool    # false to disable without deleting
```

For llama_cpp models, also add:
```yaml
file_params:
  model_path: /path/to/model.gguf
```

For TTS/STT models, add:
```yaml
media_params:
  voice: af_heart
  sample_rate: 24000
```
