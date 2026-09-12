"""Raw-linked per-domain costs; failures count, missing measurements stay missing."""
from collections import defaultdict
import json
from pathlib import Path
import random
import statistics


def paired_interval(pairs, *, seed=7, draws=2000):
    """Bootstrap independent pair units; do not pass tokens or within-run samples."""
    differences = [b - a for a, b in pairs]
    if len(differences) < 2:
        return dict(
            n=len(differences),
            mean=statistics.mean(differences) if differences else None,
            interval=None,
            reason="at least two independent pair units required",
        )
    rng = random.Random(seed)
    means = sorted(
        statistics.mean(rng.choices(differences, k=len(differences)))
        for _ in range(draws)
    )
    return dict(
        n=len(differences),
        mean=statistics.mean(differences),
        interval=[means[int(0.025 * draws)], means[int(0.975 * draws)]],
    )


def summarize(root):
    root = Path(root)
    groups = defaultdict(list)
    attempts_path = root / "exports" / "attempts.jsonl"
    if attempts_path.exists():
        for line in attempts_path.read_text().splitlines():
            row = json.loads(line)
            attempt = row["attempt"]
            path = root / "goals" / attempt["execution_id"] / "record.json"
            record = attempt.get("execution_record")
            if record is None:
                record = dict(
                    setting_id=row["plan"]["setting_id"],
                    execution_status="incomplete",
                    verifier={"outcome": "unavailable"},
                    measurements=[],
                    started_ns=attempt["started_ns"],
                    ended_ns=attempt.get("ended_ns"),
                )
            else:
                import hashlib

                reference = next(
                    a for a in attempt["artifacts"] if a["role"] == "execution-record"
                )
                if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
                    raise ValueError("execution artifact hash mismatch")
                if json.loads(path.read_text()) != record:
                    raise ValueError("export and execution artifact disagree")
            groups[record["setting_id"]].append((path, record))
    else:
        raise ValueError("summary requires the complete ledger attempt export")
    result = {}
    for setting, entries in groups.items():
        successes = sum(
            r["execution_status"] == "completed" and r["verifier"]["outcome"] == "pass"
            for _, r in entries
        )
        domains = sorted(
            {m["domain_id"] for _, r in entries for m in r["measurements"]}
        )
        energies = {}
        invalid = sum(
            any(
                m["status"] != "valid" or m["energy_j"] is None
                for m in r["measurements"]
            )
            or not r["measurements"]
            for _, r in entries
        )
        for domain in domains:
            values = [
                next(
                    (
                        m["energy_j"]
                        for m in r["measurements"]
                        if m["domain_id"] == domain and m["status"] == "valid"
                    ),
                    None,
                )
                for _, r in entries
            ]
            total = sum(values) if all(v is not None for v in values) else None
            energies[domain] = dict(
                total_attempt_joules=total,
                joules_per_success=total / successes
                if total is not None and successes
                else None,
                reason="zero successes"
                if not successes
                else "missing/invalid energy"
                if total is None
                else "",
            )
        prepared_bytes = 0
        for path, _ in entries:
            events_path = path.with_name("expert-events.json")
            if events_path.exists():
                prepared_bytes += sum(
                    e["transfer"]["transferred_bytes"]
                    for e in json.loads(events_path.read_text())
                    if e["event"] == "expert_transfer"
                    and e["transfer"]["outcome"] == "completed"
                )
        result[setting] = dict(
            completed_preparation_bytes=prepared_bytes,
            attempts=len(entries),
            successful=successes,
            invalid_energy_attempts=invalid,
            total_seconds=sum(
                (r["ended_ns"] - r["started_ns"]) / 1e9 for _, r in entries
            )
            if all(r["ended_ns"] is not None for _, r in entries)
            else None,
            energy=energies,
            records=[str(p.relative_to(root)) for p, _ in entries],
        )
    return dict(
        settings=result,
        scope="per recorded energy domain; never sum overlapping domains",
        uncertainty="paired_interval requires independent task/session pairs; one smoke run is insufficient",
    )
