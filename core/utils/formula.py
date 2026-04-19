#!/usr/bin/env python3
"""
================================================================================
FORMULA DECORATOR — Attach LaTeX to Compute Functions
================================================================================

Purpose:
    Attaches a LaTeX formula to any compute function as metadata.
    Seed script reads _formula_latex at deploy time and stores it in
    measurement_method_registry.formula_latex column.

    When code logic changes → developer updates @formula decorator →
    re-runs seed → DB stays in sync automatically. Zero manual config.

Usage:
    from core.utils.formula import formula

    @formula(
        latex=r"E_{pkg} = R_{end} - R_{start}",
        variables={
            "E_pkg":   "Package energy in µJ",
            "R_end":   "RAPL counter at interval end",
            "R_start": "RAPL counter at interval start",
        }
    )
    def get_energy_delta(self, start_readings, end_readings):
        ...

Seed reads it:
    fn    = getattr(reader_class, "get_energy_delta", None)
    latex = getattr(fn, "_formula_latex", "")

Author: Deepak Panigrahy
================================================================================
"""

from typing import Callable, Dict, Optional


def formula(latex: str, variables: Optional[Dict[str, str]] = None) -> Callable:
    """
    Attach LaTeX formula metadata to a compute function.

    Does not alter function behaviour in any way.
    Attaches _formula_latex and _formula_variables as function attributes.
    Seed script reads these at deploy time — never at runtime.

    Args:
        latex:     KaTeX-compatible formula string.
                   e.g. r"E_{pkg} = R_{end} - R_{start}"
        variables: Optional symbol → description map.
                   e.g. {"E_pkg": "Package energy µJ"}

    Returns:
        Decorator that tags the function without altering its behaviour.
    """
    def decorator(fn: Callable) -> Callable:
        """Attach formula metadata to the wrapped function."""
        fn._formula_latex     = latex
        fn._formula_variables = variables or {}
        return fn

    return decorator
