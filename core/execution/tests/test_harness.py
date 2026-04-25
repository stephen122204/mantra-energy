#!/usr/bin/env python3
"""
================================================================================
TEST HARNESS – Quick verification that harness works
================================================================================
"""

import os
import sys
import time
from pathlib import Path
from core.utils.preflight import preflight

import requests  # Add this for IP geolocation
from dotenv import load_dotenv

load_dotenv()  # Looks for .env in the current directory or parent directories
from core.execution.experiment_runner import ExperimentRunner

# ============================================================================
# Add project root to Python path
# ============================================================================
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import argparse
import socket
from datetime import datetime

import psutil

from core.config_loader import ConfigLoader
from core.database.manager import DatabaseManager
from core.execution.agentic import AgenticExecutor
from core.execution.harness import ExperimentHarness
from core.execution.linear import LinearExecutor
from core.execution.optimizer_wrapper import OptimizedExecutorWrapper
from core.utils.debug import set_debug
from core.utils.task_loader import get_task_by_id, load_tasks
from core.execution.experiment_config_loader import apply_config


def get_country_from_ip():
    """
    Attempt to derive the country code from the current public IP address.
    Uses ipapi.co (free, no API key required for basic lookups).
    Returns a two‑letter country code, or None if it fails.
    """
    try:
        response = requests.get("https://ipapi.co/json/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("country_code")
            if country_code and len(country_code) == 2:
                return country_code.upper()
        print(f"⚠️ IP geolocation returned status {response.status_code}")
    except Exception as e:
        print(f"⚠️ IP geolocation failed: {e}")
    return None


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test experiment harness")
    parser.add_argument(
        "--repetitions",
        "-n",
        type=int,
        default=3,
        help="Number of repetitions (default: 3)",
    )
    parser.add_argument(
        "--cool-down", type=int, default=None, help="Seconds between runs"
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        default=None,
        help="Custom task prompt (overrides --task-id if provided)",
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default="gsm8k_basic",
        help="Task ID from config/tasks.yaml (default: gsm8k_basic, ignored if --task is used)",
    )
    parser.add_argument(
        "--list-tasks", action="store_true", help="List all available tasks and exit"
    )
    parser.add_argument("--no-warmup", action="store_true", help="Skip warmup runs")
    parser.add_argument(
        "--provider",
        type=str,
        default="groq",
        help="Provider from models.yaml e.g. groq, llama_cpp, ollama_remote (default: groq)",
    )
    parser.add_argument("--model", type=str, default=None,
        help="Model ID. If omitted uses first model for provider.")
    
    parser.add_argument("--mode", choices=["linear","agentic","both"], default="both",
        help="linear | agentic | both (default: both)")    
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="Country code for sustainability (e.g., US, IN, FR). "
        "If not provided, derives from IP and falls back to US.",
    )
    parser.add_argument(
        "--ip-detect",
        action="store_true",
        help="Force IP‑based country detection (overrides --country if both given)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug")
    parser.add_argument(
        "--save-db", action="store_true", help="Save results to database"
    )
    parser.add_argument(
        "--optimizer", action="store_true", help="Use optimizer wrapper"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed hardware output per pair"
    )
    parser.add_argument(
        '--experiment-type',
        default='normal',
        choices=[
            'normal','overhead_study','retry_study','failure_injection',
            'quality_sweep','calibration','ablation','pilot','debug',
        ],
        help='Research intent of this experiment run.',
    )
    parser.add_argument(
        '--experiment-goal',
        default=None,
        help='Human readable research question being answered.',
    )
    parser.add_argument(
        '--workflow-mode',
        default='comparison',
        choices=['linear', 'agentic', 'comparison'],
        help='Which workflow sides to run. comparison runs both.',
    )
    parser.add_argument(
        '--config',
        default=None,
        help='Path to experiment config YAML. Overrides individual CLI args.',
    )
    
    return parser.parse_args()


def _list_tasks_and_exit() -> int:
    """Print available tasks and return exit code."""
    tasks = load_tasks()
    print("\n📋 Available tasks:")
    print("-" * 50)
    for t in tasks:
        print(
            f"  {t['id']:<15} | Level {t['level']} | {t['tool_calls']} tools | {t['name']}"
        )
    print("-" * 50)
    return 0
 
 
def _setup_experiment(args):
    """
    Load config, resolve task, build harness and runner.
 
    Returns dict with all objects main() needs to run the experiment.
    Raises SystemExit on unrecoverable setup failure.
    """
    # Country resolution — single place, no inline logic in main()
    country_code = "US"
    if args.ip_detect or (args.country is None and args.ip_detect):
        print("\n🌍 Attempting to detect country from public IP...")
        detected = get_country_from_ip()
        if detected:
            country_code = detected
            print(f"   ✅ Detected country: {country_code}")
        else:
            print(f"   ⚠️ Detection failed, using default: {country_code}")
    elif args.country:
        country_code = args.country.upper()
        print(f"\n🌍 Using provided country: {country_code}")
    else:
        print(f"\n🌍 No country specified, using default: {country_code}")
 
    # Config and hardware
    print("\n📁 Loading configuration...")
    config = ConfigLoader()
    settings = config.get_settings()
    hw_config = config.get_hardware_config()
    settings_dict = settings.__dict__ if hasattr(settings, "__dict__") else settings
    engine_config = hw_config.copy()
    engine_config["settings"] = settings_dict
 
    # Repetitions and cool-down — config wins over defaults, args win over config
    if hasattr(settings, "experiment"):
        default_repetitions = getattr(settings.experiment, "default_iterations", 10)
        default_cool_down   = getattr(settings.experiment, "cool_down_seconds", 30)
    elif isinstance(settings, dict):
        exp_settings        = settings.get("experiment", {})
        default_repetitions = exp_settings.get("default_iterations", 10)
        default_cool_down   = exp_settings.get("cool_down_seconds", 30)
    else:
        default_repetitions = 10
        default_cool_down   = 30
 
    repetitions = args.repetitions if args.repetitions is not None else default_repetitions
    cool_down   = args.cool_down   if args.cool_down   is not None else default_cool_down
 
    # Task resolution
    if args.task:
        task_prompt = args.task
        task_id     = "custom"
        task_name   = "Custom Task"
        task        = {"id": task_id, "name": task_name, "meta": {}}
        print(f"\n📝 Using custom task: {task_prompt[:50]}...")
    else:
        task = get_task_by_id(args.task_id)
        if not task:
            print(f"\n❌ Task ID '{args.task_id}' not found. Use --list-tasks to see available tasks.")
            sys.exit(1)
        task_prompt = task["prompt"]
        task_id     = task["id"]
        task_name   = task["name"]
        print(f"\n📋 Using predefined task: {task_name} (level {task['level']})")
        print(f"   Prompt: {task_prompt[:50]}...")
 
    # Model configs
    print(f"\n🤖 Getting {args.provider} model configs...")
    models_for_provider = config.list_models(args.provider)
    if not models_for_provider:
        print(f"❌ No models found for provider '{args.provider}'")
        sys.exit(1)
    model_id       = args.model if args.model else models_for_provider[0]["model_id"]
    linear_config  = config.get_model_config_v2(args.provider, model_id)
    agentic_config = config.get_model_config_v2(args.provider, model_id)
 
    dummy = type("obj", (object,), {"config": linear_config})()
    preflight(dummy, args.provider)
 
    if not linear_config or not agentic_config:
        print(f"❌ Failed to load {args.provider} model configurations")
        sys.exit(1)
 
    print(f"   Linear model:  {linear_config.get('name')}")
    print(f"   Agentic model: {agentic_config.get('name')}")
 
    # Executors
    print("\n⚙️ Creating executors...")
    if args.optimizer:
        from core.execution.optimizer_wrapper import OptimizedExecutorWrapper
        agentic = OptimizedExecutorWrapper(agentic_config, "agentic")
        linear  = OptimizedExecutorWrapper(linear_config,  "linear")
    else:
        agentic = AgenticExecutor(agentic_config)
        linear  = LinearExecutor(linear_config)
    print(f"   Optimizer: {'Yes' if args.optimizer else 'No'}")
 
    # Harness and runner
    print("🔧 Creating harness...")
    harness          = ExperimentHarness(config)
    runner           = ExperimentRunner(config, args)
    baseline         = runner.ensure_baseline(harness)
    harness.baseline = baseline
 
    return {
        "config":         config,
        "harness":        harness,
        "runner":         runner,
        "linear":         linear,
        "agentic":        agentic,
        "linear_config":  linear_config,
        "agentic_config": agentic_config,
        "task":           task,
        "task_prompt":    task_prompt,
        "task_id":        task_id,
        "task_name":      task_name,
        "country_code":   country_code,
        "repetitions":    repetitions,
        "cool_down":      cool_down,
    }
 
 
def _run_experiment(setup: dict, args) -> tuple:
    """
    Run all repetitions. Handles DB setup, rep loop, and DB teardown.
 
    Respects workflow_mode — runs only the requested sides.
    Returns (all_linear, all_agentic, all_taxes).
    """
    harness        = setup["harness"]
    runner         = setup["runner"]
    linear         = setup["linear"]
    agentic        = setup["agentic"]
    linear_config  = setup["linear_config"]
    agentic_config = setup["agentic_config"]
    task           = setup["task"]
    task_prompt    = setup["task_prompt"]
    task_id        = setup["task_id"]
    task_name      = setup["task_name"]
    country_code   = setup["country_code"]
    repetitions    = setup["repetitions"]
    cool_down      = setup["cool_down"]
    config         = setup["config"]
 
    workflow_mode = getattr(args, "workflow_mode", "comparison")
 
    # DB setup — only when saving
    db = exp_id = hw_id = None
    if args.save_db:
        db, hw_id, env_id = runner.setup_database()
        config.sync_task_categories(db.db.conn)
        exp_id = runner.create_experiment(
            db, task_id, task_name, args.provider, linear_config,
            country_code, args.repetitions, hw_id, env_id,
            optimizer=args.optimizer,
            experiment_type=getattr(args, "experiment_type", "normal"),
            experiment_goal=getattr(args, "experiment_goal", None),
            workflow_mode=workflow_mode,
        )
 
    all_linear     = []
    all_agentic    = []
    all_taxes      = []
    runs_completed = 0
 
    try:
        for rep in range(repetitions):
            print(f"\n{'─'*50}")
            print(f"📋 Repetition {rep+1}/{repetitions}")
            print(f"{'─'*50}")
 
            linear_result  = None
            agentic_result = None
 
            # Run linear side if requested
            if workflow_mode in ("linear", "comparison"):
                linear_result = harness.run_linear(
                    executor=linear,
                    prompt=task_prompt,
                    task_id=task_id,
                    is_cloud=not linear_config.get("is_local", False),
                    country_code=country_code,
                    run_number=rep + 1,
                )
                all_linear.append(linear_result)
 
            # Run agentic side if requested
            if workflow_mode in ("agentic", "comparison"):
                agentic_result = harness.run_agentic(
                    executor=agentic,
                    task=task_prompt,
                    task_id=task_id,
                    is_cloud=not agentic_config.get("is_local", False),
                    country_code=country_code,
                    run_number=rep + 1,
                )
                all_agentic.append(agentic_result)
 
            # Tax only meaningful when both sides ran
            if linear_result and agentic_result:
                linear_energy  = linear_result["ml_features"]["energy_j"]
                agentic_energy = agentic_result["ml_features"]["energy_j"]
                tax = agentic_energy / linear_energy if linear_energy > 0 else 0
                all_taxes.append(tax)
                print(f"\n   📊 Pair {rep+1}:")
                print(f"      Linear:  {linear_energy:.4f} J")
                print(f"      Agentic: {agentic_energy:.4f} J")
                print(f"      Tax: {tax:.2f}x")
            elif linear_result:
                energy = linear_result["ml_features"]["energy_j"]
                print(f"\n   📊 Rep {rep+1}: Linear {energy:.4f} J")
            elif agentic_result:
                energy = agentic_result["ml_features"]["energy_j"]
                print(f"\n   📊 Rep {rep+1}: Agentic {energy:.4f} J")
 
            # Save — pair or single depending on workflow_mode
            if args.save_db:
                if workflow_mode == "comparison":
                    runner.save_pair(
                        db, exp_id, hw_id, linear_result, agentic_result, rep + 1,
                        task_id=task.get("id"), task_name=task.get("name"),
                        task_meta=task.get("meta"),
                    )
                    runs_completed += 2
                elif workflow_mode == "linear" and linear_result:
                    runner.save_single(
                        db, exp_id, hw_id, linear_result, rep + 1, "linear",
                    )
                    runs_completed += 1
                elif workflow_mode == "agentic" and agentic_result:
                    runner.save_single(
                        db, exp_id, hw_id, agentic_result, rep + 1, "agentic",
                    )
                    runs_completed += 1
 
            if rep < repetitions - 1:
                print(f"\n⏳ Cooling down for {cool_down}s...")
                time.sleep(cool_down)
 
    except (Exception, KeyboardInterrupt) as e:
        print(f"\n❌ Experiment failed: {e}")
        import traceback
        traceback.print_exc()
        if args.save_db:
            error_msg = str(e) if str(e) else "KeyboardInterrupt (user cancelled)"
            runner.update_status(db, exp_id, "failed", runs_completed, error_msg)
            db.close()
        return all_linear, all_agentic, all_taxes
 
    if args.save_db:
        runs_completed = len(all_linear) + len(all_agentic)
        runner.update_status(db, exp_id, "completed", runs_completed)
        print(f"\n✅ Experiment {exp_id} completed with {runs_completed} runs")
        db.close()
 
    return all_linear, all_agentic, all_taxes
 
 
def _display_results(all_linear: list, all_agentic: list, all_taxes: list, args) -> None:
    """
    Display hardware deep-dive and final statistics.
    Pure display — no computation side effects.
    """
    if args.verbose:
        from core.execution.display_formatter import display_pair_hardware
        display_pair_hardware(
            all_linear, all_agentic, "HARDWARE PARAMETERS DEEP DIVE - PER PAIR"
        )
 
    import numpy as np
    from core.execution.base import calc_stats
 
    linear_energies  = [r["ml_features"]["energy_j"] for r in all_linear]
    agentic_energies = [r["ml_features"]["energy_j"] for r in all_agentic]
    stats = {
        "linear_energy_j":   calc_stats(linear_energies),
        "agentic_energy_j":  calc_stats(agentic_energies),
        "orchestration_tax": calc_stats(all_taxes),
    }
 
    print("\n" + "=" * 70)
    print("📊 FINAL STATISTICS")
    print("=" * 70)
 
    linear_mean = stats["linear_energy_j"]["mean"]
    linear_std  = stats["linear_energy_j"]["std"]
    if not np.isnan(linear_std):
        print(f"   Linear energy:     {linear_mean:.4f} ± {linear_std:.4f} J")
    else:
        print(f"   Linear energy:     {linear_mean:.4f} J")
 
    agentic_mean = stats["agentic_energy_j"]["mean"]
    agentic_std  = stats["agentic_energy_j"]["std"]
    if not np.isnan(agentic_std):
        print(f"   Agentic energy:    {agentic_mean:.4f} ± {agentic_std:.4f} J")
    else:
        print(f"   Agentic energy:    {agentic_mean:.4f} J")
 
    tax_mean = stats["orchestration_tax"]["mean"]
    ci_lower = stats["orchestration_tax"]["ci_lower"]
    ci_upper = stats["orchestration_tax"]["ci_upper"]
    if not np.isnan(ci_lower):
        print(f"   Orchestration tax: {tax_mean:.2f}x [95% CI: {ci_lower:.2f}, {ci_upper:.2f}]")
    else:
        print(f"   Orchestration tax: {tax_mean:.2f}x")
 
    print("\n✅ Test complete!")
 
 
def main():
    """
    Entry point — parse, configure, dispatch, display.
    No business logic lives here — only orchestration.
    """
    args = parse_arguments()
    apply_config(args)
 
    if args.debug:
        set_debug(True)
 
    print("\n" + "=" * 70)
    print("🔬 TESTING EXPERIMENT HARNESS")
    print("=" * 70)
 
    if args.list_tasks:
        return _list_tasks_and_exit()
 
    setup = _setup_experiment(args)
    all_linear, all_agentic, all_taxes = _run_experiment(setup, args)
    _display_results(all_linear, all_agentic, all_taxes, args)
 
    return 0


if __name__ == "__main__":
    sys.exit(main())
