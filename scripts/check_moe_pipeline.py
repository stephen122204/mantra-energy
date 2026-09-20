"""Offline acceptance: real tools/RPC/ledger plus standalone native lifecycle."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_moe_native_lifecycle.py",
                "tests/test_moe_pipeline.py",
                "tests/test_local_run.py",
            ],
            cwd=ROOT,
        )
    )
