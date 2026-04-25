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
    _apply_tasks_section(args, cfg.get("tasks", []))
    _apply_providers_section(args, cfg.get("providers", []))
    _apply_failure_injection_section(args, cfg.get("failure_injection", {}))
    logger.info("apply_config: loaded config from %s", config_path)

def _apply_failure_injection_section(args, fi: dict) -> None:
    """
    Build FailureInjector from failure_injection YAML section and store on args.
 
    FailureInjector is only active when enabled=true AND experiment_type=failure_injection.
    Storing on args allows test_harness and run_experiment to pass it into execute_goal()
    without reading YAML directly in entry points.
 
    Args:
        args: argparse.Namespace — mutated in place.
        fi:   failure_injection section dict from YAML.
    """
    if not fi.get("enabled", False):
        # Injection disabled — store None so callers can check cheaply
        args.failure_injector = None
        return
 
    try:
        from core.execution.failure_injector import FailureInjector
        experiment_type = getattr(args, "experiment_type", "normal")
        args.failure_injector = FailureInjector(fi, experiment_type)
        logger.info(
            "_apply_failure_injection_section: FailureInjector active "
            "tool_rate=%.2f timeout_rate=%.2f",
            fi.get("tool_failure_rate", 0.0),
            fi.get("timeout_rate", 0.0),
        )
    except Exception as e:
        # Never block experiment startup over injector construction failure
        logger.warning("_apply_failure_injection_section: failed to build injector: %s", e)
        args.failure_injector = None
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
    if "tasks" in study:
        # Extract task IDs from list of dicts [{id: ...}] or plain strings
        task_entries = study["tasks"]
        ids = []
        for t in task_entries:
            if isinstance(t, dict):
                ids.append(t["id"])
            else:
                ids.append(str(t))
        if ids:
            # task_id is the single-task CLI arg — set first task for single-task entry points
            args.task_id = ids[0]
            # task_ids carries full list — run_experiment.py and config-driven runs use this
            args.task_ids = ids
            logger.debug("apply_config: task_ids = %s", ids)


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

def _apply_tasks_section(args, tasks: list) -> None:
    """
    Override task_id and task_ids from top-level tasks list in config.
    tasks is a list of dicts [{id: ...}] or plain strings.
    task_id set to first entry for single-task harness entry points.
    task_ids carries full list for multi-task run_experiment.py.
    """
    if not tasks:
        return
    ids = []
    for t in tasks:
        if isinstance(t, dict):
            ids.append(t["id"])
        else:
            ids.append(str(t))
    if ids:
        args.task_id  = ids[0]
        args.task_ids = ids
        logger.debug("apply_config: task_ids = %s", ids)
        
def _apply_providers_section(args, providers: list) -> None:
    """
    Override provider and model from top-level providers list.
    Takes first provider only — test_harness is single-provider.
    run_experiment.py loops over full list itself.
    """
    if not providers:
        return
    first = providers[0] if isinstance(providers[0], dict) else {}
    if "name" in first:
        args.provider = first["name"]
        logger.debug("apply_config: provider = %s", args.provider)
    if "model_id" in first:
        args.model = first["model_id"]
        logger.debug("apply_config: model = %s", args.model)

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
    if "name" in retry:
        # policy_name used by RetryCoordinator.load_policy() in test_harness/run_experiment
        args.policy_name = str(retry["name"])
