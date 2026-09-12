"""Shared executor-boundary validation for structured adapter results."""

from typing import Any, Dict


class AdapterCallError(RuntimeError):
    """Adapter-reported failure with the original diagnostics attached."""

    def __init__(self, result: Dict[str, Any]):
        self.result = result
        super().__init__(result.get("error") or "adapter call failed")


def require_adapter_success(result: Dict[str, Any]) -> Dict[str, Any]:
    """Raise for a structured adapter failure; pass successful results through."""
    if result.get("status") == "error":
        raise AdapterCallError(result)
    return result
