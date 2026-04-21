"""
================================================================================
MODELS LOADER — reads models.yaml, expands defaults at runtime
================================================================================

Purpose:
    Single loader that reads the human-editable models.yaml and expands
    provider defaults + global defaults into fully resolved model configs.

    Output shape is identical to old models.json flat dicts — all consumers
    (ModelFactory, config_loader, run_single.py) see same rich structure.

No build step — expansion happens in memory at import time.
Cached after first load — zero repeated I/O.

Author: A-LEMS Chunk 7
================================================================================
"""

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Path to yaml — relative to project root
_YAML_PATH = Path(__file__).parent.parent / "config" / "models.yaml"

# Module-level cache — loaded once per process
_cache: Optional[Dict] = None


# =============================================================================
# PUBLIC API
# =============================================================================

def get_provider(provider_id: str) -> Optional[Dict]:
    """
    Get fully resolved provider config (meta + models expanded).

    Args:
        provider_id: e.g. 'groq', 'ollama_remote', 'llama_cpp'

    Returns:
        Dict with provider_meta and models list, or None if not found.
    """
    data = _load()
    return data["providers"].get(provider_id)


def get_model(provider_id: str, model_id: str) -> Optional[Dict]:
    """
    Get fully resolved flat config for one model.

    Merges: global_defaults → provider_defaults → model fields.
    Also adds provider-level meta fields (is_local, network_type, etc).
    Ready for LinearExecutor / AgenticExecutor constructors.

    Args:
        provider_id: e.g. 'groq'
        model_id:    e.g. 'llama-3.3-70b-versatile'

    Returns:
        Flat merged dict or None if not found / not available.
    """
    data = _load()
    provider_block = data["providers"].get(provider_id)
    if not provider_block:
        return None

    meta = provider_block["provider_meta"]
    model = next(
        (m for m in provider_block["models"]
         if m.get("model_id") == model_id and m.get("available", True)),
        None,
    )
    if not model:
        return None

    # Build flat dict — same shape old models.json produced
    flat = {
        "provider":            provider_id,
        "model_id":            model_id,
        "model_uid":           f"{provider_id}::{model_id}",
        # provider meta fields
        "is_local":            meta.get("is_local", False),
        "access_method":       meta.get("access_method", "api_http"),
        "network_type":        meta.get("network_type", "internet"),
        "captures_network_io": meta.get("captures_network_io", True),
        "energy_side":         meta.get("energy_side", "client_only"),
        "execution_site":           meta.get("execution_site"),
        "transport":                meta.get("transport"),
        "remote_energy_available":  meta.get("remote_energy_available", False),        
        "openai_compat":       meta.get("openai_compat", False),
        "base_url":            meta.get("base_url", ""),
        "api_key_env":         meta.get("api_key_env"),
        "env_path":            meta.get("env_path", ""),
        "cost_class":          meta.get("cost_class", "free"),
        "priority":            meta.get("priority", 99),
        "rate_limit_tpm":      meta.get("rate_limit_tpm"),
        # build api_endpoint for executor backward compat
        "api_endpoint":        _build_endpoint(meta, provider_id),
    }

    # Merge model fields (model wins on conflict)
    flat.update({k: v for k, v in model.items()
                 if k not in ("id", "file_params", "media_params", "runtime_params")})

    # Flatten nested param blocks to top level
    for param_key in ("file_params", "media_params", "runtime_params"):
        flat.update(model.get(param_key, {}))

    # model_path convenience alias for llama_cpp executor compat
    if "model_path" in model.get("file_params", {}):
        flat["model_path"] = model["file_params"]["model_path"]

    return flat


def list_providers(task: Optional[str] = None) -> Dict[str, Dict]:
    """
    List all available providers, optionally filtered by task.

    Args:
        task: e.g. 'text-generation', None = all

    Returns:
        Dict provider_id → provider block
    """
    data = _load()
    providers = data["providers"]
    if task is None:
        return providers
    # Filter providers that have at least one model supporting the task
    return {
        pid: pcfg for pid, pcfg in providers.items()
        if any(task in m.get("tasks", []) for m in pcfg.get("models", []))
    }


def list_models(provider_id: str) -> List[Dict]:
    """
    List all available models for a provider.

    Args:
        provider_id: provider key string

    Returns:
        List of expanded model dicts
    """
    data = _load()
    provider_block = data["providers"].get(provider_id, {})
    return [m for m in provider_block.get("models", []) if m.get("available", True)]


def get_backward_compat(mode: str, workflow: str) -> Optional[Dict]:
    """
    Backward compat for get_model_config(mode, workflow).

    Resolves through get_model() — same proper path as all other callers.
    _legacy_map only stores provider+model_id pointer, no duplicate config.

    Args:
        mode:     'cloud' or 'local'
        workflow: 'linear' or 'agentic'

    Returns:
        Fully resolved flat config dict or None
    """
    data = _load()
    mapping = data.get("_legacy_map", {}).get(mode, {}).get(workflow)
    if not mapping:
        return None
    # resolve through proper path — gets base_url, api_key_env, all meta fields
    result = get_model(mapping["provider"], mapping["model_id"])
    if not result:
        return None
    # apply workflow-specific overrides (max_tokens, tools_supported)
    result = dict(result)
    result.update({k: v for k, v in mapping.items()
                   if k not in ("provider", "model_id")})
    return result


# =============================================================================
# INTERNAL — load + expand
# =============================================================================

def _load() -> Dict:
    """
    Load and cache expanded models data. Reads yaml once per process.

    Returns:
        Dict with providers (expanded) and _backward_compat
    """
    global _cache
    if _cache is not None:
        return _cache   # early return — already loaded

    if not _YAML_PATH.exists():
        raise FileNotFoundError(f"models.yaml not found at {_YAML_PATH}")

    with open(_YAML_PATH, "r") as f:
        raw = yaml.safe_load(f)

    global_defaults = raw.get("_defaults", {})
    expanded_providers = {}

    for provider_id, provider_raw in raw.get("providers", {}).items():
        # Provider-level defaults override global defaults
        provider_defaults = {**global_defaults, **provider_raw.get("defaults", {})}

        # Build provider_meta — all scalar fields except 'models' and 'defaults'
        meta_keys = {k: v for k, v in provider_raw.items()
                     if k not in ("models", "defaults")}
        meta_keys["provider_id"] = provider_id

        expanded_models = []
        for model_raw in provider_raw.get("models", []):
            # Expand: provider_defaults → model overrides
            model = {**provider_defaults}
            model.update({k: v for k, v in model_raw.items() if k != "id"})

            # Normalize model_id from 'id' field
            model["model_id"] = model_raw["id"]
            model["model_uid"] = f"{provider_id}::{model_raw['id']}"
            model.setdefault("available", True)

            expanded_models.append(model)

        expanded_providers[provider_id] = {
            "provider_meta": meta_keys,
            "models": expanded_models,
        }

    _cache = {
        "providers": expanded_providers,
        "_legacy_map": raw.get("_legacy_map", {}),
    }

    logger.debug("ModelsLoader: loaded %d providers from models.yaml",
                 len(expanded_providers))
    return _cache


def _build_endpoint(meta: Dict, provider_id: str) -> str:
    """
    Build api_endpoint string for executor backward compat.

    Ollama:      base_url/api/chat
    OpenAI-compat: base_url/chat/completions
    Other:       base_url

    Args:
        meta:        provider_meta dict
        provider_id: provider key

    Returns:
        str endpoint URL
    """
    base = meta.get("base_url", "").rstrip("/")
    if not base:
        return ""
    # ollama providers use /api/chat endpoint
    if "ollama" in provider_id:
        return f"{base}/api/chat"
    if meta.get("openai_compat", False):
        return f"{base}/chat/completions"
    return base
