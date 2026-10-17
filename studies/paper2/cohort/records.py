"""Append-only, fsync'd cohort records and checksummed exports.

Every event is one JSON line in ``events.jsonl`` with a monotonically increasing ``seq``.
Nothing is rewritten: a resumed cohort appends ``resume`` and new attempt records, and an
infrastructure retry is a new attempt id linked to the failed one by ``retry_of``. Task
failures are terminal outcomes and are never retried here.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

TERMINAL = {"completed", "agent_failed", "timed_out", "cancelled", "infra_failed", "rejected"}


def new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}"


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        if self.path.exists():
            for rec in self.read():
                self._seq = max(self._seq, rec.get("seq", 0))
        self._fh = open(self.path, "a")

    def append(self, kind: str, **fields) -> dict:
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq, "kind": kind, "t_wall": time.time(), "t_mono_ns": time.monotonic_ns(), **fields}
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())
            return rec

    def read(self) -> Iterator[dict]:
        if not self.path.exists():
            return iter(())
        def gen():
            with open(self.path) as fh:
                for n, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        # A torn final line from a crash is kept on disk and reported, not parsed.
                        yield {"kind": "torn_line", "line_no": n}
        return gen()

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def attempt_states(events) -> dict[str, dict]:
    """Latest state per attempt id from the event stream."""
    state: dict[str, dict] = {}
    for e in events:
        aid = e.get("attempt_id")
        if not aid:
            continue
        s = state.setdefault(aid, {"attempt_id": aid, "task_id": e.get("task_id"), "retry_of": None})
        if e["kind"] == "offered":
            s.update(offered=e["t_wall"], retry_of=e.get("retry_of"))
        elif e["kind"] == "admitted":
            s["admitted"] = e["t_wall"]
        elif e["kind"] == "terminal":
            s.update(outcome=e["outcome"], ended=e["t_wall"], reason=e.get("reason", ""))
    return state


def reconcile(events) -> dict:
    """Every offered attempt must have exactly one explicit terminal outcome."""
    states = attempt_states(events)
    open_ = [a for a, s in states.items() if "outcome" not in s]
    counts: dict[str, int] = {}
    for s in states.values():
        counts[s.get("outcome", "open")] = counts.get(s.get("outcome", "open"), 0) + 1
    return {"attempts": len(states), "open": open_, "outcomes": counts, "reconciled": not open_}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(root: Path, name: str = "SHA256SUMS") -> Path:
    root = Path(root)
    lines = []
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name != name):
        lines.append(f"{sha256_file(p)}  {p.relative_to(root).as_posix()}")
    out = root / name
    out.write_text("\n".join(lines) + "\n")
    return out


def verify_manifest(root: Path, name: str = "SHA256SUMS") -> list[str]:
    """Return a list of problems (empty when every listed file matches)."""
    root = Path(root)
    problems = []
    for line in (root / name).read_text().splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        p = root / rel
        if not p.exists():
            problems.append(f"missing {rel}")
        elif sha256_file(p) != digest:
            problems.append(f"mismatch {rel}")
    return problems
