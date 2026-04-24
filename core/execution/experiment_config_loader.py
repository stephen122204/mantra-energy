"""
experiment_config_loader.py — Shared YAML config loader for experiment entry points.

Loads experiment config YAML and overrides argparse args in place.
Both test_harness.py and run_experiment.py call apply_config() after parse_args().
Adding new config keys here propagates to all entry points automatically.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_config(args) -> None:
    """
    Load experiment config YAML and override args in place.

    Called after parse_args(). If args.config is None, returns immediately —
    all CLI defaults are preserved. When config is present, only keys that
    exist in the YAML override the corresponding arg. Missing keys keep their
    CLI defaults, so partial configs are valid.

    Args:
        args: argparse.Namespace — mutated in place.

    Returns:
        None. args is mutated directly.
    """
    config_path = getattr(args, "config", None)
    if not config_path:
        # No config file — CLI args stand as-is
        return

    # Validate path before importing yaml — gives clear error message
    path = Path(config_path)
    if not path.exists():
        logger.warning("apply_config: config file not found: %s — using CLI args", config_path)
        return

    try:
        import yaml
        with open(path) as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        logger.warning("apply_config: failed to load %s: %s — using CLI args", config_path, e)
        return

    if not isinstance(cfg, dict):
        logger.warning("apply_config: config is not a dict — using CLI args")
        return

    _apply_study_section(args, cfg.get("study", {}))
    _apply_execution_section(args, cfg.get("execution", {}))
    _apply_retry_section(args, cfg.get("retry_policy", {}))

    logger.info("apply_config: loaded config from %s", config_path)


# ── Section appliers ──────────────────────────────────────────────────────────

def _apply_study_section(args, study: dict) -> None:
    """
    Override experiment identity args from study section.
    Only overrides if key present in YAML — CLI defaults kept otherwise.
    """
    if "experiment_type" in study:
        args.experiment_type = study["experiment_type"]
        logger.debug("apply_config: experiment_type = %s", args.experiment_type)

    if "experiment_goal" in study:
        args.experiment_goal = study["experiment_goal"]

    if "workflow_modes" in study:
        # YAML carries a list — map to single workflow_mode arg
        modes = study["workflow_modes"]
        if not isinstance(modes, list) or not modes:
            logger.warning("apply_config: workflow_modes must be a non-empty list — ignoring")
        elif len(modes) == 1:
            args.workflow_mode = modes[0]
        else:
            # Multiple modes → comparison experiment (both sides run)
            args.workflow_mode = "comparison"
        logger.debug("apply_config: workflow_mode = %s", getattr(args, "workflow_mode", None))


def _apply_execution_section(args, execution: dict) -> None:
    """
    Override execution parameters from execution section.
    repetitions and cool_down_seconds only — safety-critical params stay CLI-only.
    """
    if "repetitions" in execution:
        args.repetitions = int(execution["repetitions"])
        logger.debug("apply_config: repetitions = %d", args.repetitions)

    if "cool_down_seconds" in execution:
        # cool_down vs cool-down naming varies across entry points — set both
        val = int(execution["cool_down_seconds"])
        args.cool_down = val
        logger.debug("apply_config: cool_down = %d", val)


def _apply_retry_section(args, retry: dict) -> None:
    """
    Override retry policy args from retry_policy section.
    Stored on args for 8.5-B RetryCoordinator to consume.
    No-op in 8.5-A — wired here so configs are forward compatible.
    """
    if "max_retries" in retry:
        args.max_retries = int(retry["max_retries"])

    if "backoff_seconds" in retry:
        args.backoff_seconds = float(retry["backoff_seconds"])
