"""
GPU hardware detection for A-LEMS Chunk 15-A.
Runs once at install or when hw_config.json is regenerated.
Populates gpu_config table with hardware identity rows.

15-B will extend this with NVML/DCGM/ROCm/IOKit detection.
Currently implements Intel integrated GPU detection only (UBUNTU2505).

Usage:
    python3 scripts/chunk15_detect_gpu.py
    python3 scripts/chunk15_detect_gpu.py --db data/experiments.db
    python3 scripts/chunk15_detect_gpu.py --db data/experiments.db --hw-config config/hw_config.json

cp to: scripts/chunk15_detect_gpu.py
"""

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _compute_gpu_hash(gpu_info):
    # type: (Dict) -> str
    """
    SHA256 of model + pci_id + driver_version for identity tracking.
    Enables detecting driver upgrades across experiments.
    """
    key = "{}|{}|{}".format(
        gpu_info.get('model', ''),
        gpu_info.get('pci_id', ''),
        gpu_info.get('driver_version', ''),
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _get_pci_id_intel():
    # type: () -> Optional[str]
    """
    Get PCI ID for Intel GPU via lspci.
    Returns string like '8086:9a49' or None on failure.
    """
    try:
        result = subprocess.run(
            ['lspci', '-nn'],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if 'VGA' in line or 'Display' in line:
                match = re.search(r'\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]', line)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.debug("lspci failed: %s", e)
    return None


def detect_intel_integrated(hw_config):
    # type: (Dict) -> Optional[Dict]
    """
    Detect Intel integrated GPU from hw_config.json gpu block.
    Probes MSR 0x641 to confirm energy counter availability.
    Returns gpu_info dict or None if not detected.
    """
    gpu_block = hw_config.get('gpu', {})
    model = gpu_block.get('model', '')

    if not model:
        logger.debug("No gpu.model in hw_config — skipping Intel integrated detection")
        return None

    # Only proceed for Intel integrated (check cpu_vendor)
    if hw_config.get('cpu_vendor', '') != 'GenuineIntel':
        logger.debug("cpu_vendor is not GenuineIntel — skipping MSR PP1 detection")
        return None

    # Probe MSR 0x641 to confirm energy counter works
    msr_binary = Path(__file__).parent.parent / 'core' / 'msr_helper' / 'msr_read'
    energy_supported = 0
    if msr_binary.exists():
        try:
            result = subprocess.run(
                [str(msr_binary), '0', '0x641'],
                capture_output=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                energy_supported = 1
                logger.info("MSR 0x641 probe OK: energy_supported=1")
            else:
                logger.warning("MSR 0x641 probe failed: returncode=%d", result.returncode)
        except Exception as e:
            logger.warning("MSR probe exception: %s", e)
    else:
        logger.warning("msr_read binary not found at %s", msr_binary)

    driver = gpu_block.get('driver', 'i915')
    pci_id = _get_pci_id_intel()

    return {
        'gpu_index':        0,
        'vendor':           'intel',
        'model':            model,
        'driver_version':   driver,
        'cuda_version':     None,
        'rocm_version':     None,
        'vbios_version':    None,
        'pci_id':           pci_id,
        'memory_total_mb':  None,   # Intel integrated shares system RAM — not separately tracked
        'energy_supported': energy_supported,
        'backend':          'msr_pp1' if energy_supported else 'none',
    }


def upsert_gpu_config(db_path, gpu_infos):
    # type: (str, List[Dict]) -> None
    """
    Insert or update gpu_config rows.
    Idempotent — safe to rerun. UNIQUE(gpu_index, gpu_hash) prevents duplicates.
    """
    if not gpu_infos:
        logger.warning("upsert_gpu_config: empty gpu_infos list, nothing to insert")
        return

    conn = sqlite3.connect(db_path)
    try:
        for info in gpu_infos:
            gpu_hash = _compute_gpu_hash(info)
            conn.execute("""
                INSERT OR IGNORE INTO gpu_config
                    (gpu_index, vendor, model, driver_version, cuda_version,
                     rocm_version, vbios_version, pci_id, memory_total_mb,
                     energy_supported, backend, gpu_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                info['gpu_index'],
                info['vendor'],
                info['model'],
                info['driver_version'],
                info['cuda_version'],
                info['rocm_version'],
                info['vbios_version'],
                info['pci_id'],
                info['memory_total_mb'],
                info['energy_supported'],
                info['backend'],
                gpu_hash,
            ))
            logger.info(
                "gpu_config: inserted %s %s (energy_supported=%d backend=%s hash=%s...)",
                info['vendor'], info['model'],
                info['energy_supported'], info['backend'],
                gpu_hash[:12],
            )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM gpu_config").fetchone()[0]
        logger.info("gpu_config now has %d row(s)", count)
    finally:
        conn.close()
def detect_nvidia_nvml():
    """Detect NVIDIA GPUs via pynvml (nvidia-ml-py). Returns gpu_info list."""
    try:
        from core.readers.gpu_collector import NVMLBackend
        backend = NVMLBackend()
        if backend.is_available():
            return backend.get_gpu_info()
    except Exception as e:
        logger.debug("NVML detection failed: %s", e)
    return []
 
 
def detect_nvidia_dcgm():
    """Detect NVIDIA GPUs via DCGM. GN100 primary path. Returns gpu_info list."""
    try:
        from core.readers.gpu_collector import DCGMBackend
        backend = DCGMBackend()
        if backend.is_available():
            return backend.get_gpu_info()
    except Exception as e:
        logger.debug("DCGM detection failed: %s", e)
    return []
 
 
def detect_apple_iokit():
    """Detect Apple Silicon GPU via IOKit/powermetrics. macOS only."""
    try:
        from core.readers.gpu_collector import IOKitBackend
        backend = IOKitBackend()
        if backend.is_available():
            return backend.get_gpu_info()
    except Exception as e:
        logger.debug("IOKit detection failed: %s", e)
    return []
 

def main():
    parser = argparse.ArgumentParser(
        description="Detect GPU hardware and populate gpu_config for A-LEMS")
    parser.add_argument('--db', default='data/experiments.db',
                        help="Path to experiments.db")
    parser.add_argument('--hw-config', default='config/hw_config.json',
                        help="Path to hw_config.json")
    args = parser.parse_args()

    with open(args.hw_config) as f:
        hw_config = json.load(f)

    gpu_infos = []
 
    # DCGM first — GN100/DGX path, primary on ARM where RAPL absent
    dcgm_gpus = detect_nvidia_dcgm()
    if dcgm_gpus:
        gpu_infos.extend(dcgm_gpus)
        logger.info("Detected %d GPU(s) via DCGM", len(dcgm_gpus))
 
    # NVML — discrete NVIDIA GPUs, skip if DCGM already found them
    if not dcgm_gpus:
        nvml_gpus = detect_nvidia_nvml()
        if nvml_gpus:
            gpu_infos.extend(nvml_gpus)
            logger.info("Detected %d GPU(s) via NVML", len(nvml_gpus))
 
    # Intel integrated — UBUNTU2505 Iris Xe path
    intel = detect_intel_integrated(hw_config)
    if intel:
        gpu_infos.append(intel)
        logger.info("Detected Intel integrated GPU: %s (backend=%s)",
                    intel['model'], intel['backend'])
 
    # Apple Silicon — Stephen Abkin M1 Pro path
    apple_gpus = detect_apple_iokit()
    if apple_gpus:
        gpu_infos.extend(apple_gpus)
        logger.info("Detected %d Apple GPU(s) via IOKit", len(apple_gpus))

    if not gpu_infos:
        logger.warning("No GPU detected on this machine. gpu_config will be empty.")
        return

    upsert_gpu_config(args.db, gpu_infos)
    logger.info("Detection complete: %d GPU(s) registered", len(gpu_infos))


if __name__ == '__main__':
    main()
