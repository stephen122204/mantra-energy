"""
core/ontology_registry.py
─────────────────────────
Platform-level scientific taxonomy authority for A-LEMS.

GOVERNANCE RULES
────────────────
- This file is the single source of truth for all open-text taxonomy fields.
- Adding a new value requires a PR with rationale. No unilateral additions.
- Each set is versioned. Papers record which version was active at collection time.
- ETL scripts validate against these sets before any DB insert. Reject, never coerce.
- New measurement approaches must also register a method_id in provenance.py.

TAXONOMY FIELDS GOVERNED HERE
──────────────────────────────
- hallucination_events.hallucination_type  → HALLUCINATION_TYPES
- hallucination_events.detection_method    → DETECTION_METHODS
- goal_execution.goal_type                 → CATEGORY_TO_GOAL_TYPE (config/category_to_goal_type.yaml)

FIELDS NOT GOVERNED HERE (use CHECK constraints in schema)
──────────────────────────────────────────────────────────
- experiment_type       → schema.py VALID_EXPERIMENT_TYPES
- metric_type           → output_quality CHECK constraint
- judge_method          → output_quality CHECK constraint
- score_method          → output_quality CHECK constraint
- workflow_type         → goal_execution CHECK constraint
- outcome               → goal_attempt CHECK constraint
"""

from typing import FrozenSet


# ─────────────────────────────────────────────
# ONTOLOGY VERSION
# Bump when any set changes. Papers pin to this version via provenance.
# ─────────────────────────────────────────────

import os
import yaml as _yaml

def _load_yaml_map(path: str) -> dict:
    """Load a key-value YAML file relative to project root. Returns empty dict on failure."""
    abs_path = os.path.join(os.path.dirname(__file__), '..', path)
    try:
        with open(abs_path) as f:
            result = _yaml.safe_load(f)
            return result if isinstance(result, dict) else {}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "_load_yaml_map: failed to load %s: %s — using empty map", path, e
        )
        return {}

# Maps task category strings to goal_type values in goal_execution.
# Source: config/category_to_goal_type.yaml — edit that file, not this line.
CATEGORY_TO_GOAL_TYPE: dict = _load_yaml_map('config/category_to_goal_type.yaml')

ONTOLOGY_VERSION: str = "1.0.0"

# ─────────────────────────────────────────────
# HALLUCINATION TYPES
# Governs: hallucination_events.hallucination_type
#
# factual_error        — stated fact is verifiably wrong
# reasoning_error      — logic chain is invalid despite correct premises
# tool_misread         — model misinterprets tool output
# fabricated_reference — cites non-existent source, paper, or entity
# context_confusion    — confuses entities or timeframes within context window
# temporal_error       — states outdated fact as current
# instruction_ignored  — ignores explicit constraint in prompt
# other                — use when none above fits; document in actual_output
# ─────────────────────────────────────────────
HALLUCINATION_TYPES: FrozenSet[str] = frozenset({
    "factual_error",
    "reasoning_error",
    "tool_misread",
    "fabricated_reference",
    "context_confusion",
    "temporal_error",
    "instruction_ignored",
    "other",
})

# ─────────────────────────────────────────────
# DETECTION METHODS
# Governs: hallucination_events.detection_method
#
# exact_match          — string equality against ground truth
# semantic_similarity  — embedding distance below threshold
# llm_judge            — secondary LLM classifies output as hallucinatory
# unit_test            — automated test suite failure
# human_review         — human annotator judgment
# ─────────────────────────────────────────────
DETECTION_METHODS: FrozenSet[str] = frozenset({
    "exact_match",
    "semantic_similarity",
    "llm_judge",
    "unit_test",
    "human_review",
})


# ─────────────────────────────────────────────
# VALIDATION HELPERS
# Used by ETL scripts before any DB insert.
# ─────────────────────────────────────────────

def validate_hallucination_type(value: str) -> None:
    """Raise ValueError if value is not in HALLUCINATION_TYPES."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"hallucination_type must be a non-empty string. Got: {value!r}"
        )
    if value not in HALLUCINATION_TYPES:
        raise ValueError(
            f"hallucination_type {value!r} not in ontology registry v{ONTOLOGY_VERSION}. "
            f"Allowed: {sorted(HALLUCINATION_TYPES)}"
        )


def validate_detection_method(value: str) -> None:
    """Raise ValueError if value is not in DETECTION_METHODS."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"detection_method must be a non-empty string. Got: {value!r}"
        )
    if value not in DETECTION_METHODS:
        raise ValueError(
            f"detection_method {value!r} not in ontology registry v{ONTOLOGY_VERSION}. "
            f"Allowed: {sorted(DETECTION_METHODS)}"
        )
