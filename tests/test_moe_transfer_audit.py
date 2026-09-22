import copy
import hashlib
import json
import pytest
from studies.energy_diagnosis.moe.audit_transfers import audit_events, audit_campaign


def packet(start=3, end=6):
    common = dict(goal_id="goal", generation=1)
    transfer = dict(
        generation=1,
        node=2,
        layer=0,
        expert=1,
        native_clock_domain="std::chrono::steady_clock",
        bytes=64,
        transferred_bytes=64,
        enqueue_ns=1,
        start_ns=start,
        end_ns=end,
        queue_wait_ns=start - 1,
        transfer_ns=end - start,
        outcome="completed",
    )
    events = [
        dict(
            common,
            event="goal_start",
            reset=dict(
                boot=dict(
                    clock_alignment=dict(
                        native_ns=100,
                        host_lower_ns=99,
                        host_upper_ns=101,
                        uncertainty_ns=2,
                    )
                )
            ),
        ),
        dict(common, event="expert_transfer", transfer=transfer),
    ]
    tools = [
        dict(event="body_start", call_id="a", monotonic_ns=0),
        dict(event="body_end", call_id="a", monotonic_ns=10),
    ]
    return events, tools


@pytest.mark.parametrize(
    "start,end,category",
    [
        (3, 6, "host_bracket_fully_within_tool_body"),
        (15, 20, "host_bracket_outside_tool_bodies"),
        (9, 11, "partial_or_uncertain"),
    ],
)
def test_bracket_classification_keeps_clock_uncertainty(start, end, category):
    events, tools = packet(start, end)
    result = audit_events(events, tools)
    assert result["transfers"][0]["classification"] == category
    assert result["transfers"][0]["host_start_bounds_ns"] == [start - 1, start + 1]
    assert result["transferred_bytes_by_bracket_class"] == {category: 64}


def test_requested_and_resident_are_separate_from_usefulness():
    events, tools = packet()
    events.append(
        dict(
            goal_id="goal",
            generation=1,
            event="prepared_expert_requested",
            prepared=events[1]["transfer"],
            resident_on_first_dispatch=False,
        )
    )
    row = audit_events(events, tools)["transfers"][0]
    assert row["requested_later"] is True and row["resident_on_first_dispatch"] is False
    assert "useful_bytes" not in row
    events[2]["prepared"] = dict(events[1]["transfer"], node=99)
    with pytest.raises(ValueError, match="without matching"):
        audit_events(events, tools)


def test_open_tool_and_reused_call_ids_do_not_create_false_overlap():
    events, tools = packet(15, 20)
    tools.append(dict(event="body_start", call_id="a", monotonic_ns=12))
    result = audit_events(events, tools)
    assert result["unfinished_tool_bodies"] == {"a": 12}
    assert result["transfers"][0]["classification"] == "unavailable_tool_end"
    tools.append(dict(event="body_end", call_id="a", monotonic_ns=25))
    assert (
        audit_events(events, tools)["transfers"][0]["classification"]
        == "host_bracket_fully_within_tool_body"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("transfer_ns", 999),
        ("transferred_bytes", 65),
        ("start_ns", False),
        ("end_ns", 2),
        ("generation", 2),
    ],
)
def test_corrupt_transfer_rejected(field, value):
    events, tools = packet()
    events[1]["transfer"][field] = value
    with pytest.raises(ValueError):
        audit_events(events, tools)


def test_duplicate_and_bad_alignment_rejected():
    events, tools = packet()
    events.append(copy.deepcopy(events[-1]))
    with pytest.raises(ValueError, match="duplicate"):
        audit_events(events, tools)
    events, tools = packet()
    events[0]["reset"]["boot"]["clock_alignment"]["uncertainty_ns"] = 0
    with pytest.raises(ValueError, match="uncertainty"):
        audit_events(events, tools)


def test_registered_artifact_hashes_and_missing_attempt_evidence(tmp_path):
    events, tools = packet()
    base = tmp_path / "goals/exec"
    base.mkdir(parents=True)
    refs = []
    for name, role, payload in [
        ("expert-events.json", "expert-events", events),
        ("events.json", "tool-events", tools),
    ]:
        path = base / name
        path.write_text(json.dumps(payload))
        refs.append(
            dict(
                path=path.relative_to(tmp_path).as_posix(),
                role=role,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    exports = tmp_path / "exports"
    exports.mkdir()
    path = exports / "attempts.jsonl"
    row = dict(
        attempt=dict(
            execution_id="exec",
            artifacts=refs,
            execution_record=dict(simulated=False),
            execution_status="completed",
        )
    )
    path.write_text(json.dumps(row) + "\n")
    result = audit_campaign(tmp_path)
    assert result["observed_records_consistent"] and result["every_attempt_checked"]
    (base / "events.json").write_text("[]")
    assert not audit_campaign(tmp_path)["observed_records_consistent"]
    row["attempt"].update(artifacts=[], execution_status="incomplete")
    path.write_text(json.dumps(row) + "\n")
    result = audit_campaign(tmp_path)
    assert result["observed_records_consistent"] and not result["every_attempt_checked"]
