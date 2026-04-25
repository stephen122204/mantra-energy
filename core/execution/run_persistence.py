"""
run_persistence.py — Single owner of run insertion, sample storage, and ETL chain.

Extracted from ExperimentRunner so both ExperimentRunner (normal path) and
GoalExecutionManager (retry path) share identical run persistence logic.
Neither path duplicates — both delegate here.

Design:
    RunPersistenceService.insert_one_run()
        → _insert_run_row()       insert run + provenance + validate + normalization_factors stub
        → _insert_samples()       all sample tables
        → _insert_events()        orchestration events + LLM interactions
        → _run_post_etl()         full ETL chain (sync)
        → _apply_duration_fix()   fix_run / fix_run_with_pretask

Energy units: all µJ (REAL). NULL = not yet computed, 0 = computed and is zero.
All operations are synchronous — no async, no threads.
"""

import logging
from typing import Optional

from core.utils.provenance import record_run_provenance
from scripts.etl.phase_attribution_etl import compute_phase_attribution
from scripts.etl.aggregate_hardware_metrics import aggregate_hardware_metrics
from scripts.etl.energy_attribution_etl import compute_energy_attribution
from scripts.etl.duration_fix_etl import fix_run, fix_run_with_pretask
from scripts.etl.ttft_tpot_etl import populate_run as populate_ttft_tpot

logger = logging.getLogger(__name__)


class RunPersistenceService:
    """
    Owns the full lifecycle of persisting one harness result to the DB.

    Stateless — safe to instantiate once at module level and reuse.
    All methods take explicit db/conn arguments — no stored state.
    """

    def insert_one_run(
        self,
        db,
        exp_id: int,
        hw_id: int,
        result: dict,
        workflow_type: str,
        rep_num: int,
    ) -> Optional[int]:
        """
        Persist one completed harness result with all samples and ETL.

        Single entry point for both normal and retry paths — guarantees
        identical 120-column run correctness regardless of caller.

        Args:
            db:            DB adapter with insert_* and transaction() methods.
            exp_id:        Parent experiment ID.
            hw_id:         Hardware profile ID.
            result:        Full harness result dict.
            workflow_type: 'linear' or 'agentic' — never 'comparison'.
            rep_num:       Repetition number (1-indexed) for run_number field.

        Returns:
            run_id (int) or None on failure.
        """
        if workflow_type not in ("linear", "agentic"):
            logger.warning(
                "insert_one_run: invalid workflow_type=%r — aborting", workflow_type
            )
            return None

        # run_number must be stamped before insert so ETL sees it
        result["ml_features"]["run_number"] = rep_num

        with db.transaction():
            run_id = self._insert_run_row(db, exp_id, hw_id, result, workflow_type)
            if run_id is None:
                return None
            self._insert_samples(db, run_id, result)
            self._insert_events(db, run_id, result)

        # ETL runs outside transaction — each ETL function is idempotent
        self._run_post_etl(run_id)
        self._apply_duration_fix(run_id, result)

        return run_id

    # ── Private helpers — each does exactly one thing ─────────────────────────

    def _insert_run_row(
        self,
        db,
        exp_id: int,
        hw_id: int,
        result: dict,
        workflow_type: str,
    ) -> Optional[int]:
        """
        Insert run row, provenance, quality score, and normalization_factors stub.

        normalization_factors stub inserted here so ETL backfill never skips.
        Only run_id, task_category, workload_type known at this point — all
        other columns are NULL and populated by ETL later.

        Returns run_id or None on failure.
        """
        run_id = db.insert_run(exp_id, hw_id, result)
        if run_id is None:
            logger.warning("_insert_run_row: insert_run returned None")
            return None

        # Provenance must be recorded immediately after insert
        record_run_provenance(
            db, run_id, result, reader_mode=result.get("reader_mode")
        )

        # Quality score — written to run_quality table
        self._score_run(db, run_id, hw_id)

        # Stub row so ETL _backfill_normalization_factors never skips this run
        # All metric columns are NULL — ETL populates them after goal tracking
        task_meta = result.get("task_meta", {}) or {}
        task_category = task_meta.get("category", "custom")
        db.db.execute(
            """INSERT OR IGNORE INTO normalization_factors
               (run_id, task_category, workload_type)
               VALUES (?, ?, ?)""",
            (run_id, task_category, workflow_type),
        )

        return run_id

    def _score_run(self, db, run_id: int, hw_id) -> None:
        """
        Score run quality and insert into run_quality table.
        Mirrors ExperimentRunner._validate_run() exactly.
        hw_id may be None for retry-path calls — scorer handles gracefully.
        """
        from core.utils.quality_scorer import QualityScorer

        run = db.get_run(run_id)
        hardware_hash = "default"
        if hw_id is not None:
            hw_rows = db.db.execute(
                "SELECT hardware_hash FROM hardware_config WHERE hw_id = ?", (hw_id,)
            )
            if hw_rows:
                hardware_hash = hw_rows[0]["hardware_hash"]

        scorer = QualityScorer()
        valid, score, reason = scorer.compute(run or {}, hardware_hash)
        db.db.execute(
            """INSERT OR REPLACE INTO run_quality
               (run_id, experiment_valid, quality_score, rejection_reason, quality_version)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, valid, score, reason, scorer.VERSION),
        )

    def _insert_samples(self, db, run_id: int, result: dict) -> None:
        """
        Insert all sample tables for one run.

        Handles old tuple format for backward compat with pre-Chunk-2 energy samples.
        aggregate_run_stats + update_run_stats called inside thermal block — mirrors
        save_pair() exactly so aggregated hardware stats are always populated.
        """
        # Energy samples — convert old tuple format if present
        if "energy_samples" in result:
            converted = self._convert_energy_samples(result["energy_samples"])
            if converted:
                db.insert_energy_samples(run_id, converted)

        if "cpu_samples" in result:
            db.insert_cpu_samples(run_id, result["cpu_samples"])

        if "interrupt_samples" in result:
            db.insert_interrupt_samples(run_id, result["interrupt_samples"])

        if "io_samples" in result:
            db.insert_io_samples(run_id, result["io_samples"])

        if "thermal_samples" in result:
            db.insert_thermal_samples(run_id, result["thermal_samples"])
            # Aggregate stats only after thermal samples exist — matches save_pair() order
            agg = self._aggregate_run_stats(
                run_id,
                result.get("cpu_samples", []),
                result.get("interrupt_samples", []),
            )
            db.update_run_stats(run_id, agg)

    def _insert_events(self, db, run_id: int, result: dict) -> None:
        """
        Insert orchestration events and LLM interactions.

        LLM interactions key is pending_interactions — run_id stamped per row
        because harness does not know run_id at capture time.
        """
        if "orchestration_events" in result:
            db.insert_orchestration_events(run_id, result["orchestration_events"])

        # pending_interactions — harness key for not-yet-persisted LLM calls
        if result.get("pending_interactions"):
            for interaction in result["pending_interactions"]:
                interaction["run_id"] = run_id  # stamp run_id before insert
                db.insert_llm_interaction(interaction)

    def _run_post_etl(self, run_id: int) -> None:
        """
        Run full ETL chain for one run. Same order as save_pair().

        All ETL functions are idempotent — safe to rerun on same run_id.
        Sync only — no async, no threads (confirmed: experiment_runner has zero async).
        """
        compute_phase_attribution(run_id)
        aggregate_hardware_metrics(run_id)
        compute_energy_attribution(run_id)
        populate_ttft_tpot(run_id)

    def _apply_duration_fix(self, run_id: int, result: dict) -> None:
        """
        Apply duration correction. Mirrors save_pair() fix block exactly.

        fix_run_with_pretask used when pre-task RAPL snapshot exists.
        fix_run used otherwise. Never skip — duration fix affects energy attribution.
        """
        ml = result.get("ml_features", {})
        if ml.get("rapl_before_pretask") is not None:
            fix_run_with_pretask(
                run_id,
                ml.get("rapl_before_pretask"),
                ml.get("rapl_after_task"),
                ml.get("pre_task_duration_sec", 0.0),
                ml.get("post_task_duration_sec", 0.0),
                ml.get("cpu_frac_pre", 0.0),
                ml.get("cpu_frac_post", 0.0),
            )
        else:
            fix_run(run_id)

    def _convert_energy_samples(self, samples: list) -> list:
        """
        Convert energy samples to dict format.

        Handles backward compat with old tuple format (timestamp, energy_dict)
        from pre-Chunk-2 harness. New dict format passed through unchanged.
        """
        converted = []
        for sample in samples:
            if isinstance(sample, dict):
                # Chunk 2+ format — use directly
                converted.append(sample)
            elif len(sample) == 2 and isinstance(sample[1], dict):
                # Old tuple format — convert to dict
                timestamp, energy_dict = sample
                converted.append({
                    "timestamp_ns":     int(timestamp * 1_000_000_000),
                    "pkg_energy_uj":    energy_dict.get("package-0", 0),
                    "core_energy_uj":   energy_dict.get("core", 0),
                    "uncore_energy_uj": energy_dict.get("uncore", 0),
                    "dram_energy_uj":   0,
                })
        return converted

    def _aggregate_run_stats(
        self,
        run_id: int,
        cpu_samples: list,
        interrupt_samples: list,
    ) -> dict:
        """
        Compute aggregated hardware stats from samples.

        Pure computation — no DB access, no self state. Inlined here to avoid
        importing ExperimentRunner (circular dependency risk). Logic mirrors
        ExperimentRunner.aggregate_run_stats() exactly — keep in sync.
        Returns dict suitable for db.update_run_stats().
        """
        stats = {
            "run_id": run_id,
            "cpu_busy_mhz": 0.0,
            "cpu_avg_mhz": 0.0,
            "package_temp_celsius": 0.0,
            "max_temp_c": 0.0,
            "min_temp_c": 0.0,
            "interrupt_rate": 0.0,
        }

        if cpu_samples:
            busy_freqs = [s.get("cpu_busy_mhz", 0) for s in cpu_samples if s.get("cpu_busy_mhz")]
            avg_freqs  = [s.get("cpu_avg_mhz", 0)  for s in cpu_samples if s.get("cpu_avg_mhz")]
            temps      = [s.get("package_temp", 0)  for s in cpu_samples if s.get("package_temp")]
            if busy_freqs:
                stats["cpu_busy_mhz"] = sum(busy_freqs) / len(busy_freqs)
            if avg_freqs:
                stats["cpu_avg_mhz"] = sum(avg_freqs) / len(avg_freqs)
            if temps:
                stats["package_temp_celsius"] = sum(temps) / len(temps)
                stats["max_temp_c"] = max(temps)
                stats["min_temp_c"] = min(temps)

        if interrupt_samples:
            irq_rates = [
                s.get("interrupts_per_sec", 0)
                for s in interrupt_samples if s.get("interrupts_per_sec")
            ]
            if irq_rates:
                stats["interrupt_rate"] = sum(irq_rates) / len(irq_rates)

        return stats


# Module-level singleton — stateless, safe to share
_persistence = RunPersistenceService()


def insert_one_run(
    db,
    exp_id: int,
    hw_id: int,
    result: dict,
    workflow_type: str,
    rep_num: int,
) -> Optional[int]:
    """
    Module-level convenience wrapper around RunPersistenceService.insert_one_run().

    Both ExperimentRunner and GoalExecutionManager import this function —
    no need to instantiate the service directly.
    """
    return _persistence.insert_one_run(db, exp_id, hw_id, result, workflow_type, rep_num)
