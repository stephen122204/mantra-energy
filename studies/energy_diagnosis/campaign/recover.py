"""Safely reconcile interrupted campaign attempts after supervised cleanup.

The command previews by default. Applying a recovery requires a terminal
``run_bounded`` status, an explicit operator attestation that owned work has
ended, and an endpoint from the attempt's original monotonic clock domain.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Sequence

from .ledger import LedgerError, RunLedger


TERMINAL_SUPERVISOR_STATUSES = {"completed", "failed", "timed_out", "interrupted", "interference_detected"}


class RecoveryRefused(RuntimeError):
    """Recovery evidence is missing, ambiguous, or unsafe."""


def _load_supervisor_status(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryRefused(f"cannot read supervisor status {path}: {error}") from error
    if not isinstance(value, dict):
        raise RecoveryRefused("supervisor status must be a JSON object")
    status = value.get("status")
    if status not in TERMINAL_SUPERVISOR_STATUSES:
        raise RecoveryRefused(
            f"supervisor is not safely terminal: {status!r}; expected one of "
            f"{sorted(TERMINAL_SUPERVISOR_STATUSES)}"
        )
    if not value.get("finished_utc"):
        raise RecoveryRefused("supervisor status has no finished_utc cleanup marker")
    if value.get("cleanup_complete") is not True:
        raise RecoveryRefused("supervisor has no successful cleanup_complete evidence")
    if type(value.get("child_pid")) is not int or value["child_pid"] <= 0:
        raise RecoveryRefused("supervisor status has no owned child_pid")
    return value


def reconcile(
    *,
    campaign_dir: Path,
    session_id: str,
    clock_domain: str,
    ended_ns: int,
    reason: str,
    supervisor_status: Path,
    apply: bool,
    owned_work_terminated: bool,
) -> dict[str, Any]:
    """Preview or apply one evidence-backed interrupted-session recovery."""
    campaign_dir = campaign_dir.resolve()
    ledger_path = campaign_dir / "ledger.sqlite"
    if not ledger_path.is_file():
        raise RecoveryRefused(f"campaign ledger does not exist: {ledger_path}")
    if not session_id.strip() or not clock_domain.strip() or not reason.strip():
        raise RecoveryRefused("session_id, clock_domain, and reason must be non-empty")
    if isinstance(ended_ns, bool) or not isinstance(ended_ns, int) or ended_ns < 0:
        raise RecoveryRefused("ended_ns must be a non-negative integer")

    supervisor = _load_supervisor_status(supervisor_status.resolve())
    with RunLedger(ledger_path, artifact_root=campaign_dir) as ledger:
        attempts = ledger.running_attempts(session_id=session_id)
        if not attempts:
            raise RecoveryRefused(f"no running attempts belong to session {session_id!r}")
        other = ledger.running_attempts()
        if len(other) != len(attempts):
            raise RecoveryRefused("another session also has a running attempt; reconcile it separately")
        if any(attempt.clock_domain != clock_domain for attempt in attempts):
            raise RecoveryRefused("clock_domain differs from the persisted running attempt")
        if any(ended_ns < attempt.started_ns for attempt in attempts):
            raise RecoveryRefused("ended_ns precedes a persisted attempt start")

        preview = {
            "action": "apply" if apply else "preview",
            "campaign_dir": str(campaign_dir),
            "supervisor": {
                "status": supervisor["status"],
                "finished_utc": supervisor["finished_utc"],
                "child_pid": supervisor["child_pid"],
            },
            "reason": reason,
            "ended_ns": ended_ns,
            "clock_domain": clock_domain,
            "attempts": [asdict(attempt) for attempt in attempts],
        }
        if not apply:
            preview["message"] = (
                "Preview only; rerun with --apply and --owned-work-terminated "
                "after independently confirming no owned process remains."
            )
            return preview
        if not owned_work_terminated:
            raise RecoveryRefused(
                "--apply requires --owned-work-terminated after an independent process check"
            )

        recovered = ledger.recover_interrupted(
            session_id=session_id,
            clock_domain=clock_domain,
            ended_ns=ended_ns,
            reason=reason,
            expected_attempts=attempts,
        )
        if recovered != attempts:
            raise RecoveryRefused("running attempts changed during reconciliation")
        preview["recovered_attempt_ids"] = [attempt.attempt_id for attempt in recovered]
        preview["validation"] = ledger.validate()
        return preview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--clock-domain", required=True)
    parser.add_argument("--ended-ns", required=True, type=int)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--supervisor-status", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--owned-work-terminated",
        action="store_true",
        help="Attest that an independent process check found no owned work remaining.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = reconcile(
            campaign_dir=args.campaign_dir,
            session_id=args.session_id,
            clock_domain=args.clock_domain,
            ended_ns=args.ended_ns,
            reason=args.reason,
            supervisor_status=args.supervisor_status,
            apply=args.apply,
            owned_work_terminated=args.owned_work_terminated,
        )
    except (RecoveryRefused, LedgerError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
