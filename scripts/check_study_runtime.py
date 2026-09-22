"""Run the explicit portable integration regression set; never access hardware."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "test_data_analysis_workload.py",
    "test_study_contracts.py",
    "test_campaign_ledger.py",
    "test_campaign_recovery.py",
    "test_campaign_runner.py",
    "test_selector_boundary.py",
    "test_openai_compat_adapter.py",
    "test_adapter_provider_routes.py",
    "test_executor_adapter_failures.py",
    "test_measurement_session.py",
    "test_node_measurement.py",
    "test_energy_collector.py",
    "test_gpu_power_integration.py",
    "test_rapl_grace_domains.py",
    "test_integrated_goal.py",
    "test_bounded_executor.py",
    "test_executor_cleanup.py",
    "test_trace_replay.py",
    "test_pilot_tasks.py",
    "test_local_run.py",
]
if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *[str(ROOT / "tests" / p) for p in TESTS],
            ],
            cwd=ROOT,
        )
    )
