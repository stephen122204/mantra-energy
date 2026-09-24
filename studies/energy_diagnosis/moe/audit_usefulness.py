"""Read-only usefulness accounting for prepared experts, from expert-events.json.

Every completed preparation ends in exactly one class:
  used_resident      requested later in the goal and resident at its first dispatch
  evicted_before_use requested later but not resident at its first dispatch
  replaced_unused    prepared again before any use
  unused_at_goal_end never requested before the goal settled
Preparations that did not complete are counted by native outcome.

With the backend's own prefetcher disabled, the only way an expert becomes
resident after preparation and before its first dispatch is this preparation,
so used_resident means the prepared copy survived until used. Under the builtin
arm this inference does not hold; that arm prepares nothing at pauses.

Timing (whether a transfer finished inside a tool body) is audit_transfers.py.
Demand misses count dispatches to non-resident experts: an upper-level proxy
for avoided or incurred on-demand loads, not byte-level copy attribution.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

CLASSES = ("used_resident", "evicted_before_use", "replaced_unused", "unused_at_goal_end")


def _identity(row):
    return (row["node"], row["generation"], row.get("enqueue_ns"), row.get("start_ns"))


def goal(events):
    completed, other = {}, Counter()
    other_bytes = Counter()
    for e in events:
        if e["event"] == "expert_transfer":
            row = e["transfer"]
            if row["outcome"] == "completed":
                completed[_identity(row)] = row
            else:
                other[row["outcome"]] += 1
                other_bytes[row["outcome"]] += row["bytes"]
    classified, phase = {}, Counter()
    for e in events:
        kind = None
        if e["event"] == "prepared_expert_requested":
            kind = "used_resident" if e["resident_on_first_dispatch"] else "evicted_before_use"
            if kind == "used_resident":
                phase[e.get("first_use_phase") or "unknown"] += 1
        elif e["event"] == "prepared_not_used_before_reprepare":
            kind = "replaced_unused"
        elif e["event"] == "prepared_not_used_by_goal_end":
            kind = "unused_at_goal_end"
        if kind:
            key = _identity(e["prepared"])
            if key not in completed:
                raise ValueError("usefulness event without a matching completed transfer")
            if key in classified:
                raise ValueError("completed transfer classified twice")
            classified[key] = kind
    missing = set(completed) - set(classified)
    if missing:
        raise ValueError(f"{len(missing)} completed transfers have no terminal usefulness class")
    counts, nbytes = Counter(classified.values()), Counter()
    by_source = defaultdict(Counter)
    for key, kind in classified.items():
        nbytes[kind] += completed[key]["bytes"]
        by_source[str(completed[key].get("prepared_in"))][kind] += completed[key]["bytes"]
    misses = Counter()
    for e in events:
        if e["event"] == "expert_demand":
            o = e["observation"]
            dispatches = o.get("dispatches", 1)
            resident = o.get("resident_dispatches", dispatches if o.get("resident_at_dispatch") else 0)
            phase_name = o.get("phase") or "unknown"
            misses[f"{phase_name}_dispatches"] += dispatches
            misses[f"{phase_name}_nonresident_dispatches"] += dispatches - resident
    return dict(
        prepared_completed=len(completed),
        counts={k: counts.get(k, 0) for k in CLASSES},
        bytes={k: nbytes.get(k, 0) for k in CLASSES},
        used_resident_first_phase=dict(phase),
        bytes_by_preparation_source={k: dict(v) for k, v in by_source.items()},
        not_completed=dict(other),
        not_completed_bytes=dict(other_bytes),
        demand=dict(misses),
    )


def audit_campaign(campaign):
    root = Path(campaign)
    rows = []
    for path in sorted(root.glob("goals/*/expert-events.json")):
        events = json.loads(path.read_text())
        record = json.loads(path.with_name("record.json").read_text()) if path.with_name("record.json").exists() else {}
        policy = events[0].get("policy", {}).get("name") if events else None
        rows.append(dict(goal=path.parent.name, task_id=record.get("task_id"),
                         setting_id=record.get("setting_id"), policy=policy, **goal(events)))
    totals = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        for field in ("counts", "bytes", "demand"):
            totals[r["setting_id"]][field].update(r[field])
    return dict(goals=rows, by_setting={s: {f: dict(c) for f, c in v.items()} for s, v in totals.items()},
                scope="Prepared-expert terminal classes and dispatch residency from lifecycle events; "
                      "timing overlap is audit_transfers; demand misses are dispatch counts, not copy bytes.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = audit_campaign(args.campaign)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(json.dumps(result["by_setting"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
