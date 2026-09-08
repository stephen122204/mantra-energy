"""Immutable fixture and verifier for the first data-analysis goal.

The task contract deliberately stays independent of the model executor. A model
may use the repository's SQLite tool to inspect the CSV, but verification reads
the immutable source directly and recomputes both aggregate dimensions.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


VERIFIER_VERSION = "data-analysis-verifier-v1"
TASK_PATH = Path(__file__).with_name("task.json")
ASSET_DIR = Path(__file__).with_name("assets")


class TaskInputError(ValueError):
    """Raised when a task contract or its immutable assets are invalid."""


class VerificationError(ValueError):
    """Raised only for an invalid verifier invocation, not a wrong answer."""


@dataclass(frozen=True)
class DataAnalysisTask:
    task_id: str
    asset_path: Path
    expected_result_path: Path
    asset_sha256: str
    expected_result_sha256: str
    verifier_version: str
    absolute_tolerance: Decimal

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], base_dir: Path = ASSET_DIR) -> "DataAnalysisTask":
        required = {
            "task_id", "asset", "expected_result", "asset_sha256",
            "expected_result_sha256", "verifier_version", "absolute_tolerance",
        }
        missing = required.difference(raw)
        if missing:
            raise TaskInputError(f"missing task fields: {sorted(missing)}")
        if raw["verifier_version"] != VERIFIER_VERSION:
            raise TaskInputError("unsupported verifier version")
        try:
            tolerance = Decimal(str(raw["absolute_tolerance"]))
        except (InvalidOperation, ValueError) as exc:
            raise TaskInputError("absolute_tolerance must be numeric") from exc
        if not tolerance.is_finite():
            raise TaskInputError("absolute_tolerance must be finite")
        if tolerance <= 0:
            raise TaskInputError("absolute_tolerance must be positive")
        asset_path = (base_dir / str(raw["asset"])).resolve()
        expected_path = (base_dir / str(raw["expected_result"])).resolve()
        base_resolved = base_dir.resolve()
        if not _is_within(asset_path, base_resolved) or not _is_within(expected_path, base_resolved):
            raise TaskInputError("task assets must stay inside the asset directory")
        if not raw["task_id"] or not isinstance(raw["task_id"], str):
            raise TaskInputError("task_id must be a non-empty string")
        return cls(
            task_id=raw["task_id"],
            asset_path=asset_path,
            expected_result_path=expected_path,
            asset_sha256=str(raw["asset_sha256"]),
            expected_result_sha256=str(raw["expected_result_sha256"]),
            verifier_version=raw["verifier_version"],
            absolute_tolerance=tolerance,
        )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_task(path: Path = TASK_PATH) -> DataAnalysisTask:
    """Load and integrity-check the task contract and its expected asset."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskInputError(f"cannot load task contract: {exc}") from exc
    task = DataAnalysisTask.from_mapping(raw, path.parent / "assets")
    for asset_path, expected_hash in (
        (task.asset_path, task.asset_sha256),
        (task.expected_result_path, task.expected_result_sha256),
    ):
        if not asset_path.is_file():
            raise TaskInputError(f"missing immutable asset: {asset_path.name}")
        if _sha256(asset_path) != expected_hash:
            raise TaskInputError(f"asset hash mismatch: {asset_path.name}")
    return task


def _read_rows(task: DataAnalysisTask) -> list[dict[str, str]]:
    with task.asset_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected_columns = {"order_id", "region", "product", "units", "unit_price"}
    if not rows or set(rows[0]) != expected_columns:
        raise TaskInputError("source asset has an unexpected schema")
    return rows


def _reference_aggregates(task: DataAnalysisTask) -> dict[str, dict[str, Decimal] | Decimal]:
    """Recompute references directly from source rows, without query output."""
    region_totals: dict[str, Decimal] = {}
    product_totals: dict[str, Decimal] = {}
    grand_total = Decimal("0")
    for row in _read_rows(task):
        try:
            amount = Decimal(row["units"]) * Decimal(row["unit_price"])
        except (InvalidOperation, KeyError) as exc:
            raise TaskInputError("source asset contains invalid numeric data") from exc
        region_totals[row["region"]] = region_totals.get(row["region"], Decimal("0")) + amount
        product_totals[row["product"]] = product_totals.get(row["product"], Decimal("0")) + amount
        grand_total += amount
    return {
        "region_totals": region_totals,
        "product_totals": product_totals,
        "grand_total": grand_total,
    }


def _as_decimal_map(value: Any, field: str) -> dict[str, Decimal]:
    if not isinstance(value, dict) or not value or any(not isinstance(key, str) for key in value):
        raise VerificationError(f"{field} must be a non-empty object")
    try:
        return {key: Decimal(str(number)) for key, number in value.items()}
    except (InvalidOperation, ValueError) as exc:
        raise VerificationError(f"{field} contains a non-numeric value") from exc


def verify_answer(task: DataAnalysisTask, answer: Any) -> dict[str, Any]:
    """Return an independent pass/fail result for one structured answer."""
    if not isinstance(answer, dict):
        return {"passed": False, "reason": "answer must be an object", "verifier_version": VERIFIER_VERSION}
    evidence = answer.get("evidence")
    if not isinstance(evidence, list) or task.asset_sha256 not in evidence:
        return {"passed": False, "reason": "missing source evidence", "verifier_version": VERIFIER_VERSION}
    try:
        actual_regions = _as_decimal_map(answer.get("region_totals"), "region_totals")
        actual_products = _as_decimal_map(answer.get("product_totals"), "product_totals")
        reconciliation = answer["reconciliation"]
        if not isinstance(reconciliation, dict):
            raise VerificationError("reconciliation must be an object")
        region_total = Decimal(str(reconciliation["region_total"]))
        product_total = Decimal(str(reconciliation["product_total"]))
        difference = Decimal(str(reconciliation["difference"]))
        expected = _reference_aggregates(task)
        expected_regions = expected["region_totals"]
        expected_products = expected["product_totals"]
        checks = [
            actual_regions.keys() == expected_regions.keys(),
            actual_products.keys() == expected_products.keys(),
            all(abs(actual_regions[key] - expected_regions[key]) <= task.absolute_tolerance for key in expected_regions),
            all(abs(actual_products[key] - expected_products[key]) <= task.absolute_tolerance for key in expected_products),
            abs(region_total - expected["grand_total"]) <= task.absolute_tolerance,
            abs(product_total - expected["grand_total"]) <= task.absolute_tolerance,
            abs(difference) <= task.absolute_tolerance,
            abs(region_total - product_total) <= task.absolute_tolerance,
        ]
    except (KeyError, InvalidOperation, TypeError, VerificationError) as exc:
        return {"passed": False, "reason": f"malformed answer: {exc}", "verifier_version": VERIFIER_VERSION}
    return {
        "passed": all(checks),
        "reason": "ok" if all(checks) else "aggregate or reconciliation mismatch",
        "verifier_version": VERIFIER_VERSION,
        "asset_sha256": task.asset_sha256,
        "expected_result_sha256": task.expected_result_sha256,
    }


def load_default_task() -> DataAnalysisTask:
    return load_task()
