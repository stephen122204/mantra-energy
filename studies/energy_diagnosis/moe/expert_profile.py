"""Build policy data from recorded development runs (read-only on the campaign).

profile: experts ranked by routed tokens across the selected goals, for the
  static policy. Use development goals only; never evaluation goals.
future:  per task and pause index, the experts the following model call used,
  for the future diagnostic. Built from one reference goal per task.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from studies.energy_diagnosis.moe import event_log


def _goals(campaign, policy):
    for path in event_log.glob_goals(campaign):
        events = event_log.read(path)
        if events and events[0].get("policy", {}).get("name") == policy:
            record = json.loads(path.with_name("record.json").read_text())
            if (record.get("execution_status") != "completed"
                    or record.get("verifier", {}).get("outcome") != "pass"
                    or not any(e.get("event") == "goal_end" for e in events)):
                raise ValueError("profile sources must be completed, verified goals")
            yield record, events


def build_profile(campaign, policy="demand"):
    tokens, goals = Counter(), []
    for record, events in _goals(campaign, policy):
        goals.append(record["goal_execution_id"])
        for e in events:
            if e["event"] == "expert_demand":
                o = e["observation"]
                tokens[(o["layer"], o["expert"])] += o.get("tokens", 1)
    if not goals:
        raise ValueError("no goals for the requested policy")
    ranked = sorted(tokens.items(), key=lambda kv: (-kv[1], kv[0]))
    return dict(kind="static-profile-v1", source_policy=policy, source_goals=goals,
                experts=[[layer, expert, n] for (layer, expert), n in ranked])


def build_future_trace(campaign, policy="demand"):
    tasks, sources = {}, {}
    for record, events in _goals(campaign, policy):
        task = record["task_id"]
        if task in tasks:
            continue  # first reference goal per task
        # Model turns and tool pauses are different clocks: a malformed reply
        # can consume a model turn without launching a tool. Associate each
        # actual pause with the next completed model call, not calls[pause].
        following, waiting, active, current = {}, [], [], None
        pause_index = 0
        for e in events:
            if e["event"] == "tool_pause_start":
                pause_index += 1
                waiting.append(pause_index)
            elif e["event"] == "model_start":
                active, waiting = waiting, []
                current = Counter()
            elif e["event"] == "expert_demand" and current is not None:
                o = e["observation"]
                current[(o["layer"], o["expert"])] += o.get("tokens", 1)
            elif e["event"] == "model_end" and current is not None:
                for pause in active:
                    following[str(pause)] = [[layer, expert, n] for (layer, expert), n in sorted(current.items())]
                active = []
                current = None
        tasks[task] = following
        sources[task] = record["goal_execution_id"]
    if not tasks:
        raise ValueError("no goals for the requested policy")
    return dict(kind="future-trace-v2", diagnostic=True, source_policy=policy, source_goals=sources, tasks=tasks)


def dump(data, path):
    raw = (json.dumps(data, sort_keys=True, separators=(",", ":"),
                      allow_nan=False) + "\n").encode("utf-8")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def load(path):
    """Return (data, sha256 of the exact file bytes)."""
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=["profile", "future"])
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--policy", default="demand", help="Source arm whose goals are read")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    data = (build_profile if args.kind == "profile" else build_future_trace)(args.campaign, args.policy)
    print(dump(data, args.output))


if __name__ == "__main__":
    main()
