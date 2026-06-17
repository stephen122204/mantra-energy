#!/usr/bin/env python3
"""
================================================================================
BASELINE MANAGER – Handles storage and retrieval of baseline measurements
================================================================================

This module manages baseline data:
- Loading from cache
- Saving new baselines
- Getting the most recent baseline
- Database storage for experiment tracking

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Fix Python path to find core modules
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.config_loader import ConfigLoader
from core.database.manager import DatabaseManager
from core.models.baseline_measurement import BaselineMeasurement
# RAPLReader import removed — PAC-2: no concrete reader imports outside factory.py
from core.utils.core_pinner import CorePinner
from core.utils.idle_baseline import measure_idle_baseline

logger = logging.getLogger(__name__)


class BaselineManager:
    """
    Manages baseline measurements – loading, saving, and retrieving.

    Baselines are stored in:
    1. `data/baselines/` as JSON files (backward compatibility)
    2. `idle_baselines` database table (for experiment tracking)
    """

    def __init__(self, base_dir=None):
        # type: (Optional[str]) -> None
        """
        Initialize baseline manager.
 
        base_dir resolves to machine-specific location when ALEMS_DATA_ROOT set,
        otherwise falls back to project-relative data/baselines/.
 
        Args:
            base_dir: Override directory path. None = auto-resolve.
        """
        import os, socket as _socket
        if base_dir is None:
            # Use same machine-aware root as experiments.db
            data_root = os.environ.get("ALEMS_DATA_ROOT", "")
            if data_root:
                host = _socket.gethostname().lower()
                self.base_dir = Path(data_root) / host / "baselines"
            else:
                self.base_dir = Path(project_root) / "data" / "baselines"
        else:
            self.base_dir = Path(project_root) / base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # ====================================================================
        # NEW: Database connection for experiment tracking
        # ====================================================================
        self.config_loader = ConfigLoader()
        self.db_config = self.config_loader.get_db_config()
        self.db = DatabaseManager(self.db_config)

        logger.info(f"BaselineManager initialized with dir: {self.base_dir}")

    def save(self, baseline: BaselineMeasurement) -> str:
        """
        Save a baseline measurement to disk AND database.
        """
        print(f"🔍 DEBUG - save() method ENTERED for baseline {baseline.baseline_id}")
        print(f"🔍 DEBUG3 - save() entry - object ID: {id(baseline)}")
        print(f"🔍 DEBUG3 - save() entry - metadata: {baseline.metadata}")

        # Save to JSON file

        filename = f"{baseline.baseline_id}.json"
        filepath = self.base_dir / filename

        with open(filepath, "w") as f:
            json.dump(baseline.to_dict(), f, indent=2)

        logger.info(f"Saved baseline {baseline.baseline_id} to {filepath}")

        # Insert into database
        baseline_dict = baseline.to_dict()
        print(
            f"🔍 DEBUG - baseline_dict metadata before DB insert: {baseline_dict.get('metadata')}"
        )

        try:
            result = self.db.insert_baseline(baseline_dict)
            print(f"🔍 DEBUG - Insert result: {result}")
            logger.info(f"Saved baseline {baseline.baseline_id} to database")
        except Exception as e:
            print(f"🔍 DEBUG - Database insert EXCEPTION: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            logger.warning(f"Failed to save baseline to database: {e}")

        return str(filepath)

    def load(self, baseline_id: str) -> Optional[BaselineMeasurement]:
        """
        Load a baseline by ID from JSON file.

        Args:
            baseline_id: Unique baseline identifier

        Returns:
            BaselineMeasurement or None if not found
        """
        filepath = self.base_dir / f"{baseline_id}.json"

        if not filepath.exists():
            logger.warning(f"Baseline {baseline_id} not found")
            return None

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            return BaselineMeasurement(
                baseline_id=data["baseline_id"],
                timestamp=data["timestamp"],
                power_watts=data["power_watts"],
                duration_seconds=data["duration_seconds"],
                sample_count=data["sample_count"],
                std_dev_watts=data.get("std_dev_watts", {}),
                cpu_temperature_c=data.get("cpu_temperature_c"),
                method=data.get("method", "loaded"),
                metadata=data.get("metadata", {}),
            )
        except Exception as e:
            logger.error(f"Error loading baseline {baseline_id}: {e}")
            return None

    def get_latest(self) -> Optional[BaselineMeasurement]:
        """
        Get the most recent baseline from database (preferred) or filesystem.

        Returns:
            Most recent BaselineMeasurement or None
        """
        # ====================================================================
        # NEW: Try database first
        # ====================================================================
        # Step 1: Get most recent baseline_id from idle_baselines
        try:
            result = self.db.execute(
                "SELECT * FROM idle_baselines ORDER BY timestamp DESC LIMIT 1"
            )
            if not result or len(result) == 0:
                raise ValueError("No rows in idle_baselines")
            row = result[0]
 
            # Step 2: Load all domains from normalized table (v61 path)
            # Returns canonical uppercase keys: PACKAGE, CORE, CPU_P, CPU_E, GPU etc.
            domain_rows = self.db.execute(
                """
                SELECT ed.name AS domain_name, ibd.power_watts, ibd.std_watts
                FROM idle_baseline_domains ibd
                JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
                WHERE ibd.baseline_id = ?
                """,
                (row["baseline_id"],),
            )
 
            if domain_rows:
                # v61 path: full domain coverage from normalized table
                power_watts = {r["domain_name"]: r["power_watts"] for r in domain_rows}
                std_dev     = {r["domain_name"]: r["std_watts"]   for r in domain_rows}
            else:
                # Pre-v61 fallback: reconstruct from legacy fixed columns
                # Keys match canonical names so downstream code is consistent
                power_watts = {}
                std_dev     = {}
                legacy_pairs = [
                    ("package_power_watts", "package_std",  "PACKAGE"),
                    ("core_power_watts",    "core_std",     "CORE"),
                    ("dram_power_watts",    "dram_std",     "DRAM"),
                    ("uncore_power_watts",  "uncore_std",   "UNCORE"),
                    ("gpu_power_watts",     "gpu_std",      "GPU"),
                ]
                for pw_col, std_col, canonical in legacy_pairs:
                    val = row.get(pw_col)
                    if val is not None:              # MIC-1: NULL means unavailable
                        power_watts[canonical] = val
                        std_dev[canonical]     = row.get(std_col) or 0.0
 
            return BaselineMeasurement(
                baseline_id=row["baseline_id"],
                timestamp=row["timestamp"],
                power_watts=power_watts,
                duration_seconds=row["duration_seconds"],
                sample_count=row["sample_count"],
                std_dev_watts=std_dev,
                method=row.get("method", "database"),
                metadata={
                    "governor":       row.get("governor"),
                    "turbo":          row.get("turbo"),
                    "background_cpu": row.get("background_cpu"),
                    "process_count":  row.get("process_count"),
                    "gpu_method":     row.get("gpu_method"),
                },
            )
 
        except Exception as e:
            logger.debug("No baseline in database: %s", e)

        # ====================================================================
        # Fallback to filesystem (backward compatibility)
        # ====================================================================
        json_files = list(self.base_dir.glob("*.json"))
        if json_files:
            latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
            baseline_id = latest_file.stem
            return self.load(baseline_id)

        return None

    # ... rest of existing methods (load, list_baselines, measure_new) remain the same ...
