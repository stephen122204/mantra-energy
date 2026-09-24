"""Fail-closed Linux process observations for a separately reserved machine.

This sampled check cannot detect every short-lived process and is not access
control. Use it with exclusive allocation, operator coordination and the lock.
No command lines or environment variables are collected.
"""
import argparse
import json
import os
from pathlib import Path
import time


class InterferenceDetected(RuntimeError):
    pass


def snapshot(proc=Path("/proc")):
    rows = []
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            text = (path / "stat").read_text()
            left, right = text.index("("), text.rindex(")")
            fields = text[right + 2 :].split()
            if int(fields[6]) & 0x00200000:  # Linux PF_KTHREAD; never user work.
                continue
            if fields[0] == "Z":
                continue
            rows.append(
                dict(
                    pid=int(path.name),
                    ppid=int(fields[1]),
                    name=text[left + 1 : right],
                    start_ticks=int(fields[19]),
                    cpu_ticks=int(fields[11]) + int(fields[12]),
                    uid=path.stat().st_uid,
                )
            )
        except FileNotFoundError:
            continue  # Exited between directory listing and read.
    return dict(
        boot_id=(proc / "sys/kernel/random/boot_id").read_text().strip(),
        monotonic_ns=time.monotonic_ns(),
        ticks_per_second=os.sysconf("SC_CLK_TCK"),
        processes=rows,
    )


SSHD_NAMES = frozenset({"sshd", "sshd-session", "sshd-auth"})


def _privsep_uids():
    import pwd
    uids = {0}
    for name in ("sshd", "sshd-auth"):
        try:
            uids.add(pwd.getpwnam(name).pw_uid)
        except KeyError:
            pass
    return uids


def preauth_sshd(rows, allowed, privsep_uids):
    """Unauthenticated connection handlers under a baseline sshd listener.

    Internet scanners on a public IP spawn these continuously. They run only
    as root or the sshd privilege-separation user; an authenticated login
    adds a user-owned process below them and is then no longer exempt.
    """
    by_pid = {row["pid"]: row for row in rows}
    children = {}
    for row in rows:
        children.setdefault(row["ppid"], []).append(row)
    exempt = set()
    for row in rows:
        if row["name"] not in SSHD_NAMES or row["uid"] not in privsep_uids or identity(row) in allowed:
            continue
        parent = by_pid.get(row["ppid"])
        while parent is not None and parent["name"] in SSHD_NAMES and identity(parent) not in allowed:
            parent = by_pid.get(parent["ppid"])
        if parent is None or parent["name"] not in SSHD_NAMES or identity(parent) not in allowed:
            continue
        stack, user_below = list(children.get(row["pid"], [])), False
        while stack:
            child = stack.pop()
            if child["name"] not in SSHD_NAMES or child["uid"] not in privsep_uids:
                user_below = True
                break
            stack.extend(children.get(child["pid"], []))
        if not user_below:
            exempt.add(identity(row))
    return exempt


def identity(row):
    return row["pid"], row["start_ticks"], row["uid"], row["name"]


def relatives(rows, root):
    parents = {row["pid"]: row["ppid"] for row in rows}
    descendants = {root}
    while True:
        added = {
            pid for pid, parent in parents.items() if parent in descendants
        } - descendants
        if not added:
            break
        descendants.update(added)
    ancestors = set()
    parent = parents.get(root)
    while parent and parent not in ancestors:
        ancestors.add(parent)
        parent = parents.get(parent)
    return descendants, ancestors


class ProcessGuard:
    def __init__(self, baseline, log, root, reader=snapshot, max_background_cpu=0.25):
        if not 0 < max_background_cpu <= 1:
            raise ValueError(
                "background CPU limit must be within (0, 1] core-seconds per second"
            )
        self.baseline = baseline
        self.allowed = {identity(row) for row in baseline["processes"]}
        self.root, self.reader, self.log = root, reader, log
        self.limit = max_background_cpu
        self.privsep_uids = _privsep_uids()
        self.previous = None
        self.owned = set()
        self.check()

    def surviving_owned(self):
        return [
            row["pid"]
            for row in self.reader()["processes"]
            if identity(row) in self.owned
        ]

    def check(self):
        current = self.reader()
        descendants, ancestors = relatives(current["processes"], self.root)
        self.owned.update(
            identity(row)
            for row in current["processes"]
            if row["pid"] in descendants and row["pid"] != self.root
        )
        # A process once observed below the root stays owned after reparenting:
        # when a supervisor exits before its worker is reaped, the worker moves
        # under init but is still this job's work (and is cleaned up as owned).
        foreign = [
            row
            for row in current["processes"]
            if row["pid"] not in descendants | ancestors and identity(row) not in self.owned
        ]
        # Pre-auth sshd handlers are exempt from the process check only; their
        # CPU still counts against the background budget below.
        exempt = preauth_sshd(current["processes"], self.allowed, self.privsep_uids)
        unexpected = [row for row in foreign if identity(row) not in self.allowed and identity(row) not in exempt]
        reasons = []
        if current["boot_id"] != self.baseline["boot_id"]:
            reasons.append("baseline belongs to another boot")
        if unexpected:
            reasons.append("unapproved external process")
        delta_cpu = None
        elapsed = None
        if self.previous is not None:
            elapsed = (current["monotonic_ns"] - self.previous["monotonic_ns"]) / 1e9
            previous = {identity(row): row for row in self.previous["processes"]}
            delta_cpu = (
                sum(
                    max(0, row["cpu_ticks"] - previous[identity(row)]["cpu_ticks"])
                    for row in foreign
                    if identity(row) in previous
                )
                / current["ticks_per_second"]
            )
            if elapsed <= 0 or delta_cpu > self.limit * elapsed:
                reasons.append("background CPU budget exceeded or invalid clock")
        record = dict(
            snapshot=current,
            owned_pids=sorted(descendants),
            ancestor_pids=sorted(ancestors),
            unexpected=unexpected,
            background_cpu_seconds=delta_cpu,
            interval_seconds=elapsed,
            background_cpu_limit=self.limit,
            reasons=reasons,
        )
        with self.log.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
        self.previous = current
        if reasons:
            raise InterferenceDetected("; ".join(reasons))
        return record


def main():
    parser = argparse.ArgumentParser(
        description="Save a private process baseline for human review before guarded execution."
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with Path(args.output).open("x") as stream:
        json.dump(snapshot(), stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
