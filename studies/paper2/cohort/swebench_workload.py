"""SWE-bench Verified tasks for the cohort runner (GoalExecutor-compatible runtime).

Preparation (outside any energy interval, needs docker):
  ``prepare_instances`` pulls the official evaluation image of each instance, removes every git
  ref and unreachable object except the base commit (so later upstream commits, including the
  fix, are not readable), checks the tree is clean, and commits a local sanitized image. The
  task asset holds only public fields (instance id, repo, base commit, problem statement).

Execution (inside a session): one container per attempt from the sanitized image with
``--network none`` and CPU/memory limits; the only tool is ``bash`` (``cd /testbed``; bounded
time and output). At session end ``finalize`` stores ``git diff`` of the working tree as the
model patch and removes the container.

Verification (after the cohort): the official SWE-bench harness evaluates the patch in a fresh
official image (hidden tests applied there); resolved == pass. ``qualify_instance`` runs the same
harness on the gold patch (must resolve) and an empty patch (must not) before an instance is used.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

FAMILY = "swebench-verified"
VERSION = "swebench-verified-bash-v1"
SANITIZED = "paper2/sweb-sanitized"
PROMPT = ("You are working in the git repository at /testbed (the {repo} project at commit {base}). "
          "Resolve the issue below by editing non-test source files. Use the bash tool to inspect files, "
          "edit them and run commands or tests; it runs in /testbed and has no network access. "
          "Do not modify or add test files. When the change is complete, call submit_answer with "
          'arguments {{"answer": {{}}}}; the working-tree diff is your submission.\n\n<issue>\n{problem}\n</issue>')


def official_image(instance_id: str, namespace: str = "swebench") -> str:
    return f"{namespace}/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def sanitized_image(instance_id: str) -> str:
    return f"{SANITIZED}:{instance_id.replace('__', '_1776_').lower()}"


Runner = Callable[..., tuple]  # (argv, timeout, cwd=None) -> (returncode, stdout, stderr)


def run_cmd(argv: list, timeout: float, cwd=None) -> tuple:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "timeout"


SANITIZE = ("set -e; cd /testbed; test -z \"$(git status --porcelain)\"; git checkout -q --detach {base}; "
            "for r in $(git for-each-ref --format='%(refname)'); do git update-ref -d \"$r\"; done; "
            "git stash clear || true; git reflog expire --expire=now --all; git gc -q --prune=now; "
            "git checkout -q -b main; test \"$(git rev-parse HEAD)\" = {base}; "
            "test \"$(git rev-list --all | wc -l)\" = \"$(git rev-list HEAD | wc -l)\"")


def prepare_instances(rows: list, out: Path, *, run: Runner = run_cmd, docker: str = "docker") -> list:
    """rows: SWE-bench dataset rows. Returns cohort catalog entries (task pickles written)."""
    import cloudpickle
    from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
    out = Path(out)
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    catalog = []
    for row in rows:
        iid, base = row["instance_id"], row["base_commit"]
        img, san = official_image(iid), sanitized_image(iid)
        rc, _, err = run([docker, "image", "inspect", san], 60)
        if rc != 0:
            for argv, t in (([docker, "pull", "-q", img], 3600),):
                rc, _, err = run(argv, t)
                if rc != 0:
                    raise RuntimeError(f"{iid}: docker pull failed: {err[-300:]}")
            name = f"p2-prep-{hashlib.sha1(iid.encode()).hexdigest()[:10]}"
            run([docker, "rm", "-f", name], 60)
            rc, _, err = run([docker, "run", "-d", "--name", name, "--network", "none", img, "sleep", "infinity"], 300)
            if rc != 0:
                raise RuntimeError(f"{iid}: container start failed: {err[-300:]}")
            try:
                rc, o, err = run([docker, "exec", name, "bash", "-lc", SANITIZE.format(base=base)], 1800)
                if rc != 0:
                    raise RuntimeError(f"{iid}: git sanitization failed: {(o + err)[-400:]}")
                rc, _, err = run([docker, "commit", name, san], 1800)
                if rc != 0:
                    raise RuntimeError(f"{iid}: docker commit failed: {err[-300:]}")
            finally:
                run([docker, "rm", "-f", name], 120)
        rc, digest, _ = run([docker, "image", "inspect", "--format", "{{.Id}}", san], 60)
        asset = out / "assets" / iid
        asset.mkdir(parents=True, exist_ok=True)
        public = dict(instance_id=iid, repo=row["repo"], base_commit=base, problem_statement=row["problem_statement"],
                      sanitized_image=san, sanitized_image_id=digest.strip(), official_image=official_image(iid),
                      difficulty=row.get("difficulty"))
        (asset / "instance.json").write_text(json.dumps(public, indent=1, sort_keys=True))
        task = PilotTask(task_id=iid, family=FAMILY, lineage=VERSION, asset_path=asset, expected={},
                         asset_sha256=_hash(asset), eligible_controls=(),
                         prompt=PROMPT.format(repo=row["repo"], base=base[:12], problem=row["problem_statement"]))
        blob = cloudpickle.dumps(task)
        p = out / "tasks" / f"{iid}.pkl"
        p.write_bytes(blob)
        catalog.append(dict(task_id=iid, family=FAMILY, task_kind="swebench", task_pickle=str(p.resolve()),
                            task_pickle_sha256=hashlib.sha256(blob).hexdigest(), asset_sha256=task.asset_sha256,
                            sanitized_image_id=public["sanitized_image_id"], difficulty=row.get("difficulty")))
    (out / "catalog.json").write_text(json.dumps(catalog, indent=1))
    return catalog


@dataclass
class BashTool:
    docker: str
    container: str
    command: str
    timeout_s: float = 180.0
    max_chars: int = 10000

    def execute(self, workers=1):
        rc, out, err = run_cmd([self.docker, "exec", "-w", "/testbed", self.container, "bash", "-lc",
                                f"timeout {int(self.timeout_s)} bash -c {shlex.quote(self.command)}"], self.timeout_s + 30)
        text = (out or "") + (("\n[stderr]\n" + err) if err and err != "timeout" else "")
        truncated = len(text) > self.max_chars
        if truncated:
            half = self.max_chars // 2
            text = text[:half] + f"\n[... {len(text) - self.max_chars} characters omitted ...]\n" + text[-half:]
        return dict(exit_code=rc, output=text, truncated=truncated, timed_out=rc == 124)


class SweBenchRuntime:
    """GoalExecutor runtime for one SWE-bench attempt (one container per attempt)."""

    def __init__(self, root, *, docker: str = "docker", cpus: str = "4", memory: str = "16g",
                 tool_timeout_s: float = 180.0, max_output_chars: int = 10000, run: Runner = run_cmd,
                 harness_python: str = "python"):
        self.root, self.docker, self.cpus, self.memory = Path(root), docker, cpus, memory
        self.harness_python = harness_python
        self.tool_timeout_s, self.max_output_chars, self._run = tool_timeout_s, max_output_chars, run
        self.container: Optional[str] = None
        self.instance: Optional[dict] = None
        self.patch_path: Optional[Path] = None
        # PackRuntime-compatible surface used by session.py
        self.active = self

    def begin(self, task, lease):
        from studies.energy_diagnosis.workloads.pilot_tasks import _hash
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError("task assets changed")
        self.instance = json.loads((Path(task.asset_path) / "instance.json").read_text())
        self.workspace = self.root / "workspaces" / lease.execution_id
        self.workspace.mkdir(parents=True, exist_ok=False)
        self.container = f"p2-{lease.execution_id}"[:120]
        rc, out, err = self._run([self.docker, "run", "-d", "--name", self.container, "--network", "none",
                                  "--cpus", self.cpus, "--memory", self.memory, "--pids-limit", "4096",
                                  self.instance["sanitized_image"], "sleep", "infinity"], 300)
        if rc != 0:
            raise RuntimeError(f"container start failed: {err[-300:]}")

    def context(self, task):
        return dict(family=FAMILY, tools={"bash": {
            "description": f"Run one bash command in /testbed (no network; {int(self.tool_timeout_s)} s limit; "
                           f"output over {self.max_output_chars} characters is truncated in the middle).",
            "parameters": dict(type="object", properties=dict(command=dict(type="string", minLength=1)),
                               required=["command"], additionalProperties=False)}})

    def tool(self, task, call):
        args = call.get("args")
        if call.get("tool") != "bash" or not isinstance(args, dict) or set(args) != {"command"} \
                or not isinstance(args["command"], str) or not args["command"].strip():
            raise ValueError("tool request outside declared schema")
        return BashTool(self.docker, self.container, args["command"], self.tool_timeout_s, self.max_output_chars)

    def finalize(self, task):
        """Store the working-tree diff (tracked and new files) as the model patch; remove the container."""
        if not self.container:
            return None
        try:
            rc, out, err = self._run([self.docker, "exec", "-w", "/testbed", self.container, "bash", "-lc",
                                      "git add -A && git diff --cached --binary HEAD"], 300)
            self.patch_path = self.workspace / "model.patch"
            self.patch_path.write_text(out if rc == 0 else "")
            (self.workspace / "finalize.json").write_text(json.dumps(dict(rc=rc, err=err[-500:], bytes=len(out))))
        finally:
            self._run([self.docker, "rm", "-f", self.container], 120)
            self.container = None
        return self.patch_path

    def verify(self, task, answer):
        patch = self.patch_path.read_text() if self.patch_path and self.patch_path.exists() else ""
        return evaluate_patch(self.instance["instance_id"], patch, self.workspace / "eval", python=self.harness_python)

    def verification_callable(self, task):
        return self.verify


def evaluate_patch(instance_id: str, patch: str, work: Path, *, run: Runner = run_cmd, python: str = "python",
                   dataset: str = "princeton-nlp/SWE-bench_Verified", timeout_s: float = 3600) -> dict:
    """Official harness on one patch; returns the verifier result dict used by the session."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    run_id = f"p2-{hashlib.sha1((instance_id + patch).encode()).hexdigest()[:12]}"
    preds = work / "predictions.jsonl"
    preds.write_text(json.dumps(dict(instance_id=instance_id, model_name_or_path="paper2", model_patch=patch)) + "\n")
    if not patch.strip():
        return dict(passed=False, reason="empty patch", run_id=run_id)
    rc, out, err = run([python, "-m", "swebench.harness.run_evaluation", "--dataset_name", dataset, "--split", "test",
                        "--instance_ids", instance_id, "--predictions_path", str(preds), "--max_workers", "1",
                        "--run_id", run_id, "--namespace", "swebench", "--timeout", "1800", "--report_dir", str(work)],
                       timeout_s, cwd=str(work))  # the harness writes logs/ under its working directory
    reports = list(work.glob(f"logs/run_evaluation/{run_id}/paper2/{instance_id}/report.json"))
    if not reports:
        return dict(passed=False, reason=f"harness produced no report (rc={rc}): {(out + err)[-400:]}", run_id=run_id,
                    infrastructure=True)
    try:
        report = json.loads(reports[0].read_text())
        rep = report.get(instance_id) if isinstance(report, dict) else None
    except (OSError, ValueError):
        rep = None
    if rc != 0 or not isinstance(rep, dict) or not isinstance(rep.get("resolved"), bool):
        return dict(passed=False, reason=f"invalid harness report or unsuccessful exit (rc={rc})", run_id=run_id,
                    infrastructure=True)
    return dict(passed=rep["resolved"], reason="resolved" if rep["resolved"] else "not resolved",
                run_id=run_id, tests_status=rep.get("tests_status"))


def qualify_instance(row: dict, work: Path, **kw) -> dict:
    """Gold patch must resolve; empty and no-op patches must not."""
    gold = evaluate_patch(row["instance_id"], row["patch"], Path(work) / "gold", **kw)
    noop = evaluate_patch(row["instance_id"], "diff --git a/README_P2 b/README_P2\nnew file mode 100644\n--- /dev/null\n"
                          "+++ b/README_P2\n@@ -0,0 +1 @@\n+noop\n", Path(work) / "noop", **kw)
    # both controls need a completed harness report: a crashed no-op run is not a rejected solution
    valid = not gold.get("infrastructure") and not noop.get("infrastructure") and noop.get("reason") == "not resolved"
    return dict(instance_id=row["instance_id"], gold_resolves=gold["passed"], noop_resolves=noop["passed"],
                controls_valid=valid, qualified=bool(valid and gold["passed"] and not noop["passed"]),
                gold=gold, noop=noop, checked=time.time())


def _rows(raw_dir: Path, ids: list) -> list:
    rows = {}
    for f in sorted(Path(raw_dir).glob("swev_*.json")):
        for r in json.loads(f.read_text())["rows"]:
            rows[r["row"]["instance_id"]] = r["row"]
    missing = [i for i in ids if i not in rows]
    if missing:
        raise KeyError(f"instances not in {raw_dir}: {missing}")
    return [rows[i] for i in ids]


def main(argv=None):
    """prepare/qualify CLI (node, docker required, outside measurements)."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("prepare", "qualify"))
    ap.add_argument("--raw", type=Path, required=True, help="fetch_task_metadata.sh output (swev_*.json)")
    ap.add_argument("--selection", type=Path, required=True, help="JSON with instances[].instance_id")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--harness-python", default="python")
    a = ap.parse_args(argv)
    ids = [x["instance_id"] for x in json.loads(a.selection.read_text())["instances"]]
    rows = _rows(a.raw, ids)
    if a.action == "prepare":
        print(json.dumps(prepare_instances(rows, a.out), indent=1))
    else:
        res = [qualify_instance(r, a.out / "qualify" / r["instance_id"], python=a.harness_python) for r in rows]
        (a.out / "qualification.json").write_text(json.dumps(res, indent=1, default=str))
        print(json.dumps([{k: r[k] for k in ("instance_id", "gold_resolves", "noop_resolves", "qualified")} for r in res]))


if __name__ == "__main__":
    main()
