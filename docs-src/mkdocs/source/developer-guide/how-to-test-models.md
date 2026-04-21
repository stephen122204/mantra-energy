# How to Test Models Individually

## Quick Adapter Test (no DB write)

```bash
# Test any provider+model directly
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('PROVIDER', 'MODEL_ID')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('tokens:', result.get('tokens'))
print('api_latency_ms:', result.get('api_latency_ms'))
print('error:', result.get('error'))
"
```

## All Providers — Copy/Paste Test Commands

```bash
# groq
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('groq', 'llama-3.3-70b-versatile')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('GROQ tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# ollama_remote
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('ollama_remote', 'phi4:latest')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('OLLAMA_REMOTE tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# ollama_local
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('ollama_local', 'tinyllama-1b')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('OLLAMA_LOCAL tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# llama_cpp
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('llama_cpp', 'tinyllama-1b-gguf')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('LLAMA_CPP tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# anthropic
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('anthropic', 'claude-sonnet-4-5')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('ANTHROPIC tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# gemini
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('gemini', 'gemini-2.0-flash')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('GEMINI tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# openai
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('openai', 'gpt-4o-mini')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('OPENAI tokens:', result.get('tokens'), 'error:', result.get('error'))
"

# deepseek_cloud
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.linear import LinearExecutor
config = ConfigLoader()
cfg = config.get_model_config_v2('deepseek_cloud', 'deepseek-chat')
ex = LinearExecutor(cfg)
result = ex.execute('What is 2+2?')
print('DEEPSEEK tokens:', result.get('tokens'), 'error:', result.get('error'))
"
```

## Full Experiment Run (with DB write + energy measurement)

```bash
# local provider
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 1 \
    --provider local --save-db --verbose 2>&1 | tail -10

# cloud provider
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 1 \
    --provider cloud --save-db --verbose 2>&1 | tail -10
```

## List All Providers and Models

```bash
python3 -c "
from core.execution.model_factory import ModelFactory
for pid, pcfg in ModelFactory.list_providers().items():
    meta = pcfg['provider_meta']
    models = [m['model_id'] for m in pcfg['models']]
    print(f'{pid}: is_local={meta[\"is_local\"]} models={models}')
"
```

## Check Adapter Availability

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from core.config_loader import ConfigLoader
from core.execution.model_factory import ModelFactory
config = ConfigLoader()
for provider in ['groq','ollama_remote','ollama_local','llama_cpp','anthropic','gemini']:
    models = ModelFactory.list_models(provider)
    if models:
        cfg = config.get_model_config_v2(provider, models[0]['model_id'])
        adapter = ModelFactory.get_adapter(provider, cfg)
        print(f'{provider}: available={adapter.is_available()} name={adapter.get_name()}')
"
```

## run_single.py CLI

```bash
# List everything
python scripts/run_single.py --list

# Single model run
python scripts/run_single.py \
    --provider ollama_remote --model qwen2.5-coder:14b \
    --mode linear --task gsm8k_basic --repetitions 3

# Both modes
python scripts/run_single.py \
    --provider groq --model llama-3.3-70b-versatile \
    --mode both --task gsm8k_basic

# Cross-provider comparison
python scripts/run_single.py \
    --compare ollama_remote:qwen2.5-coder:14b groq:llama-3.3-70b-versatile \
    --mode linear --task gsm8k_basic --repetitions 3
```

## Verify DB After Run

```bash
# Check last 4 runs populated correctly
sqlite3 data/experiments.db "
SELECT run_id, workflow_type, total_tokens, api_latency_ms,
       energy_sample_coverage_pct, l2_cache_misses_total
FROM runs ORDER BY run_id DESC LIMIT 4;"
```
