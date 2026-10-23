"""Prepare private challenge seeds once; reuse them across arms and resumes."""
import json
from pathlib import Path
import secrets


def read(root):
    path=Path(root)/'private/challenges.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('private challenges must not be symlinks')
    value=json.loads(path.read_text())
    seeds=value.get('seeds')
    if value.get('version')!='private-challenges-v1' or not isinstance(seeds,list) or len(seeds)!=3 \
            or any(type(s) is not int or not 0<=s<2**128 for s in seeds):
        raise ValueError('invalid private challenges')
    return seeds


def prepare(stage, existing):
    seeds=read(existing) if Path(existing).exists() else [secrets.randbits(128) for _ in range(3)]
    path=Path(stage)/'private/challenges.json'
    path.parent.mkdir()
    path.write_text(json.dumps(dict(version='private-challenges-v1',seeds=seeds),sort_keys=True)+'\n')
