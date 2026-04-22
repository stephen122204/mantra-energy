"""
Quality score computation for experiment runs.

Returns three values per run:
    experiment_valid  — 1 if no hard failures, else 0
    quality_score     — float [0.0, 1.0]; formula: max(0, 1 - sum(w_i * p_i))
    rejection_reason  — JSON blob with full audit trail

Hard failures set valid=0 and score=0 immediately (short-circuit).
Soft issues subtract weighted penalties from 1.0.
Config loaded from config/quality.yaml — thresholds are NOT hardcoded here.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Tuple


class QualityScorer:
    """
    Computes experiment_valid, quality_score, and rejection_reason for a run.

    Config path defaults to config/quality.yaml relative to repo root.
    Hardware profile is resolved by hardware_hash; falls back to 'default'.
    """

    # Bump this when scoring logic changes — stored in run_quality.quality_version
    # so historical scores can be identified and re-backfilled if needed.
    VERSION = 1

    def __init__(self, config_path: str = "config/quality.yaml"):
        """
        Load quality thresholds from YAML config.

        Args:
            config_path: Path to quality.yaml relative to CWD (or absolute).
        """
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        # Version stored in YAML for future multi-version support
        self.version = self.config.get("version", 1)

    # ------------------------------------------------------------------
    # PROFILE RESOLUTION
    # ------------------------------------------------------------------

    def _get_profile(self, hardware_hash: str) -> Dict:
        """
        Resolve threshold profile for the given hardware hash.

        Profiles support single-level inheritance via 'inherits' key.
        Unknown hashes fall back to 'default' profile.

        Args:
            hardware_hash: Value from hardware_config.hardware_hash column.

        Returns:
            Merged dict of threshold values for this hardware.
        """
        profiles = self.config.get("profiles", {})

        # Simple hash→name mapping — extend here for per-machine profiles
        hash_map = self.config.get("hash_map", {})
        profile_name = "default"
        profile = profiles.get(profile_name, {}).copy()

        # Single-level inheritance: child keys override parent
        if "inherits" in profile:
            parent = profiles.get(profile["inherits"], {})
            base = parent.copy()
            base.update(profile)
            return base

        return profile

    # ------------------------------------------------------------------
    # MAIN SCORING ENTRY POINT
    # ------------------------------------------------------------------

    def compute(
        self, run_data: Dict, hardware_hash: str = "default"
    ) -> Tuple[int, float, str]:
        """
        Score a single run against quality thresholds.

        Formula (soft score):
            quality_score = max(0.0, 1.0 - sum(w_i * p_i))
            where w_i = weight from config, p_i in {0.5 (warning), 1.0 (critical)}

        Hard failures short-circuit: experiment_valid=0, quality_score=0.0.

        Args:
            run_data:      Dict with run fields (status, baseline_id, temps, etc.)
            hardware_hash: From hardware_config.hardware_hash; selects threshold profile.

        Returns:
            (experiment_valid: int, quality_score: float, rejection_reason: str JSON)
        """
        profile = self._get_profile(hardware_hash)
        weights = self.config.get("weights", {})
        null_handling = self.config.get("null_handling", {})

        # Audit blob — always populated so analysts can inspect scoring decisions
        result = {
            "version": self.VERSION,
            "hard_failures": [],        # any entry → experiment_valid=0
            "soft_issues": [],          # entries reduce quality_score
            "missing_telemetry": [],    # fields absent but penalty skipped per null_handling
            "metrics": {
                "max_temp_c":              run_data.get("max_temp_c"),
                "start_temp_c":            run_data.get("start_temp_c"),
                "delta_c":                 None,   # computed below if both temps present
                "background_cpu_percent":  run_data.get("background_cpu_percent"),
                "interrupts_per_second":   run_data.get("interrupts_per_second"),
                "energy_sample_count":     run_data.get("energy_sample_count") if run_data.get("energy_sample_count") is not None else run_data.get("energy_sample_coverage_pct"),
                "duration_ms": (
                    run_data.get("duration_ns", 0) / 1e6
                    if run_data.get("duration_ns") else 0
                ),
            },
        }

        # Thermal delta requires both readings; compute once, reuse below
        if (
            run_data.get("max_temp_c") is not None
            and run_data.get("start_temp_c") is not None
        ):
            result["metrics"]["delta_c"] = (
                run_data["max_temp_c"] - run_data["start_temp_c"]
            )

        # ==============================================================
        # HARD FAILURES — short-circuit, experiment_valid = 0, score = 0
        # ==============================================================

        # Execution must have completed successfully
        if run_data.get("status") == "failed":
            result["hard_failures"].append("execution_failed")

        # Baseline is mandatory — without it dynamic energy is meaningless
        if run_data.get("baseline_id") is None:
            result["hard_failures"].append("missing_baseline")

        # Zero energy almost certainly means RAPL read failed or run was trivial
        if run_data.get("dynamic_energy_uj", 0) == 0:
            result["hard_failures"].append("zero_energy")

        # Duration sanity — too short = incomplete; too long = runaway
        duration_ms = result["metrics"]["duration_ms"]
        if duration_ms < profile.get("min_duration_ms", 100):
            result["hard_failures"].append("duration_too_short")
        elif duration_ms > profile.get("max_duration_sec", 60) * 1000:
            result["hard_failures"].append("duration_too_long")

        # Any hard failure → stop here, score is meaningless
        if result["hard_failures"]:
            return 0, 0.0, json.dumps(result)

        # ==============================================================
        # SOFT ISSUES — subtract weighted penalties from 1.0
        # ==============================================================

        score = 1.0

        # --- Thermal absolute ---
        # High absolute temp degrades measurement reliability (CPU throttles)
        max_temp = run_data.get("max_temp_c")
        if max_temp is not None:
            if max_temp > profile.get("max_temp_critical", 85):
                result["soft_issues"].append("temperature_too_high")
                score -= weights.get("thermal_absolute", 0.20)          # full penalty
            elif max_temp > profile.get("max_temp_warning", 80):
                result["soft_issues"].append("temperature_elevated")
                score -= weights.get("thermal_absolute", 0.20) * 0.5    # half penalty
        elif null_handling.get("max_temp_c") == "skip_penalty":
            result["missing_telemetry"].append("no_max_temp")

        # --- Thermal delta ---
        # Large rise during run indicates thermal transient — energy noise
        delta = result["metrics"]["delta_c"]
        if delta is not None:
            if delta > profile.get("thermal_delta_critical", 25):
                result["soft_issues"].append("thermal_delta_high")
                score -= weights.get("thermal_delta", 0.15)
            elif delta > profile.get("thermal_delta_warning", 15):
                result["soft_issues"].append("thermal_delta_elevated")
                score -= weights.get("thermal_delta", 0.15) * 0.5
        elif null_handling.get("start_temp_c") == "skip_delta":
            result["missing_telemetry"].append("no_start_temp")

        # --- Background CPU ---
        # High background load contaminates workload energy attribution
        bg_cpu = run_data.get("background_cpu_percent")
        if bg_cpu is not None:
            if bg_cpu > profile.get("background_cpu_critical", 20):
                result["soft_issues"].append("high_background_cpu")
                score -= weights.get("background_cpu", 0.20)
            elif bg_cpu > profile.get("background_cpu_warning", 10):
                result["soft_issues"].append("elevated_background_cpu")
                score -= weights.get("background_cpu", 0.20) * 0.5
        # assume_zero → no penalty when field is NULL (ARM VM expected)

        # --- Interrupt rate ---
        # High interrupt rate inflates pkg energy via interrupt handling overhead
        interrupts = run_data.get("interrupts_per_second")
        if interrupts is not None:
            if interrupts > profile.get("interrupts_critical", 50000):
                result["soft_issues"].append("high_interrupt_rate")
                score -= weights.get("interrupts", 0.15)
            elif interrupts > profile.get("interrupts_warning", 15000):
                result["soft_issues"].append("elevated_interrupt_rate")
                score -= weights.get("interrupts", 0.15) * 0.5
        # assume_zero → no penalty when field is NULL

        # --- Sample count ---
        # Too few RAPL samples → energy integral is coarse
        sample_count = run_data.get("energy_sample_count", 0)
        if sample_count < profile.get("min_energy_samples", 20):
            result["soft_issues"].append("low_energy_samples")
            score -= weights.get("sample_count", 0.10)

        # Clamp to [0.0, 1.0] — multiple penalties can't produce negative score
        quality_score = max(0.0, min(1.0, score))

        return 1, quality_score, json.dumps(result)
