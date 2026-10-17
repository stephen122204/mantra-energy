"""Prepare task-pack tasks once (outside any energy interval) and hand them to sessions.

    python -m studies.paper2.cohort.taskprep --specs specs.json --out PREP_DIR [--prepared-assets FROZEN]

Writes PREP_DIR/assets (the task pack), PREP_DIR/tasks/<task_id>.pkl and PREP_DIR/catalog.json
(task id, family, kind, asset/verifier hashes). Sessions copy public assets from the pack into
their own workspace; private challenge material never enters a workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def prepare_tasks(specs: list, out: Path, prepared_assets=None) -> list:
    import cloudpickle
    from studies.energy_diagnosis.moe import task_pack
    out = Path(out)
    pack = task_pack.prepare(out / "assets", specs, prepared_assets=prepared_assets)
    kind_of = {mod: kind for kind, mod in task_pack.MODULES.items()}
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    catalog = []
    for row, task in zip(pack.catalog(), pack.tasks):
        path = out / "tasks" / f"{task.task_id}.pkl"
        blob = cloudpickle.dumps(task)
        if path.exists() and path.read_bytes() != blob:
            raise ValueError(f"{path} exists with different content")
        path.write_bytes(blob)
        catalog.append(dict(row, task_kind=kind_of[pack.modules[task.task_id]], task_pickle=str(path.resolve()),
                            task_pickle_sha256=hashlib.sha256(blob).hexdigest()))
    (out / "catalog.json").write_text(json.dumps(catalog, indent=1))
    return catalog


def cohort_items(catalog: list, task_ids: list, *, repeat_tag: str = "r0") -> list:
    """Offer-ordered cohort items; a task may appear once per cohort (distinct pair keys)."""
    by_id = {c["task_id"]: c for c in catalog}
    missing = [t for t in task_ids if t not in by_id]
    if missing:
        raise KeyError(f"unknown task ids: {missing}")
    return [dict(task_id=t, task_pickle=by_id[t]["task_pickle"], task_kind=by_id[t]["task_kind"],
                 pair_key=f"{t}-{repeat_tag}") for t in task_ids]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prepared-assets", type=Path)
    a = ap.parse_args(argv)
    cat = prepare_tasks(json.loads(a.specs.read_text()), a.out, a.prepared_assets)
    print(json.dumps(dict(tasks=len(cat), catalog=str(a.out / "catalog.json"))))


if __name__ == "__main__":
    main()
