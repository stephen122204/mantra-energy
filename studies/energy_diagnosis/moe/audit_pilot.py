"""Read-only acceptance report for one guarded development stage.

This qualifies record consistency and an explicitly expected successful smoke
task, not a research effect, electrical calibration, or a full campaign.
"""
import argparse
import json
from pathlib import Path

from .audit_usefulness import audit_campaign as usefulness
from .audit_transfers import audit_campaign as transfers
from .audit_windows import audit as windows


def call_checks(calls, prefix_mode, require_timing=False):
    if not calls:
        return dict(model_calls_present=False)
    checks = dict(model_calls_present=True, token_accounting=True, prefix_mode=True)
    reused = 0
    # A turn refused before generation (context budget) is a recorded model outcome, not an
    # executed call: it carries no prefill/decode or timing. It must be the goal's final call.
    refused = [i for i, c in enumerate(calls)
               if c.get("adapter", {}).get("backend", {}).get("finish_reason") == "context_exhausted"]
    checks["refused_calls_terminal"] = all(
        i == len(calls) - 1 and calls[i]["adapter"]["backend"].get("tokens", {}).get("completion") == 0
        and not calls[i]["adapter"]["backend"].get("text") for i in refused)
    for index, call in enumerate(calls):
        if index in refused:
            continue
        backend = call.get("adapter", {}).get("backend", {})
        p, t = backend.get("prefix_cache", {}), backend.get("tokens", {})
        checks["prefix_mode"] &= p.get("mode") == prefix_mode
        fields = [p.get(k) for k in ("new_prefill_tokens", "reused_prefix_tokens", "decode_forward_tokens")]
        values = fields + [t.get("prompt"), t.get("completion")]
        valid = all(type(v) is int and v >= 0 for v in values)
        checks["token_accounting"] &= valid and (fields[0] + fields[1] == values[3] and fields[2] == values[4] - 1)
        if valid:
            reused += fields[1]
        if require_timing:
            timing = backend.get("generation_timing", {})
            stamps = [timing.get(k) for k in ("started_ns", "first_token_ready_ns", "last_token_ready_ns", "stream_end_ns")]
            valid_timing = (all(type(v) is int and v >= 0 for v in stamps)
                and stamps == sorted(stamps)
                and timing.get("version") == "host-token-availability-v1"
                and timing.get("generated_tokens") == t.get("completion")
                and timing.get("time_to_first_token_ns") == stamps[1] - stamps[0]
                and timing.get("subsequent_tokens_ns") == stamps[2] - stamps[1])
            checks["token_timing"] = checks.get("token_timing", True) and valid_timing
    if prefix_mode == "exact_prefix":
        checks["prefix_reuse_exercised"] = len(calls) - len(refused) > 1 and reused > 0
    return checks


def compare_calls(calls, reference):
    return dict(same_requests=[x["request"] for x in calls] == [x["request"] for x in reference],
                same_outputs=[x["adapter"]["content"] for x in calls] == [x["adapter"]["content"] for x in reference])


OUTCOME_CHECKS = ("native_correct_completion", "prefix_reuse_exercised")


def audit(stage, *, prefix_mode, reference=None, required_domains=(), require_timing=False):
    stage = Path(stage).resolve()
    root = stage / "campaign"
    checks, details, errors = {}, {}, []
    try:
        job = json.loads((stage / "job/status.json").read_text())
        checks["guarded_stage_completed"] = (job.get("status") == "completed" and job.get("returncode") == 0
            and job.get("cleanup_complete") is True and job.get("measurement_batch_valid") is not False)
        # A successful process without an enabled guard is not guarded evidence.
        observations = stage / "job/process-observations.jsonl"
        checks["guard_observations_present"] = observations.is_file() and observations.stat().st_size > 0
        w, t, u = windows(root), transfers(root), usefulness(root)
        details.update(windows=w, transfers=t, usefulness=u)
        checks["supported_native_policy"] = bool(u["goals"]) and all(x["policy"] != "builtin" for x in u["goals"])
        checks["counter_audit"] = w["audit_passed"] and all(x.get("all_domains_measured") for x in w["results"])
        checks["transfer_audit"] = t["observed_records_consistent"] and t["every_attempt_checked"]
        goals = sorted((root / "goals").glob("*/record.json"))
        checks["exactly_one_goal"] = len(goals) == 1 and w["attempts"] == 1
        manifest = root / "moe-manifest.json"
        checks["not_diagnostic"] = not (manifest.exists() and json.loads(manifest.read_text()).get("diagnostic"))
        if len(goals) != 1:
            raise ValueError("one goal is required for a development stage")
        g = goals[0].parent
        record = json.loads(goals[0].read_text())
        checks["native_correct_completion"] = (record["execution_status"] == "completed"
            and record["verifier"]["outcome"] == "pass" and record["simulated"] is False)
        inner = json.loads((g / "initialized-model-window.json").read_text())
        domains = {x["domain_id"] for x in inner["measurements"] if x["status"] == "valid"}
        checks["required_domains"] = set(required_domains) <= domains
        calls = json.loads((g / "model-calls.json").read_text())
        checks.update(call_checks(calls, prefix_mode, require_timing))
        if require_timing and checks.get("token_timing"):
            spans = [s for s in record["spans"] if s["kind"] == "model"]
            # Pair every call with its span; a refused (context-exhausted) call has a span but no
            # generation timing, and call_checks has already required it to be the final call.
            pairs = [(s, x["adapter"]["backend"].get("generation_timing")) for s, x in zip(spans, calls)
                     if x["adapter"]["backend"].get("finish_reason") != "context_exhausted"]
            checks["timing_inside_model_spans"] = len(spans) == len(calls) and all(
                t is not None and s["start_ns"] <= t["started_ns"] <= t["stream_end_ns"] <= s["end_ns"] for s, t in pairs)
        if reference is not None:
            ref = json.loads(Path(reference).read_text())
            checks.update(compare_calls(calls, ref))
        details["model_work"] = [x["adapter"].get("backend", {}).get("prefix_cache") for x in calls]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    protocol = {k: v for k, v in checks.items() if k not in OUTCOME_CHECKS}
    return dict(smoke_passed=bool(checks) and all(checks.values()) and not errors,
                # Validity never depends on the task outcome: failed goals are data.
                protocol_valid=bool(protocol) and all(protocol.values()) and not errors,
                outcome={k: checks[k] for k in OUTCOME_CHECKS if k in checks},
                checks=checks, errors=errors, details=details,
                scope="Development smoke only. Residency is not saved copy bytes; host overlap is not DMA overlap. "
                      "No energy benefit or general model fidelity is inferred. Genuine task failures remain recorded.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage")
    p.add_argument("--prefix-mode", choices=["disabled", "exact_prefix"], required=True)
    p.add_argument("--reference", help="Saved reference model-calls.json for conditional comparison")
    p.add_argument("--required-domain", action="append", default=[])
    p.add_argument("--require-token-timing", action="store_true")
    p.add_argument("--output", required=True)
    p.add_argument("--campaign", action="store_true",
                   help="Exit status reflects protocol validity only; task outcome is recorded, never gating")
    a = p.parse_args(argv)
    result = audit(a.stage, prefix_mode=a.prefix_mode, reference=a.reference, required_domains=a.required_domain, require_timing=a.require_token_timing)
    Path(a.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "details"}))
    return 0 if result["protocol_valid" if a.campaign else "smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
