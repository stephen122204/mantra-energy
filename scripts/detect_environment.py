#!/usr/bin/env python3
"""
================================================================================
ENVIRONMENT DETECTOR — Detect Runtime Environment and Save to JSON
================================================================================

Purpose:
    Detect the software environment (Python, OS, git state, dependencies,
    container runtime) and save to config/environment.json.

    This runs BEFORE detect_hardware.py and platform.py so that
    PlatformDetector can read both files and make informed decisions
    (e.g. container runtime affects RAPL accessibility).

Run order:
    1. python scripts/detect_environment.py   → config/environment.json
    2. python scripts/detect_hardware.py      → config/hw_config.json
    3. (automatic) platform.py reads both     → config/platform.json

Chunk 1 fix:
    container_runtime and container_image were previously hardcoded None.
    Now detected properly via /.dockerenv and /proc/1/cgroup inspection.
    This matters because Docker/containerd block RAPL reads even on x86_64,
    which must downgrade the measurement mode from MEASURED to INFERRED.

Author: Deepak Panigrahy
================================================================================
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

# Ensure project root is on the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# GIT INFO
# ============================================================================

def get_git_info() -> dict:
    """
    Retrieve current git commit, branch, and dirty state.

    Returns:
        dict: Keys 'commit' (str|None), 'branch' (str|None), 'dirty' (bool|None).
              All None if git is unavailable or not a git repo.
    """
    info = {"commit": None, "branch": None, "dirty": None}
    try:
        # Short commit hash (16 chars is enough for identification)
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()[:16]

        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()

        # Non-empty status output means uncommitted changes exist
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True
        ).strip()

        info = {"commit": commit, "branch": branch, "dirty": bool(status)}
    except Exception:
        pass    # not a git repo or git not installed — leave as None

    return info


# ============================================================================
# DEPENDENCY VERSIONS
# ============================================================================

def get_dependency_versions() -> dict:
    """
    Probe installed versions of key ML/numeric dependencies.

    Returns:
        dict: Keys 'numpy', 'torch', 'transformers' — version strings or None.
              None means the package is not installed in the current venv.
    """
    deps = {"numpy": None, "torch": None, "transformers": None}

    try:
        import numpy
        deps["numpy"] = numpy.__version__
    except ImportError:
        pass    # numpy not installed

    try:
        import torch
        deps["torch"] = torch.__version__
    except ImportError:
        pass    # torch not installed — EnergyEstimator ML model unavailable

    try:
        import transformers
        deps["transformers"] = transformers.__version__
    except ImportError:
        pass    # transformers not installed

    return deps


# ============================================================================
# CONTAINER DETECTION  (Chunk 1 fix — was hardcoded None)
# ============================================================================

def get_container_info() -> dict:
    """
    Detect if the process is running inside a container runtime.

    Detection methods (in order of reliability):
        1. /.dockerenv file — Docker always creates this on container start
        2. /proc/1/cgroup   — contains runtime name for Docker/containerd/podman
        3. KUBERNETES_SERVICE_HOST env var — set by Kubernetes for all pods

    Why this matters for A-LEMS:
        Container runtimes often block access to RAPL sysfs paths even on
        x86_64 hardware. PlatformDetector uses this flag to downgrade
        measurement mode from MEASURED → INFERRED when RAPL is inaccessible
        due to container isolation.

    Returns:
        dict: Keys 'runtime' (str|None) and 'image' (str|None).
              runtime: 'docker' | 'containerd' | 'podman' | 'kubernetes' | None
              image:   container image name if detectable, else None
    """
    # Method 1: Docker always creates /.dockerenv on the container filesystem
    if Path("/.dockerenv").exists():
        image = os.getenv("HOSTNAME")   # Docker sets HOSTNAME to container ID
        return {"runtime": "docker", "image": image}

    # Method 2: Inspect /proc/1/cgroup for runtime signatures
    cgroup_path = Path("/proc/1/cgroup")
    if cgroup_path.exists():
        try:
            cgroup_text = cgroup_path.read_text()

            if "docker" in cgroup_text:
                return {"runtime": "docker", "image": None}

            if "containerd" in cgroup_text:
                return {"runtime": "containerd", "image": None}

            if "podman" in cgroup_text:
                return {"runtime": "podman", "image": None}

        except (OSError, PermissionError):
            pass    # /proc/1/cgroup not readable — not a container or no permission

    # Method 3: Kubernetes injects this env var into every pod
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return {"runtime": "kubernetes", "image": os.getenv("HOSTNAME")}

    # Not running in any detected container runtime
    return {"runtime": None, "image": None}


# ============================================================================
# HASH & SAVE HELPERS
# ============================================================================

def generate_env_hash(hash_input: dict) -> str:
    """
    Generate a short deterministic fingerprint of the environment.

    Used to detect environment changes between experiment runs and
    link runs to the exact software stack that produced them.

    Args:
        hash_input: Dict of fields to include in the hash.

    Returns:
        str: 16-character hex string (SHA-256 truncated).
    """
    hash_str = json.dumps(hash_input, sort_keys=True)
    return hashlib.sha256(hash_str.encode()).hexdigest()[:16]


def save_with_merge(path: Path, new_data: dict) -> None:
    """
    Write new_data to path, merging with existing JSON if present.

    Merge strategy: existing keys are overwritten by new_data values.
    This allows detect_environment.py to be re-run safely without
    losing keys added by other scripts.

    Args:
        path:     Output path for the JSON file.
        new_data: Dict of fields to write / update.
    """
    if path.exists():
        # Merge: existing fields preserved unless overwritten by new_data
        existing = json.loads(path.read_text())
        existing.update(new_data)
        path.write_text(json.dumps(existing, indent=2))
    else:
        path.write_text(json.dumps(new_data, indent=2))


# ============================================================================
# MAIN
# ============================================================================

def main():
    """
    Run all detection steps and write config/environment.json.

    Output is a FLAT dict (no nested dicts) for easy SQL storage
    and consistent access patterns across the codebase.
    """
    config_path = Path("config/environment.json")

    # Collect all environment information
    git_info      = get_git_info()
    deps          = get_dependency_versions()
    container     = get_container_info()           # Chunk 1 fix: real detection

    # Build flat output dict — no nested dicts per original design
    env_info = {
        # Python runtime
        "python_version":        platform.python_version(),
        "python_implementation": platform.python_implementation(),

        # OS identification
        "os_name":               platform.system(),
        "os_version":            platform.version(),
        "kernel_version":        platform.release(),

        # Git provenance
        "git_commit":            git_info["commit"],
        "git_branch":            git_info["branch"],
        "git_dirty":             git_info["dirty"],

        # ML/numeric dependencies
        "numpy_version":         deps["numpy"],
        "torch_version":         deps["torch"],
        "transformers_version":  deps["transformers"],

        # Container runtime — Chunk 1 fix (was hardcoded None)
        "container_runtime":     container["runtime"],   # None on bare metal
        "container_image":       container["image"],     # None on bare metal
    }

    # Generate environment fingerprint from stable identifying fields
    hash_input = {
        "python_version": env_info["python_version"],
        "os_name":        env_info["os_name"],
        "git_commit":     env_info["git_commit"],
        "numpy_version":  env_info["numpy_version"],
    }
    env_info["env_hash"] = generate_env_hash(hash_input)

    # Persist (merge with existing if present)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_with_merge(config_path, env_info)

    # Summary output
    print(f"✅ Environment detected: {env_info['env_hash']}")
    print(f"   Python  : {env_info['python_version']} ({env_info['python_implementation']})")
    print(f"   OS      : {env_info['os_name']} {env_info['kernel_version']}")
    print(f"   Git     : {env_info['git_commit']} ({env_info['git_branch']}) dirty={env_info['git_dirty']}")
    print(f"   torch   : {env_info['torch_version'] or 'not installed'}")
    print(f"   Container: {env_info['container_runtime'] or 'none (bare metal)'}")


if __name__ == "__main__":
    main()
