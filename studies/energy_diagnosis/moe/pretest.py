"""Check saved guarded task stages against an explicit execution contract.

This command reads completed stages; it never launches a model or changes results.
It checks execution and records, not task-suite representativeness.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from .audit_pilot import audit

DOMAINS = ("PACKAGE_SOCKET_0", "PACKAGE_SOCKET_1", "GPU_BOARD_0")
FAMILIES = dict(impl="python-implementation", program="python-transformation", etl="etl-sql-repair",
                repo="repository-repair", business="business-query", numerical="grouped-regression")


def check_stage(stage, expected, *, revision, limits):
    stage = Path(stage)
    result = dict(stage=str(stage), arm=expected["arm"], checks={}, errors=[])
    checks = result["checks"]
    try:
        audit_result = audit(stage, prefix_mode="exact_prefix", required_domains=DOMAINS, require_timing=True)
        checks["measurement_and_completion"] = audit_result["smoke_passed"]
        result["audit"] = audit_result
        m = json.loads((stage / "campaign/moe-manifest.json").read_text())
        checks["revision"] = m["source_revision"] == revision
        checks["protocol"] = m["agent"]["protocol"] == "chat-tools-v2"
        checks["engine"] = m["config"]["engine"] == "llamacpp"
        checks["model_file"] = m["config"]["gguf_path"] == expected["gguf_path"]
        checks["context"] = m["config"]["max_context"] == limits["context"]
        checks["limits"] = all(m["agent"].get(k) == limits[k] for k in (
            "max_turns", "max_tool_calls", "max_total_output_tokens", "max_output_tokens_per_turn"))
        checks["deadline"] = m["limits"]["goal_seconds"] == limits["goal_seconds"]
        specs = m["task_pack"]["specifications"]
        kind = expected.get("kind", "impl")
        if "task_pack" in expected:
            # Broader pre-tests pin the complete prepared envelope, including
            # helper hashes, and the selected task's asset/verifier identities.
            checks["qualified_task_path"] = (kind in FAMILIES
                and m["task_pack"] == expected["task_pack"]
                and any(s["kind"] == kind for s in specs)
                and m["task_catalog"] == [expected["task_catalog_entry"]]
                and expected["task_catalog_entry"].get("family") == FAMILIES[kind]
                and expected["task_catalog_entry"]["task_id"] == expected["task_id"])
        else:
            # Preserve the original, implementation-only smoke contract.
            checks["qualified_task_path"] = (kind == "impl" and len(specs) == 1 and specs[0]["kind"] == "impl"
                and expected.get("prompt", "v2") in {"v2", "v3"}
                and specs[0].get("prompt", "v2") == expected.get("prompt", "v2"))
        checks["task_identity"] = len(m["task_catalog"]) == 1 and m["task_catalog"][0]["task_id"] == expected["task_id"]
        goals = sorted((stage / "campaign/goals").glob("*/verification.json"))
        checks["one_verifier"] = len(goals) == 1
        if len(goals) != 1:
            raise ValueError("expected exactly one verification record")
        g = goals[0].parent
        v = json.loads(goals[0].read_text())
        trace = json.loads((g / "agent-trace.json").read_text())
        checks["verified_completion"] = v.get("status") == "returned" and v["result"].get("passed") is True and trace["outcome"] == "passed"
        result["protocol_slips"] = sum(t["kind"] in {"malformed", "no_action"} for t in trace["turns"])
        result["turns"] = len(trace["turns"])
        checks["clean_submission"] = result["protocol_slips"] == 0
        workspace = stage / "campaign/workspaces" / g.name
        if kind in {"impl", "program", "etl"}:
            source = workspace / ("pipeline.sql" if kind == "etl" else "solution.py")
            checks["saved_program"] = source.is_file() and not source.is_symlink()
            if checks["saved_program"]:
                result["solution_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        elif kind == "repo":
            changed = v.get("result", {}).get("changed_files", [])
            artifacts = {}
            for relative in changed:
                source = workspace / relative
                if (not source.is_symlink() and source.is_file()
                        and workspace.resolve() in source.resolve().parents):
                    artifacts[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
            checks["saved_program"] = bool(changed) and len(artifacts) == len(changed)
            result["changed_file_sha256"] = artifacts
        else:
            # SQL analysis and numerical-tool tasks return structured answers;
            # requiring a Python file here would reject valid task completions.
            checks["saved_program"] = kind in {"business", "numerical"}
        window = json.loads((g / "initialized-model-window.json").read_text())
        energies = {}
        for phase in ("before_task_window", "task_window", "verifier_window"):
            rows = window.get(phase, {}).get("measurements", [])
            ok = (len(rows) == len(DOMAINS) and {r.get("domain_id") for r in rows} == set(DOMAINS)
                  and all(r.get("status") == "valid" and isinstance(r.get("energy_j"), (float, int))
                          and math.isfinite(r["energy_j"]) and r["energy_j"] >= 0 for r in rows))
            checks[phase + "_energy"] = ok
            energies[phase] = sum(r["energy_j"] for r in rows) if ok else None
        result["energy_j"] = energies
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    result["passed"] = bool(checks) and all(checks.values()) and not result["errors"]
    outcome_checks = {"measurement_and_completion", "verified_completion", "clean_submission", "saved_program"}
    result["record_valid"] = (result.get("audit", {}).get("protocol_valid", False)
        and (checks.get("saved_program", False) or not checks.get("verified_completion", False))
        and all(v for k,v in checks.items() if k not in outcome_checks) and not result["errors"])
    return result


def check(contract):
    stages = contract.get("stages", [])
    if not 2 <= len(stages) <= 32:
        raise ValueError("provide 2..32 explicitly approved smoke stages")
    identities = [(s["arm"], s["task_id"], s.get("replicate", 0)) for s in stages]
    if len(set(identities)) != len(stages) or len({s["path"] for s in stages}) != len(stages):
        raise ValueError("duplicate smoke stage")
    arms = {s["arm"] for s in stages}
    if len(arms) != 2:
        raise ValueError("exactly two named arms are required")
    models = [{s["gguf_path"] for s in stages if s["arm"] == arm} for arm in sorted(arms)]
    if any(len(paths) != 1 for paths in models) or models[0] == models[1]:
        raise ValueError("each arm requires one distinct model file")
    task_sets = [{(s["task_id"], s.get("replicate", 0)) for s in stages if s["arm"] == arm} for arm in sorted(arms)]
    if task_sets[0] != task_sets[1]:
        raise ValueError("both arms must cover the same task/replicate slots")
    rows = [check_stage(s["path"], s, revision=contract["revision"], limits=contract["limits"]) for s in stages]
    return dict(version="task-pretest-v2", implementation_pretest_passed=all(r["passed"] for r in rows),
                task_pretest_passed=all(r["passed"] for r in rows), records_valid=all(r["record_valid"] for r in rows),
                campaign_authorized=False, scope="Guarded execution, correct completion, settings and CPU/GPU record integrity only",
                stages=rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("contract", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args(argv)
    result = check(json.loads(a.contract.read_text()))
    with a.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k != "stages"}))
    return 0 if result["implementation_pretest_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
