"""The per-expert event log: written gzip-compressed (deterministic bytes); older runs used plain JSON."""
import gzip
import json
from pathlib import Path

NAMES = ("expert-events.json.gz", "expert-events.json")


def encode(events):
    """Deterministic gzip of compact sorted JSON (mtime 0), so equal content gives equal bytes/hash."""
    return gzip.compress(json.dumps(events, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n",
                         mtime=0)


def decode(raw, name):
    return json.loads(gzip.decompress(raw) if str(name).endswith(".gz") else raw)


def path_in(goal_dir):
    """The goal's event log, whichever format it was written in (None if absent)."""
    for name in NAMES:
        path = Path(goal_dir) / name
        if path.exists():
            return path
    return None


def read(path):
    return decode(Path(path).read_bytes(), path)


def glob_goals(campaign):
    """Event-log paths of every goal under campaign/goals, in goal order."""
    out = []
    for goal in sorted(Path(campaign).glob("goals/*")):
        path = path_in(goal)
        if path is not None:
            out.append(path)
    return out
