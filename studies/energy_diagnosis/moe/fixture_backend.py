"""Deterministic device simulator; never selected by native-mode failures."""
from dataclasses import asdict, replace
import json
import threading
import time

from .backend import CONTROLS
from .control import Expert


class FixtureDevice:
    def __init__(self, config):
        self.case = config.get("fixture_case", "success")
        self.delay = config.get("transfer_seconds", 0.02)
        self.experts = {i: Expert(0, i, i + 100, i, 64, "cpu") for i in range(4)}
        self.records, self.demand_rows, self.jobs = [], [], []
        self.lock = threading.Lock()
        self.generation = 0
        self.boot = dict(controls=CONTROLS, mode="fixture", applied_config=config)

    def snapshot(self, _):
        with self.lock:
            if any(not j["done"] for j in self.jobs):
                raise RuntimeError("snapshot before transfer drain")
            return [asdict(e) for e in self.experts.values()]

    def prepare(self, arg):
        with self.lock:
            inflight = sum(64 for j in self.jobs if not j["done"])
            nodes = []
            for raw in arg["experts"]:
                e = Expert(**raw)
                if (
                    e.node not in self.experts
                    or self.experts[e.node].tensor != e.tensor
                ):
                    raise ValueError("unknown expert")
                if (
                    self.case == "locked"
                    or inflight + 64 > arg["budget"]
                    or any(j["node"] == e.node and not j["done"] for j in self.jobs)
                ):
                    continue
                job = dict(
                    node=e.node,
                    generation=arg["generation"],
                    enqueue_ns=time.monotonic_ns(),
                    start_ns=0,
                    done=False,
                )
                self.jobs.append(job)
                threading.Thread(
                    target=self._transfer, args=(job,), daemon=True
                ).start()
                nodes.append(e.node)
                inflight += 64
            if self.case == "broken_ack":
                nodes.append(999)
            return dict(
                accepted_nodes=nodes,
                accepted_bytes=64 * len(nodes),
                rejected_bytes=64 * (len(arg["experts"]) - len(nodes)),
                inflight_bytes=inflight,
            )

    def _transfer(self, job):
        with self.lock:
            if job["done"]:
                return
            job["start_ns"] = time.monotonic_ns()
        time.sleep(self.delay)
        with self.lock:
            self.experts[job["node"]] = replace(
                self.experts[job["node"]], device="cuda:0"
            )
            self._finish(job, "completed", 64)

    def _finish(self, job, outcome, transferred):
        end = time.monotonic_ns()
        job["done"] = True
        self.records.append(
            dict(
                layer=0,
                expert=job["node"],
                tensor=job["node"] + 100,
                node=job["node"],
                generation=job["generation"],
                bytes=64,
                transferred_bytes=transferred,
                outcome=outcome,
                enqueue_ns=job["enqueue_ns"],
                start_ns=job["start_ns"],
                end_ns=end,
                queue_wait_ns=(job["start_ns"] or end) - job["enqueue_ns"],
                transfer_ns=end - job["start_ns"] if job["start_ns"] else 0,
                native_clock_domain="fixture:host-monotonic",
            )
        )

    def cancel(self, arg):
        if self.case == "cancel_failure":
            raise RuntimeError("injected cancellation failure")
        cancelled = 0
        with self.lock:
            for j in self.jobs:
                if (
                    not j["done"]
                    and not j["start_ns"]
                    and j["generation"] == arg["generation"]
                ):
                    self._finish(j, "cancelled", 0)
                    cancelled += 64
        return cancelled

    def drain(self, arg):
        if self.case == "drain_failure":
            raise RuntimeError("injected drain failure")
        deadline = time.monotonic() + arg["timeout"]
        while True:
            with self.lock:
                if all(j["done"] for j in self.jobs):
                    return {"inflight_bytes": 0}
            if time.monotonic() >= deadline:
                raise TimeoutError("fixture transfers did not drain")
            time.sleep(0.001)

    def transfers(self, _):
        with self.lock:
            rows, self.records = self.records, []
        return dict(records=rows, dropped=1 if self.case == "dropped" else 0)

    def demands_rpc(self, _):
        rows, self.demand_rows = self.demand_rows, []
        return rows

    def generate(self, arg):
        if self.case == "model_failure":
            raise RuntimeError("injected model failure")
        if self.case == "model_timeout":
            time.sleep(60)
        chat = "messages" in arg
        if chat:
            from studies.energy_diagnosis.agent_protocol import legacy_context
            context = legacy_context(arg, arg.get("meta") or {})
            if self.case == "truncated_output":
                return dict(text='<tool_call>\n{"name": "sql", "argum', finish_reason="length",
                            tokens=dict(prompt=len(json.dumps(arg["messages"])), completion=arg["max_tokens"]), hook_ns=0)
            if self.case == "no_action":
                return dict(text="I have checked the data.", finish_reason="stop",
                            tokens=dict(prompt=len(json.dumps(arg["messages"])), completion=6), hook_ns=0)
        else:
            context = json.loads(arg["prompt"])
        results = context.get("tool_results", [])
        expert = 1 if self.case == "wrong_prediction" and results else 0
        self.demand_rows.append(
            dict(
                layer=0,
                expert=expert,
                tokens=1,
                resident_at_dispatch=self.experts[expert].device.startswith("cuda"),
            )
        )
        # Return the expert to CPU to expose repeated preparation in fixtures.
        with self.lock:
            self.experts[expert] = replace(self.experts[expert], device="cpu")
        if context.get("family") in {"business-query", "grouped-regression", "etl-sql-repair", "python-transformation"}:
            from .task_pack_fixture import ScriptedModel
            decision = json.loads(ScriptedModel(self.case).call(json.dumps(context), 0)["content"])
        elif context.get("family") == "sql-query":
            if not results:
                decision = {"tool_calls": [dict(id="schema", tool="sql", args=dict(action="schema"))]}
            elif len(results) == 1:
                query = ("SELECT CAST(strftime('%H', tpep_pickup_datetime) AS INTEGER) AS hour, COUNT(*) AS trips "
                         "FROM trips JOIN zones ON trips.PULocationID=zones.LocationID "
                         "WHERE Borough='Manhattan' AND payment_type=1 AND trip_distance>0 AND fare_amount>0 "
                         "AND tpep_pickup_datetime >= '2025-01-01 00:00:00' "
                         "AND tpep_pickup_datetime < '2025-02-01 00:00:00' GROUP BY hour ORDER BY hour")
                decision = {"tool_calls": [dict(id="query", tool="sql", args=dict(action="query", sql=query))]}
            else:
                counts = [0] * 24
                for hour, count in results[-1]["result"]["rows"]:
                    counts[hour] = count
                decision = {"answer": dict(hour_counts=counts, total_trips=sum(counts))}
        elif context.get("family") == "repository-repair":
            calls = [
                dict(id="read", tool="repo", args=dict(action="read")),
                dict(
                    id="edit",
                    tool="repo",
                    args=dict(
                        action="write",
                        content="def net_cents(price, count, discount):\n    return (price * count * (100 - discount) + 50) // 100\n",
                    ),
                ),
                dict(id="test", tool="repo", args=dict(action="test")),
            ]
            decision = (
                {"tool_calls": [calls[len(results)]]}
                if len(results) < 3
                else {"answer": {"done": True}}
            )
        elif context.get("family") == "etl-repair":
            calls = [
                dict(id="read", tool="etl", args=dict(action="read")),
                dict(id="edit", tool="etl", args=dict(action="write", content="def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n")),
                dict(id="test", tool="etl", args=dict(action="test")),
            ]
            decision = {"tool_calls": [calls[len(results)]]} if len(results) < 3 else {"answer": {"done": True}}
        elif context.get("family") == "database-analysis":
            if not results:
                decision = {"tool_calls": [dict(id="schema", tool="database", args=dict(action="schema"))]}
            elif len(results) == 1:
                query = ("SELECT c.segment, COUNT(*) AS order_count, SUM(o.amount_cents) AS revenue_cents "
                         "FROM orders o JOIN customers c ON c.customer_id=o.customer_id "
                         "WHERE o.status='paid' GROUP BY c.segment ORDER BY c.segment")
                decision = {"tool_calls": [dict(id="query", tool="database", args=dict(action="query", sql=query))]}
            else:
                by_segment = {row[0]: {"order_count": row[1], "revenue_cents": row[2]} for row in results[-1]["result"]["rows"]}
                decision = {"answer": {"by_segment": by_segment, "total_cents": sum(item["revenue_cents"] for item in by_segment.values())}}
        elif context.get("family") == "numerical-analysis":
            if not results:
                decision = {"tool_calls": [dict(id="read", tool="numerical", args=dict(action="read"))]}
            else:
                rows = results[-1]["result"]["rows"]
                mean_x = sum(row[0] for row in rows) / len(rows)
                mean_y = sum(row[1] for row in rows) / len(rows)
                slope = sum((x - mean_x) * (y - mean_y) for x, y in rows) / sum((x - mean_x) ** 2 for x, _ in rows)
                intercept = mean_y - slope * mean_x
                rmse = (sum((y - (slope * x + intercept)) ** 2 for x, y in rows) / len(rows)) ** 0.5
                decision = {"answer": {"slope": round(slope, 6), "intercept": round(intercept, 6), "rmse": round(rmse, 6)}}
        elif not results:
            decision = {"tool_calls": [dict(id="pipeline", tool="pipeline", args={})]}
        else:
            value = results[-1]["result"]
            decision = {"answer": value}
        if self.case == "wrong_answer" and "answer" in decision:
            decision = {"answer": {"wrong": True}}
        if chat:
            from studies.energy_diagnosis.agent_protocol import to_native_text
            text = to_native_text(decision)
            if self.case == "unclosed_submit" and "answer" in decision:
                text = text[: -len("\n</tool_call>")]     # observed Qwen3 slip: submit without the closing tag
            return dict(text=text, finish_reason="stop",
                        tokens=dict(prompt=len(json.dumps(arg["messages"])), completion=10), hook_ns=0)
        return dict(
            text=json.dumps(decision),
            tokens=dict(prompt=len(arg["prompt"]), completion=10),
            hook_ns=0,
        )
