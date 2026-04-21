#!/usr/bin/env python3
"""
================================================================================
RUN EXPERIMENT — individual experiment CLI for A-LEMS
================================================================================

Purpose:
    Run single or comparison experiments without going through test_harness.py.
    Supports all providers in models.json v2 — local, remote, cloud.
    Delegates to existing LinearExecutor / AgenticExecutor + harness measurement
    stack — energy measurement is NOT bypassed.

Usage:
    python scripts/run_experiment.py --list
    python scripts/run_experiment.py --list-models --provider ollama_remote

    python scripts/run_experiment.py \
        --provider ollama_remote --model qwen2.5-coder:14b \
        --mode linear --task gsm8k_basic --repetitions 3

    python scripts/run_experiment.py \
        --provider groq --model llama-3.3-70b-versatile \
        --mode both --task gsm8k_basic --repetitions 5

    python scripts/run_experiment.py \
        --compare ollama_remote:qwen2.5-coder:14b groq:llama-3.3-70b-versatile \
        --mode linear --task gsm8k_basic --repetitions 3

Author: A-LEMS Chunk 7
================================================================================
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

# Ensure project root on path when called as script
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core.config_loader import ConfigLoader
from core.execution.model_factory import ModelFactory

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def main():
    """Parse args and dispatch to run mode."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.list:
        _cmd_list(args)
        return

    if args.list_models:
        _cmd_list_models(args)
        return

    if args.compare:
        _cmd_compare(args)
        return

    # Default: single provider/model run
    _cmd_run(args)


# =============================================================================
# COMMANDS
# =============================================================================

def _cmd_list(args):
    """
    Print all providers and their models from models.json.

    Args:
        args: parsed argparse namespace
    """
    providers = ModelFactory.list_providers(task=args.task_filter)
    print(f"\n{'='*60}")
    print(f"  A-LEMS Model Registry")
    if args.task_filter:
        print(f"  Filtered by task: {args.task_filter}")
    print(f"{'='*60}")
    for pname, pcfg in providers.items():
        ptype = pcfg.get("type", "?")
        print(f"\n  [{pname}]  type={ptype}")
        for m in pcfg.get("models", []):
            tasks = ",".join(m.get("tasks", []))
            modes = ",".join(m.get("modes", []))
            print(f"    {m['model_id']:<40} tasks={tasks}  modes={modes}")
    print()


def _cmd_list_models(args):
    """
    Print models for a specific provider.

    Args:
        args: parsed argparse namespace (requires args.provider)
    """
    if not args.provider:
        print("ERROR: --list-models requires --provider")
        sys.exit(1)
    models = ModelFactory.list_models(args.provider)
    if not models:
        print(f"No models found for provider '{args.provider}'")
        sys.exit(1)
    print(f"\nModels for '{args.provider}':")
    for m in models:
        print(f"  {m['model_id']}")
        print(f"    name:   {m.get('name','')}")
        print(f"    tasks:  {m.get('tasks',[])}")
        print(f"    modes:  {m.get('modes',[])}")
        print(f"    tokens: {m.get('max_tokens','?')}")


def _cmd_run(args):
    """
    Run single provider/model experiment (linear, agentic, or both modes).

    Args:
        args: parsed argparse namespace
    """
    _validate_run_args(args)

    config = ConfigLoader()
    # Use v2 config loader to get flat merged config
    flat_config = config.get_model_config_v2(args.provider, args.model)
    if not flat_config:
        print(f"ERROR: model '{args.model}' not found under provider '{args.provider}'")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  A-LEMS Experiment Run")
    print(f"  Provider : {args.provider}")
    print(f"  Model    : {args.model}")
    print(f"  Mode     : {args.mode}")
    print(f"  Task     : {args.task}")
    print(f"  Reps     : {args.repetitions}")
    print(f"{'='*60}\n")

    modes = ["linear", "agentic"] if args.mode == "both" else [args.mode]

    for mode in modes:
        # Check mode supported by this model
        supported_modes = flat_config.get("modes", [])
        if mode not in supported_modes:
            print(f"  SKIP {mode}: not in supported modes {supported_modes}")
            continue
        _run_mode(flat_config, mode, args.task, args.repetitions, args.verbose)


def _cmd_compare(args):
    """
    Cross-provider comparison run — same task, multiple provider:model pairs.

    Args:
        args: parsed argparse namespace (args.compare is list of 'provider:model')
    """
    config = ConfigLoader()
    pairs = []
    for spec in args.compare:
        # Parse 'provider:model_id' — model_id may contain colons (ollama tags)
        parts = spec.split(":", 1)
        if len(parts) != 2:
            print(f"ERROR: --compare spec must be 'provider:model_id', got '{spec}'")
            sys.exit(1)
        provider, model_id = parts
        flat = config.get_model_config_v2(provider, model_id)
        if not flat:
            print(f"ERROR: '{model_id}' not found under '{provider}'")
            sys.exit(1)
        pairs.append((provider, model_id, flat))

    print(f"\n{'='*60}")
    print(f"  A-LEMS Cross-Provider Comparison")
    print(f"  Task : {args.task}   Mode: {args.mode}   Reps: {args.repetitions}")
    for p, m, _ in pairs:
        print(f"  - {p}:{m}")
    print(f"{'='*60}\n")

    for provider, model_id, flat_config in pairs:
        print(f"\n--- {provider}:{model_id} ---")
        _run_mode(flat_config, args.mode, args.task, args.repetitions, args.verbose)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _run_mode(flat_config: dict, mode: str, task: str, repetitions: int, verbose: bool):
    """
    Instantiate executor and run via harness for one mode.

    Uses existing harness measurement stack — no energy bypass.

    Args:
        flat_config:  merged provider+model config dict
        mode:         'linear' or 'agentic'
        task:         task ID string (e.g. 'gsm8k_basic')
        repetitions:  number of repetitions
        verbose:      pass through to test harness
    """
    # Delegate to test_harness CLI — reuses all measurement logic
    # This avoids duplicating harness setup and keeps energy capture intact
    cmd = [
        sys.executable, "-m", "core.execution.tests.test_harness",
        "--task-id", task,
        "--repetitions", str(repetitions),
        "--provider", flat_config.get("provider", ""),
        "--model-id", flat_config.get("model_id", ""),
    ]
    if mode == "agentic":
        cmd.append("--agentic")
    if verbose:
        cmd.append("--verbose")

    import subprocess
    print(f"  Running {mode} [{flat_config.get('model_id')}] x{repetitions}...")
    result = subprocess.run(cmd, cwd=str(_ROOT))
    if result.returncode != 0:
        print(f"  WARNING: {mode} run exited with code {result.returncode}")


def _validate_run_args(args):
    """
    Validate required args for --run mode. Exits on missing.

    Args:
        args: parsed argparse namespace
    """
    if not args.provider:
        print("ERROR: --provider required")
        sys.exit(1)
    if not args.model:
        print("ERROR: --model required")
        sys.exit(1)
    if not args.task:
        print("ERROR: --task required")
        sys.exit(1)
    if args.mode not in ("linear", "agentic", "both"):
        print(f"ERROR: --mode must be linear|agentic|both, got '{args.mode}'")
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    """
    Build and return the argument parser.

    Returns:
        argparse.ArgumentParser
    """
    p = argparse.ArgumentParser(
        description="A-LEMS individual experiment runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_experiment.py --list
  python scripts/run_experiment.py --list-models --provider ollama_remote
  python scripts/run_experiment.py --provider ollama_remote --model qwen2.5-coder:14b --mode linear --task gsm8k_basic --repetitions 3
  python scripts/run_experiment.py --provider groq --model llama-3.3-70b-versatile --mode both --task gsm8k_basic
  python scripts/run_experiment.py --compare ollama_remote:qwen2.5-coder:14b groq:llama-3.3-70b-versatile --mode linear --task gsm8k_basic
        """
    )

    # List commands
    p.add_argument("--list", action="store_true", help="List all providers and models")
    p.add_argument("--list-models", action="store_true", help="List models for a provider")
    p.add_argument("--task-filter", default=None, help="Filter --list by task (e.g. text-generation)")

    # Single run
    p.add_argument("--provider", default=None, help="Provider key (e.g. ollama_remote, groq)")
    p.add_argument("--model", default=None, help="Model ID (e.g. qwen2.5-coder:14b)")
    p.add_argument("--mode", default="linear", choices=["linear","agentic","both"])
    p.add_argument("--task", default=None, help="Task ID (e.g. gsm8k_basic)")
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--verbose", action="store_true")

    # Comparison run
    p.add_argument(
        "--compare", nargs="+", default=None,
        metavar="PROVIDER:MODEL",
        help="Cross-provider comparison: space-separated provider:model pairs"
    )

    return p


if __name__ == "__main__":
    main()
