import json
from pathlib import Path

import pytest

from studies.energy_diagnosis.campaign import PlannedRun, RunLedger
from studies.energy_diagnosis.campaign.recover import RecoveryRefused, reconcile


SHA = "a" * 64
COMMIT = "b" * 40
SESSION = "fixture-session-recovery"
CLOCK = "fixture-host:boot-recovery"


def plan() -> PlannedRun:
    return PlannedRun(
        planned_run_id="fixture-recovery-C00",
        ordinal=1,
        task_id="fixture-recovery",
        setting_id="C00",
        tool_concurrency=False,
        tool_workers=1,
        source_commit=COMMIT,
        task_asset_sha256=SHA,
        model_sha256=SHA,
        verifier_version="fixture-verifier-v1",
        verifier_sha256=SHA,
        retry_limit=1,
        simulated=True,
    )


def interrupted_campaign(tmp_path: Path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    with RunLedger(campaign / "ledger.sqlite", artifact_root=campaign) as ledger:
        ledger.register_plan([plan()])
        lease = ledger.claim_next(
            session_id=SESSION,
            started_ns=100,
            clock_domain=CLOCK,
        )
    assert lease is not None
    return campaign, lease


def supervisor_status(tmp_path: Path, status: str = "interrupted") -> Path:
    path = tmp_path / "supervisor" / "status.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "returncode": 130,
                "child_pid": 1234,
                "cleanup_complete": True,
                "finished_utc": "2026-09-22T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return path


def call(campaign: Path, status: Path, *, apply=False, confirmed=False):
    return reconcile(
        campaign_dir=campaign,
        session_id=SESSION,
        clock_domain=CLOCK,
        ended_ns=150,
        reason="fixture supervisor interruption",
        supervisor_status=status,
        apply=apply,
        owned_work_terminated=confirmed,
    )


def test_preview_is_read_only(tmp_path: Path) -> None:
    campaign, lease = interrupted_campaign(tmp_path)
    result = call(campaign, supervisor_status(tmp_path))
    assert result["action"] == "preview"
    assert result["attempts"][0]["attempt_id"] == lease.attempt_id
    with RunLedger(campaign / "ledger.sqlite") as ledger:
        assert ledger.validate()["counts"]["running"] == 1


def test_apply_requires_explicit_owned_work_confirmation(tmp_path: Path) -> None:
    campaign, _ = interrupted_campaign(tmp_path)
    with pytest.raises(RecoveryRefused, match="owned-work-terminated"):
        call(campaign, supervisor_status(tmp_path), apply=True)
    with RunLedger(campaign / "ledger.sqlite") as ledger:
        assert ledger.validate()["counts"]["running"] == 1


@pytest.mark.parametrize("status", ["starting", "running", "blocked_by_other_job"])
def test_nonterminal_supervisor_refuses_recovery(tmp_path: Path, status: str) -> None:
    campaign, _ = interrupted_campaign(tmp_path)
    with pytest.raises(RecoveryRefused, match="not safely terminal"):
        call(campaign, supervisor_status(tmp_path, status), apply=True, confirmed=True)


def test_apply_retains_interrupted_attempt_and_requeues_retry(tmp_path: Path) -> None:
    campaign, lease = interrupted_campaign(tmp_path)
    result = call(
        campaign,
        supervisor_status(tmp_path),
        apply=True,
        confirmed=True,
    )
    assert result["recovered_attempt_ids"] == [lease.attempt_id]
    assert result["validation"]["counts"] == {
        "plans": 1,
        "pending": 1,
        "running": 0,
        "terminal": 0,
        "attempts": 1,
    }
    with RunLedger(campaign / "ledger.sqlite") as ledger:
        export = ledger.export(tmp_path / "export")
    attempt = json.loads(export["attempts"].read_text(encoding="utf-8"))
    assert attempt["attempt"]["execution_status"] == "incomplete"
    assert attempt["attempt"]["measurement_status"] == "unavailable"
    assert attempt["attempt"]["execution_record"]["error"] == "fixture supervisor interruption"


def test_wrong_clock_or_missing_cleanup_marker_refuses_recovery(tmp_path: Path) -> None:
    campaign, _ = interrupted_campaign(tmp_path)
    status = supervisor_status(tmp_path)
    payload = json.loads(status.read_text(encoding="utf-8"))
    del payload["finished_utc"]
    status.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RecoveryRefused, match="finished_utc"):
        call(campaign, status, apply=True, confirmed=True)

    status = supervisor_status(tmp_path)
    with pytest.raises(RecoveryRefused, match="clock_domain"):
        reconcile(
            campaign_dir=campaign,
            session_id=SESSION,
            clock_domain="fixture-host:other-boot",
            ended_ns=150,
            reason="fixture supervisor interruption",
            supervisor_status=status,
            apply=True,
            owned_work_terminated=True,
        )


@pytest.mark.parametrize("marker", [None, False, "true"])
def test_missing_or_failed_cleanup_refuses_without_mutation(tmp_path, marker):
    campaign, lease = interrupted_campaign(tmp_path)
    status = supervisor_status(tmp_path)
    value = json.loads(status.read_text())
    value["cleanup_complete"] = marker
    status.write_text(json.dumps(value))
    with pytest.raises(RecoveryRefused, match="cleanup_complete"):
        call(campaign, status, apply=True, confirmed=True)
    with RunLedger(campaign / "ledger.sqlite") as ledger:
        assert ledger.running_attempts() == (lease,)


def test_changed_attempt_refused_atomically(tmp_path):
    from studies.energy_diagnosis.campaign.ledger import LedgerValidationError
    campaign, original = interrupted_campaign(tmp_path)
    with RunLedger(campaign / "ledger.sqlite", artifact_root=campaign) as ledger:
        ledger.recover_interrupted(session_id=SESSION, clock_domain=CLOCK,
                                   ended_ns=150, reason="first recovery")
        replacement = ledger.claim_next(session_id=SESSION, started_ns=160,
                                        clock_domain=CLOCK)
        with pytest.raises(LedgerValidationError, match="changed during"):
            ledger.recover_interrupted(session_id=SESSION, clock_domain=CLOCK,
                                       ended_ns=200, reason="stale preview",
                                       expected_attempts=(original,))
        assert ledger.running_attempts() == (replacement,)
