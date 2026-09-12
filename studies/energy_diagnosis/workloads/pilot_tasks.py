"""Four small, immutable AL3 pilot tasks and independent verifiers."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PILOT_VERIFIER_VERSION = "pilot-verifier-v1"
PILOT_DIR = Path(__file__).with_name("pilot_assets")


class PilotInputError(ValueError):
    """Raised when a pilot manifest or immutable asset is invalid."""


@dataclass(frozen=True)
class PilotTask:
    task_id: str
    family: str
    lineage: str
    asset_path: Path
    expected: dict[str, Any]
    asset_sha256: str
    eligible_controls: tuple[str, ...]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    else:
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(child.relative_to(path).as_posix().encode())
            digest.update(b"\0")
            digest.update(child.read_bytes())
    return digest.hexdigest()


def _data_reference(path: Path) -> dict[str, Decimal]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    try:
        return {
            "total_units": sum(Decimal(row["units"]) for row in rows),
            "total_revenue": sum(Decimal(row["units"]) * Decimal(row["unit_price"]) for row in rows),
        }
    except (KeyError, InvalidOperation) as exc:
        raise PilotInputError(f"invalid data asset: {path.name}") from exc


def _repository_reference(path: Path) -> dict[str, Any]:
    files = sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file())
    return {"file_count": len(files), "checks": files}


def load_pilot_tasks(manifest_path: Path | None = None) -> tuple[PilotTask, ...]:
    path = manifest_path or PILOT_DIR / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotInputError(f"cannot load pilot manifest: {exc}") from exc
    tasks = []
    for raw in manifest.get("tasks", []):
        required = {"task_id", "family", "lineage", "asset", "asset_sha256", "expected", "eligible_controls"}
        if required.difference(raw):
            raise PilotInputError(f"missing fields for {raw.get('task_id', '<unknown>')}")
        asset = (path.parent / raw["asset"]).resolve()
        if not asset.exists() or path.parent.resolve() not in asset.parents:
            raise PilotInputError(f"invalid asset for {raw['task_id']}")
        if _hash(asset) != raw["asset_sha256"]:
            raise PilotInputError(f"asset hash mismatch for {raw['task_id']}")
        if raw["family"] not in {"data", "repository"}:
            raise PilotInputError(f"unsupported family for {raw['task_id']}")
        tasks.append(PilotTask(
            task_id=raw["task_id"], family=raw["family"], lineage=raw["lineage"],
            asset_path=asset, expected=raw["expected"],
            asset_sha256=raw["asset_sha256"],
            eligible_controls=tuple(raw["eligible_controls"]),
        ))
    if len(tasks) != 4 or len({task.task_id for task in tasks}) != 4:
        raise PilotInputError("pilot manifest must contain four unique tasks")
    if {task.family for task in tasks} != {"data", "repository"}:
        raise PilotInputError("pilot manifest needs both task families")
    return tuple(tasks)


def verify_pilot(task: PilotTask, answer: Any) -> dict[str, Any]:
    """Verify a structured answer using the immutable asset, not agent output."""
    if not isinstance(answer, dict):
        return {"passed": False, "reason": "answer must be an object", "verifier_version": PILOT_VERIFIER_VERSION}
    if answer.get("task_id") != task.task_id or answer.get("evidence") != [task.asset_sha256]:
        return {"passed": False, "reason": "task identity or evidence mismatch", "verifier_version": PILOT_VERIFIER_VERSION}
    try:
        if task.family == "data":
            actual = {key: Decimal(str(answer[key])) for key in ("total_units", "total_revenue")}
            expected = _data_reference(task.asset_path)
            passed = all(abs(actual[key] - expected[key]) <= Decimal("0.01") for key in actual)
        else:
            actual = answer["checks"]
            expected = _repository_reference(task.asset_path)
            passed = actual == expected["checks"] and answer.get("file_count") == expected["file_count"]
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return {"passed": False, "reason": "malformed answer", "verifier_version": PILOT_VERIFIER_VERSION}
    return {
        "passed": passed,
        "reason": "ok" if passed else "reference mismatch",
        "verifier_version": PILOT_VERIFIER_VERSION,
        "task_id": task.task_id,
        "asset_sha256": task.asset_sha256,
    }