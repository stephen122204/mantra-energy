"""Independent saved-record checks for transfer brackets and real tool bodies.

A host bracket encloses admission/eviction/copy; it is not a DMA duration. A
bracket intersecting a tool body does not by itself prove the copy overlapped.
"""
import argparse
import hashlib
import json
from pathlib import Path
from studies.energy_diagnosis.moe import event_log


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value):
    require(type(value) is int and value >= 0, "invalid nonnegative integer")
    return value


def transfer_key(row):
    return tuple(
        row[key] for key in ("generation", "node", "enqueue_ns", "start_ns", "end_ns")
    )


def tool_intervals(events):
    active, intervals = {}, []
    for event in events:
        kind = event["event"]
        if kind not in {"body_start", "body_end"}:
            continue
        key, stamp = event["call_id"], integer(event["monotonic_ns"])
        if kind == "body_start":
            require(key not in active, "ambiguous concurrent tool identity")
            active[key] = stamp
        else:
            require(key in active, "tool end without start")
            start = active.pop(key)
            require(start <= stamp, "reversed tool body")
            intervals.append((start, stamp))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged, active


def audit_events(events, tools):
    starts = [event for event in events if event["event"] == "goal_start"]
    require(len(starts) == 1, "one goal-start record required")
    goal = starts[0]
    alignment = goal["reset"]["boot"]["clock_alignment"]
    native = integer(alignment["native_ns"])
    lower, upper = integer(alignment["host_lower_ns"]), integer(
        alignment["host_upper_ns"]
    )
    require(lower <= upper, "reversed clock calibration")
    require(
        alignment["uncertainty_ns"] == upper - lower,
        "clock uncertainty disagrees with bracket",
    )
    offset_low, offset_high = lower - native, upper - native
    bodies, unfinished = tool_intervals(tools)
    transfers, by_key, residency = [], {}, {}
    for event in events:
        require(
            event["goal_id"] == goal["goal_id"]
            and event["generation"] == goal["generation"],
            "mixed goal or generation",
        )
        if event["event"] == "prepared_expert_requested":
            key = transfer_key(event["prepared"])
            require(
                key not in residency, "duplicate prepared-expert request attribution"
            )
            require(
                type(event.get("resident_on_first_dispatch")) in {bool, type(None)},
                "invalid residency observation",
            )
            residency[key] = event.get("resident_on_first_dispatch")
        if event["event"] != "expert_transfer":
            continue
        row = event["transfer"]
        require(row["generation"] == goal["generation"], "transfer generation differs")
        require(
            row["native_clock_domain"] == "std::chrono::steady_clock",
            "unsupported native clock",
        )
        moved, size = integer(row["transferred_bytes"]), integer(row["bytes"])
        require(moved <= size, "transferred bytes exceed expert size")
        if row["outcome"] != "completed":
            transfers.append(
                dict(
                    outcome=row["outcome"],
                    transferred_bytes=moved,
                    classification="not_completed",
                )
            )
            continue
        enqueue, start, end = [
            integer(row[key]) for key in ("enqueue_ns", "start_ns", "end_ns")
        ]
        require(enqueue <= start <= end, "reversed transfer timestamps")
        require(
            row["queue_wait_ns"] == start - enqueue
            and row["transfer_ns"] == end - start,
            "derived transfer duration disagrees",
        )
        key = transfer_key(row)
        require(key not in by_key, "duplicate completed transfer")
        start_low, start_high = start + offset_low, start + offset_high
        end_low, end_high = end + offset_low, end + offset_high
        if any(a <= start_low and end_high <= b for a, b in bodies):
            category = "host_bracket_fully_within_tool_body"
        elif unfinished:
            category = "unavailable_tool_end"
        elif all(end_high <= a or start_low >= b for a, b in bodies):
            category = "host_bracket_outside_tool_bodies"
        else:
            category = "partial_or_uncertain"
        result = dict(
            outcome="completed",
            node=row["node"],
            layer=row["layer"],
            expert=row["expert"],
            transferred_bytes=moved,
            classification=category,
            host_start_bounds_ns=[start_low, start_high],
            host_end_bounds_ns=[end_low, end_high],
            host_bracket_ns=end - start,
            requested_later=False,
            resident_on_first_dispatch=None,
        )
        by_key[key] = result
        transfers.append(result)
    require(
        set(residency) <= set(by_key),
        "request attribution without matching completed transfer",
    )
    for key, resident in residency.items():
        by_key[key].update(requested_later=True, resident_on_first_dispatch=resident)
    totals = {}
    for row in transfers:
        category = row["classification"]
        totals[category] = totals.get(category, 0) + row["transferred_bytes"]
    return dict(
        audit_passed=True,
        clock_offset_bounds_ns=[offset_low, offset_high],
        tool_body_intervals_ns=bodies,
        unfinished_tool_bodies=unfinished,
        transferred_bytes_by_bracket_class=totals,
        transfers=transfers,
        scope="Logical completed expert placement bytes, not independently measured PCIe traffic. "
        "Host brackets include admission/eviction/copy and clock uncertainty; partial bracket overlap "
        "does not establish DMA overlap. Later request and pre-dispatch residency do not prove "
        "which transfer supplied the bytes or that no eviction/reload occurred.",
    )


def audit_campaign(root):
    root = Path(root).resolve()
    rows = [
        json.loads(line)
        for line in (root / "exports/attempts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    require(rows, "no exported attempts")
    results = []
    for row in rows:
        attempt = row["attempt"]
        execution = attempt["execution_id"]
        if (attempt.get("execution_record") or {}).get("simulated"):
            results.append(
                dict(
                    execution_id=execution,
                    status="unavailable",
                    reason="simulated attempt",
                )
            )
            continue
        payloads = {}
        try:
            for ref in attempt["artifacts"]:
                if ref["role"] not in {"expert-events", "tool-events"}:
                    continue
                require(ref["role"] not in payloads, "duplicate artifact role")
                relative = Path(ref["path"])
                path = (root / relative).resolve()
                allowed = ([Path("goals") / execution / n for n in event_log.NAMES]
                           if ref["role"] == "expert-events" else [Path("goals") / execution / "events.json"])
                require(
                    relative in allowed and path.is_relative_to(root),
                    "artifact identity/path mismatch",
                )
                raw = path.read_bytes()
                require(
                    hashlib.sha256(raw).hexdigest() == ref["sha256"],
                    "artifact hash mismatch",
                )
                payloads[ref["role"]] = event_log.decode(raw, relative)
            if set(payloads) != {"expert-events", "tool-events"} or not payloads.get(
                "expert-events"
            ):
                require(
                    attempt.get("execution_status") != "completed",
                    "completed attempt lacks required trace artifacts",
                )
                results.append(
                    dict(
                        execution_id=execution,
                        status="unavailable",
                        reason="attempt lacks required completed trace artifacts",
                    )
                )
                continue
            result = audit_events(payloads["expert-events"], payloads["tool-events"])
            results.append(dict(execution_id=execution, status="checked", **result))
        except (ValueError, KeyError, TypeError, OSError) as error:
            results.append(
                dict(execution_id=execution, status="failed", error=str(error))
            )
    return dict(
        observed_records_consistent=all(r["status"] != "failed" for r in results),
        every_attempt_checked=all(r["status"] == "checked" for r in results),
        attempts=results,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign")
    args = parser.parse_args()
    result = audit_campaign(args.campaign)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["observed_records_consistent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
