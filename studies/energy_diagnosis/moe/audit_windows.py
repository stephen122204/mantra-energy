"""Read-only, independent replay of exported initialized-model counter windows.

This does not import the runtime's counter arithmetic or certify sensor accuracy.
It checks recorded evidence, including failed attempts, without rewriting it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def replay(samples, domain, bits):
    """Use every intermediate reading; do not bridge gaps or interpolate time."""
    if domain["domain_type"] != "ENERGY_COUNTER":
        return None, 0, "not a cumulative energy counter"
    limit = domain.get("max_energy_range_uj") or 2 ** bits
    total, wraps = 0, 0
    for sample in samples:
        if sample["status"] != "ok" or not finite(sample["value"]):
            return None, wraps, "missing or invalid raw reading"
        require(0 <= sample["value"] < limit, "raw reading outside declared counter range")
    for before, after in zip(samples, samples[1:]):
        delta = after["value"] - before["value"]
        if delta < 0:
            if before["value"] < 0.75 * limit or after["value"] > 0.25 * limit:
                return None, wraps, "counter decreased outside single-wrap boundary"
            delta += limit
            wraps += 1
        total += delta
    return total / 1e6, wraps, ""


def indexed(records):
    by_domain = {r["domain_id"]: r for r in records}
    require(len(by_domain) == len(records), "duplicate domain measurement")
    return by_domain


def audit_attempt(root, row):
    attempt = row["attempt"]
    execution = attempt["execution_id"]
    base = Path("goals") / execution
    required = {
        "execution-record": "record.json",
        "raw-measurement": "measurement.json",
        "initialized-model-window": "initialized-model-window.json",
        "expert-events": "expert-events.json",
    }
    artifacts = {}
    for ref in attempt["artifacts"]:
        relative = Path(ref["path"])
        path = (root / relative).resolve()
        require(not relative.is_absolute() and path.is_relative_to(root), "artifact escapes packet")
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == ref["sha256"], "artifact hash mismatch")
        if ref["role"] in required:
            require(relative == base / required[ref["role"]], "artifact identity/path mismatch")
            require(ref["role"] not in artifacts, "duplicate artifact role")
            artifacts[ref["role"]] = json.loads(raw)
    require(set(required) <= artifacts.keys(), "required registered artifact missing")
    record = artifacts["execution-record"]
    raw = artifacts["raw-measurement"]
    window = artifacts["initialized-model-window"]
    events = artifacts["expert-events"]
    require(record == attempt["execution_record"], "record differs from ledger export")
    require(record["goal_execution_id"] == window["goal_execution_id"] == execution, "execution identity mismatch")
    require(record["clock_domain"] == raw["clock_domain"] == window["clock_domain"] == attempt["clock_domain"], "clock domain mismatch")
    require(raw["session_id"] == attempt["session_id"], "session identity mismatch")
    require(window["protocol"] == "initialized-model-fresh-process-v1", "unsupported checkpoint protocol")
    require(record["started_ns"] == raw["goal_start_ns"] and record["ended_ns"] == raw["goal_end_ns"], "outer goal endpoints differ")
    require(raw["measurement_schema"]["unit"] == "microjoules", "unsupported counter unit")
    checkpoints = raw["checkpoints"]
    require(set(checkpoints) >= {"initialized_model_start", "initialized_model_end"}, "initialized endpoints not both captured")
    labels = ["goal_start", checkpoints["initialized_model_start"], checkpoints["initialized_model_end"], "goal_end"]
    require(len(set(labels)) == 4, "checkpoint labels alias each other")
    domains = {d["canonical_name"]: d for d in raw["measurement_schema"]["domains"]}
    require(len(domains) == len(raw["measurement_schema"]["domains"]) and domains, "empty or duplicate counter domains")
    samples = defaultdict(list)
    seen = set()
    for sample in raw["samples"]:
        require(sample["sample_id"] not in seen, "duplicate raw sample")
        seen.add(sample["sample_id"])
        require(sample["session_id"] == raw["session_id"], "raw sample session mismatch")
        require(sample["domain_id"] in domains and sample["unit"] == "microjoules", "raw sample domain/unit mismatch")
        require(sample["acquired_start_ns"] <= sample["acquired_end_ns"], "reversed acquisition bracket")
        samples[sample["domain_id"]].append(sample)
    measured = {
        "outer": indexed(record["measurements"]),
        "initialized": indexed(window["measurements"]),
        "before": indexed(window.get("before_task_window", {}).get("measurements", [])),
        "after": indexed(window.get("after_task_window", {}).get("measurements", [])),
    }
    owned = attempt.get("outcome_metadata", {}).get("owned_work_terminated") is True
    result = {}
    for name, domain in domains.items():
        series = samples[name]
        require(series, "domain has no raw samples")
        require(all(a["acquired_end_ns"] <= b["acquired_start_ns"] for a, b in zip(series, series[1:])), "raw acquisition overlap or reordered samples")
        endpoint_indices = []
        for label in labels:
            matches = [i for i, s in enumerate(series) if s["sample_id"].rsplit(":", 2)[-2] == label]
            require(len(matches) == 1, "missing or duplicate raw endpoint")
            endpoint_indices.append(matches[0])
        require(all(a < b for a, b in zip(endpoint_indices, endpoint_indices[1:])), "raw endpoints out of order")
        endpoints = [series[i] for i in endpoint_indices]
        begin, end = endpoints[1:3]
        for span in record["spans"]:
            require(begin["acquired_end_ns"] <= span["start_ns"] <= span["end_ns"] <= end["acquired_start_ns"], "task span outside initialized interval")
        starts = [e for e in events if e["event"] == "goal_start"]
        drains = [e for e in events if e["event"] == "preparation_drained"]
        releases = [e for e in events if e["event"] == "goal_end"]
        require(len(starts) == 1 and len(drains) == 1 and len(releases) == 1, "missing/duplicate startup, drain or release evidence")
        require(starts[0]["startup_window"]["end_ns"] <= begin["acquired_start_ns"], "initialization overlaps inner start")
        require(begin["acquired_end_ns"] <= drains[0]["monotonic_ns"] <= end["acquired_start_ns"], "drain outside initialized interval")
        require(end["acquired_end_ns"] <= releases[0]["monotonic_ns"] <= endpoints[3]["acquired_start_ns"], "release outside final portion")
        for event in events:
            if event["event"] in {"preparation_planning_start", "preparation_planning_end", "model_start", "model_end"}:
                require(begin["acquired_end_ns"] <= event["monotonic_ns"] <= end["acquired_start_ns"], "task control outside initialized interval")
        portions = {}
        for part, left, right in [("outer", 0, 3), ("before", 0, 1), ("initialized", 1, 2), ("after", 2, 3)]:
            selected = series[endpoint_indices[left]:endpoint_indices[right] + 1]
            joules, wraps, reason = replay(selected, domain, raw["measurement_schema"]["counter_width_bits"])
            saved = measured[part].get(name)
            require(saved is not None, "missing domain measurement")
            require(saved["session_id"] == raw["session_id"], "measurement session mismatch")
            require(saved["start_ns"] == selected[0]["acquired_start_ns"] and saved["end_ns"] == selected[-1]["acquired_end_ns"], "measurement endpoints differ from raw brackets")
            if saved["status"] == "valid":
                require(owned and joules is not None, "valid energy without complete ownership/raw counters")
                require(finite(saved["energy_j"]) and math.isclose(saved["energy_j"], joules, rel_tol=1e-12, abs_tol=1e-9), "counter replay disagrees with energy total")
            else:
                require(saved["energy_j"] is None, "invalid measurement retains a numeric total")
            portions[part] = dict(replayed_joules=joules, recorded_status=saved["status"], wraps=wraps, reason=reason)
        if all(p["replayed_joules"] is not None for p in portions.values()):
            require(math.isclose(portions["outer"]["replayed_joules"], sum(portions[p]["replayed_joules"] for p in ("before", "initialized", "after")), rel_tol=1e-12, abs_tol=1e-9), "energy portions do not reconcile")
        result[name] = dict(
            portions=portions,
            checkpoint_brackets_ns=[s["acquired_end_ns"] - s["acquired_start_ns"] for s in endpoints],
            initialized_duration_bracket_ns=[end["acquired_start_ns"] - begin["acquired_end_ns"], end["acquired_end_ns"] - begin["acquired_start_ns"]],
            max_sample_bracket_ns=max(s["acquired_end_ns"] - s["acquired_start_ns"] for s in series),
        )
    all_valid = all(p["recorded_status"] == "valid" for d in result.values() for p in d["portions"].values())
    inner_valid = all(d["portions"]["initialized"]["recorded_status"] == "valid" for d in result.values())
    require(window["status"] != "valid" or inner_valid, "valid window with invalid domain evidence")
    return dict(execution_id=execution, audit_passed=True, all_domains_measured=all_valid,
                simulated=record["simulated"], execution_status=record["execution_status"],
                verifier_outcome=record["verifier"]["outcome"], owned_work_terminated=owned,
                source_revision=raw["environment"]["source_revision"], domains=result)


def audit_recovered(root, row):
    """An interrupted attempt recovered by the operator claims no counter evidence.

    It is reported explicitly, never treated as measured, and cannot hide behind
    an artifact: recovery metadata, incomplete status and absent valid energy are
    all required before the attempt is accepted as consistently recorded.
    """
    attempt = row["attempt"]
    metadata = attempt.get("outcome_metadata") or {}
    record = attempt["execution_record"]
    require(isinstance(metadata.get("recovery"), dict) and metadata["recovery"].get("reason"), "recovered attempt lacks recovery reason")
    for ref in attempt["artifacts"]:
        # Artifacts checkpointed before the interruption stay hash-pinned evidence
        # of the pre-recovery state; they are not audited as a completed goal.
        relative = Path(ref["path"])
        path = (root / relative).resolve()
        require(not relative.is_absolute() and path.is_relative_to(root), "artifact escapes packet")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"], "recovered attempt artifact hash mismatch")
    require(record["execution_status"] == "incomplete" and attempt["execution_status"] == "incomplete", "recovered attempt is not incomplete")
    require(attempt["measurement_status"] != "valid" and attempt["verifier_outcome"] == "unavailable", "recovered attempt claims valid measurement or verification")
    require(all(m.get("status") != "valid" and m.get("energy_j") is None for m in record.get("measurements", [])), "recovered attempt retains a numeric energy total")
    require(record["ended_ns"] is not None and record["ended_ns"] >= record["started_ns"], "recovered attempt endpoint precedes its start")
    return dict(execution_id=attempt["execution_id"], audit_passed=True, all_domains_measured=False, recovered=True,
                checkpointed_artifacts=len(attempt["artifacts"]),
                simulated=record["simulated"], execution_status="incomplete", verifier_outcome="unavailable",
                owned_work_terminated=metadata.get("owned_work_terminated") is True, source_revision=None, domains={},
                note="recovered after interruption: " + metadata["recovery"]["reason"] + "; no counter evidence is claimed")


def audit(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "moe-manifest.json").read_text())
    rows = [json.loads(line) for line in (root / "exports" / "attempts.jsonl").read_text().splitlines() if line.strip()]
    results, seen = [], set()
    for row in rows:
        execution = row["attempt"]["execution_id"]
        try:
            require(execution not in seen, "duplicate execution in export")
            seen.add(execution)
            if "recovery" in (row["attempt"].get("outcome_metadata") or {}):
                results.append(audit_recovered(root, row))
                continue
            result = audit_attempt(root, row)
            require(manifest["execution_protocol"] == "planned-body-initialized-window-v1", "unsupported execution protocol")
            require(result["source_revision"] == manifest["source_revision"], "source revision differs from manifest")
            require(manifest["mode"] in {"native", "fixture"} and result["simulated"] == (manifest["mode"] == "fixture"), "simulation identity differs from manifest")
            results.append(result)
        except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
            results.append(dict(execution_id=execution, audit_passed=False, error=str(exc)))
    return dict(
        audit_version="initialized-counter-replay-v1", attempts=len(rows), results=results,
        audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        audit_passed=bool(results) and all(r["audit_passed"] for r in results),
        scope="Recorded counter arithmetic and timing/ownership evidence only; no external calibration, model equivalence or effect estimate. Failed attempts are retained. Brackets express acquisition uncertainty, not exact simultaneous boundaries. Replay assumes at most one wrap per adjacent reading and cannot detect unobserved complete counter cycles.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    report = audit(args.root)
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["audit_passed"] else 2)


if __name__ == "__main__":
    main()
