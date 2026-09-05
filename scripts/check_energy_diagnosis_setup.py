"""Check portable study handoff and planning artifacts; never run a workload."""
from pathlib import Path
import csv
import json
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "docs" / "agent-context"


def main():
    errors = []
    for doc in CONTEXT.rglob("*.md"):
        for link in re.findall(r"\]\(([^)]+)\)", doc.read_text()):
            target = link.split("#", 1)[0]
            if not target or re.match(r"^[a-zA-Z]+:", target):
                continue
            if not (doc.parent / target).exists():
                errors.append(f"Broken link in {doc.relative_to(ROOT)}: {target}")
    provenance = json.loads((ROOT / "studies/energy_diagnosis/provenance.json").read_text())
    for name in ("reviewed_upstream_commit", "chosen_upstream_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}", provenance[name]):
            errors.append(f"Invalid provenance {name}")
    planner = CONTEXT / "starter" / "make_run_plan.py"
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "planned"
        completed = subprocess.run(
            [sys.executable, str(planner), "--out", str(out)],
            capture_output=True, text=True, check=False,
        )
        if completed.returncode:
            errors.append(f"Planner failed: {completed.stderr}")
        else:
            report = json.loads((out / "planning-report.json").read_text())
            with (out / "run-plan.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            if len(rows) != report["planned_executions"] or not rows:
                errors.append("CSV/report execution count mismatch or empty plan")
            if any(row["status"] != "planned" or row["actual_execution_id"] for row in rows):
                errors.append("Planner claims an actual execution")
            strict_out = Path(temp) / "strict"
            strict = subprocess.run(
                [sys.executable, str(planner), "--require-ready", "--out", str(strict_out)],
                capture_output=True, text=True, check=False,
            )
            expected = 0 if report["declaration_fields_complete"] else 2
            if strict.returncode != expected:
                errors.append("Strict readiness exit does not match declaration completeness")
            if expected == 2 and strict_out.exists():
                errors.append("Unready strict check unexpectedly wrote outputs")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PASS: portable handoff links, provenance, planner CSV/report and readiness behavior")
    print("Scope: setup/planning only; no upstream runtime test, inference or hardware measurement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
