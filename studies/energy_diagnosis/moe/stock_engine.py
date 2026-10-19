"""Shared pieces for stock comparison engines (vLLM, llama.cpp) behind the worker protocol.

Checkpoint integrity: hashing every weight file inside each measured goal charges several
kJ of hashing to the goal. With ``checkpoint_verification: "preflight"`` the full hash runs
once per block (``python -m studies.energy_diagnosis.moe.stock_engine preflight``) and each
goal only checks that the recorded manifest and file sizes still match.

Placement evidence: after the engine has loaded, the worker records where its memory lives
(``/proc/<pid>/numa_maps``) and which CPUs it may run on, for the worker and any engine
child process, so pinned host memory placement is recorded rather than assumed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def _sha(path, chunk=16 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                return h.hexdigest()
            h.update(block)


def _files(paths):
    out = {}
    for p in paths:
        p = Path(p).resolve(strict=True)
        out[str(p)] = dict(size=p.stat().st_size)
    return out


def preflight(paths, output):
    """Full hash of every file, once per block, outside any measured goal."""
    files = {}
    for p in paths:
        p = Path(p).resolve(strict=True)
        files[str(p)] = dict(size=p.stat().st_size, sha256=_sha(p))
    record = dict(version="stock-engine-preflight-v1", files=files)
    Path(output).write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify(paths, config):
    """Per-goal check. Returns evidence for the boot record; raises on mismatch."""
    mode = config.get("checkpoint_verification", "full")
    if mode == "full":
        return dict(mode="full", files={str(Path(p).resolve()): _sha(p) for p in paths})
    if mode != "preflight":
        raise ValueError("checkpoint_verification must be full or preflight")
    record_path = Path(config["checkpoint_preflight"]).resolve(strict=True)
    record = json.loads(record_path.read_text())
    if record.get("version") != "stock-engine-preflight-v1":
        raise ValueError("unsupported preflight record")
    current = _files(paths)
    for name, meta in current.items():
        saved = record["files"].get(name)
        if saved is None or saved["size"] != meta["size"]:
            raise ValueError(f"checkpoint file not covered by preflight or changed size: {name}")
    return dict(mode="preflight", record=str(record_path), record_sha256=_sha(record_path),
                files=sorted(current))


def _children(pid):
    kids = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
            if int(fields[1]) == pid:
                kids.append(int(stat.parent.name))
        except (OSError, ValueError, IndexError):
            continue
    return kids


def large_mappings(pid, min_mib=256):
    """Per-mapping NUMA placement for large mappings: pinned offload buffers show up as large
    anonymous mappings, mmapped GGUF weights as file mappings. Only resident pages are listed."""
    out = []
    try:
        lines = Path(f"/proc/{pid}/numa_maps").read_text().splitlines()
    except OSError as exc:
        return dict(error=str(exc))
    for line in lines:
        fields = line.split()
        page_kb, nodes, kind = 4, {}, "anon" if "anon=" in line else "other"
        for f in fields:
            if f.startswith("kernelpagesize_kB="):
                page_kb = int(f.split("=", 1)[1])
            elif f.startswith("file="):
                kind = "file:" + f.split("=", 1)[1]
            elif f.startswith("N") and "=" in f and f[1:].split("=", 1)[0].isdigit():
                node, pages = f[1:].split("=", 1)
                nodes[node] = int(pages)
        mib = {k: v * page_kb / 1024 for k, v in nodes.items()}
        if sum(mib.values()) >= min_mib:
            out.append(dict(address=fields[0], policy=fields[1], kind=kind,
                            mib_by_node={k: round(v, 1) for k, v in sorted(mib.items())}))
    return out


def summarize_mappings(maps):
    """Totals by kind (anon vs each file) and node, from large_mappings()."""
    totals = {}
    for m in maps if isinstance(maps, list) else []:
        key = "anon" if m["kind"] == "anon" else m["kind"]
        for node, mib in m["mib_by_node"].items():
            totals.setdefault(key, {}).setdefault(node, 0.0)
            totals[key][node] += mib
    return {k: {n: round(v, 1) for n, v in sorted(d.items())} for k, d in totals.items()}


def placement_tree(pid, min_mib=256):
    """Placement of a process and all its descendants, with large-mapping detail."""
    seen, queue, out = set(), [pid], []
    while queue:
        p = queue.pop()
        if p in seen:
            continue
        seen.add(p)
        entry = numa_placement(p)
        try:
            entry["cmd"] = Path(f"/proc/{p}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")[:160]
        except OSError:
            pass
        maps = large_mappings(p, min_mib)
        entry["large_mappings"] = maps
        entry["large_mapping_totals_mib"] = summarize_mappings(maps)
        out.append(entry)
        queue.extend(_children(p))
    return out


def numa_placement(pid):
    """Resident memory per NUMA node (MiB) and allowed CPUs for one process."""
    nodes = {}
    try:
        for line in Path(f"/proc/{pid}/numa_maps").read_text().splitlines():
            fields = line.split()
            page_kb = 4
            for f in fields:
                if f.startswith("kernelpagesize_kB="):
                    page_kb = int(f.split("=", 1)[1])
            for f in fields:
                if f.startswith("N") and "=" in f and f[1:].split("=", 1)[0].isdigit():
                    node, pages = f[1:].split("=", 1)
                    nodes[node] = nodes.get(node, 0) + int(pages) * page_kb
    except OSError as exc:
        return dict(pid=pid, error=str(exc))
    cpus = None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("Cpus_allowed_list:"):
                cpus = line.split(":", 1)[1].strip()
    except OSError:
        pass
    return dict(pid=pid, resident_mib_by_node={k: round(v / 1024, 1) for k, v in sorted(nodes.items())},
                cpus_allowed=cpus)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--output", required=True)
    pf.add_argument("paths", nargs="+")
    pl = sub.add_parser("placement", help="Placement of a process tree (large mappings per NUMA node)")
    pl.add_argument("pid", type=int)
    pl.add_argument("--output", required=True)
    pl.add_argument("--min-mib", type=int, default=256)
    a = p.parse_args(argv)
    if a.cmd == "placement":
        tree = placement_tree(a.pid, a.min_mib)
        Path(a.output).write_text(json.dumps(tree, indent=1) + "\n")
        print(json.dumps([dict(pid=e["pid"], totals=e.get("large_mapping_totals_mib")) for e in tree]))
        return
    if a.cmd == "preflight":
        r = preflight(a.paths, a.output)
        print(json.dumps(dict(files=len(r["files"]), output=a.output)))


if __name__ == "__main__":
    main()
