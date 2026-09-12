"""Substantive local task tools with per-goal workspaces and independent checks."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from studies.energy_diagnosis.workloads.pilot_tasks import (
    PilotTask,
    _hash as asset_hash,
)
from studies.energy_diagnosis.workloads.bounded_executor import (
    BoundedToolExecutor,
    ToolCall,
)

VERSION = "moe-tools-v2"
BUGGY = "def net_cents(price, count, discount):\n    return price * count * (100 - discount) // 100\n"


def create_tasks(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data = root / "orders"
    data.mkdir(exist_ok=True)
    with (data / "products.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["product", "price_cents"])
        w.writerows((f"p{i}", 101 + 7 * i) for i in range(29))
    with (data / "orders.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["order", "product", "region", "quantity", "returned"])
        w.writerows(
            (i, f"p{i%29}", f"r{i%7}", 1 + i % 11, int(i % 13 == 0))
            for i in range(20000)
        )
    repo = root / "repository"
    repo.mkdir(exist_ok=True)
    (repo / "pricing.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (repo / "visible_checks.py").write_text(
        "from pricing import net_cents\nassert net_cents(101, 1, 50) == 51\nassert net_cents(250, 2, 10) == 450\nprint('2 visible checks passed')\n",
        encoding="utf-8",
        newline="\n",
    )
    return (
        PilotTask(
            "joined-orders-v1",
            "data-pipeline",
            "synthetic-orders-v1",
            data,
            {},
            asset_hash(data),
            (),
            "Join orders to product prices, exclude returned orders, and return exact revenue_cents_by_region and total_cents using the pipeline tool.",
        ),
        PilotTask(
            "pricing-repair-v1",
            "repository-repair",
            "synthetic-pricing-v1",
            repo,
            {},
            asset_hash(repo),
            (),
            "Repair net_cents(price, count, discount) to return integer cents rounded half up after applying an integer percentage discount. Inputs are nonnegative integer price/count and discount 0..100. Read the source, edit pricing.py, and execute visible tests. Return {done:true} when finished.",
        ),
    )


@dataclass
class PipelineTool:
    root: str

    def execute(self, workers=1):
        path = Path(self.root)
        with (path / "products.csv").open() as f:
            prices = {
                row["product"]: int(row["price_cents"]) for row in csv.DictReader(f)
            }
        totals = {}
        with (path / "orders.csv").open() as f:
            for row in csv.DictReader(f):
                if int(row["returned"]):
                    continue
                region = row["region"]
                totals[region] = (
                    totals.get(region, 0)
                    + int(row["quantity"]) * prices[row["product"]]
                )
        return dict(revenue_cents_by_region=totals, total_cents=sum(totals.values()))


@dataclass
class RepositoryTool:
    root: str

    def execute(self, action, content=None, workers=1):
        path = Path(self.root)
        if action == "read" and content is None:
            return {
                name: (path / name).read_text()
                for name in ("pricing.py", "visible_checks.py")
            }
        if (
            action == "write"
            and isinstance(content, str)
            and len(content.encode()) <= 32768
        ):
            (path / "pricing.py").write_text(content, encoding="utf-8", newline="\n")
            return {"written": "pricing.py"}
        if action == "test" and content is None:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import py_compile; py_compile.compile('pricing.py', doraise=True); exec(open('visible_checks.py').read())",
                ],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return dict(
                exit_code=result.returncode,
                stdout=result.stdout[-8192:],
                stderr=result.stderr[-8192:],
            )
        raise ValueError("declared actions are read, write(content), test")


@dataclass
class HiddenRepositoryCheck:
    source: str

    def execute(self, workers=1):
        # Trusted test file lives in a fresh directory, unavailable to model tool reads.
        # The outer bounded executor owns this subprocess and all of its descendants.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            import ast

            source = Path(self.source).read_text()
            tree = ast.parse(source)
            allowed = (
                ast.Module,
                ast.FunctionDef,
                ast.arguments,
                ast.arg,
                ast.Return,
                ast.BinOp,
                ast.UnaryOp,
                ast.Name,
                ast.Load,
                ast.Constant,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.FloorDiv,
                ast.Mod,
                ast.Div,
                ast.USub,
                ast.UAdd,
            )
            if (
                len(tree.body) != 1
                or not isinstance(tree.body[0], ast.FunctionDef)
                or tree.body[0].name != "net_cents"
                or tree.body[0].decorator_list
                or any(not isinstance(n, allowed) for n in ast.walk(tree))
                or any(
                    isinstance(n, ast.Name)
                    and n.id not in {"price", "count", "discount"}
                    for n in ast.walk(tree)
                )
            ):
                return {
                    "passed": False,
                    "reason": "function must be pure arithmetic without imports or calls",
                }
            (p / "pricing.py").write_text(source)
            cases = [
                (p, n, d)
                for p in (0, 1, 99, 101, 10003)
                for n in (0, 1, 7)
                for d in (0, 1, 33, 50, 99, 100)
            ]
            expected = [
                int(
                    (Decimal(a) * b * (100 - c) / 100).quantize(
                        Decimal(1), rounding="ROUND_HALF_UP"
                    )
                )
                for a, b, c in cases
            ]
            script = (
                "from pricing import net_cents\nimport json\ncases="
                + repr(cases)
                + "\nexpected="
                + repr(expected)
                + "\nactual=[net_cents(*c) for c in cases]\nprint(json.dumps({'passed': actual == expected, 'checks': len(cases)}))\n"
            )
            # Model edits cannot replace the verification command or reference data.
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=p,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode:
                return {"passed": False, "reason": "hidden test execution failed"}
            try:
                payload = json.loads(result.stdout)
            except ValueError:
                return {"passed": False, "reason": "invalid hidden test output"}
            return {
                "passed": payload == {"passed": True, "checks": len(cases)},
                "checks": len(cases),
            }


@dataclass
class InjectedFailureTool:
    timeout: bool = False

    def execute(self, workers=1):
        if self.timeout:
            import time

            time.sleep(20)
        raise RuntimeError("injected tool failure")


class WorkloadRuntime:
    def __init__(self, root, fixture_case=None):
        self.root = Path(root)
        self.fixture_case = fixture_case

    def begin(self, task, lease):
        self.workspace = self.root / "workspaces" / lease.execution_id
        if self.workspace.exists():
            raise RuntimeError(
                "goal workspace already exists; reset would be ambiguous"
            )
        shutil.copytree(task.asset_path, self.workspace)
        if asset_hash(self.workspace) != task.asset_sha256:
            raise RuntimeError("workspace reset does not reproduce task input")

    def context(self, task):
        tools = (
            {
                "pipeline": {
                    "description": "Runs the complete predefined join, returned-order filter, quantity-times-price calculation, and region aggregation. Returns revenue_cents_by_region and total_cents. It accepts no arguments; do not provide SQL or a query.",
                    "args": {},
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    "example_call": {"id": "pipeline_1", "tool": "pipeline", "args": {}},
                }
            }
            if task.family == "data-pipeline"
            else {
                "repo": {
                    "description": "Read the workspace, replace pricing.py, or run its visible checks. Only action and (for write) content are accepted. Invoke dependent read/write/test steps in order using separate decisions or explicit depends_on call IDs.",
                    "args": {
                        "action": "read|write|test",
                        "content": "only for write; complete pricing.py source",
                    }
                }
            }
        )
        return dict(
            family=task.family,
            tools=tools,
            instruction='Return only JSON: {"tool_calls":[{"id":"unique","tool":"declared name","args":{...}}]} or {"answer":{...}}. Follow the exact declared argument schema; do not add arguments. Use the declared tools to observe and change the workspace. Do not invent tool outputs.',
        )

    def tool(self, task, call):
        if self.fixture_case in {"tool_failure", "tool_timeout"}:
            return InjectedFailureTool(self.fixture_case == "tool_timeout")
        if (
            task.family == "data-pipeline"
            and call.get("tool") == "pipeline"
            and call.get("args", {}) == {}
        ):
            return PipelineTool(str(self.workspace))
        if task.family == "repository-repair" and call.get("tool") == "repo":
            args = call.get("args", {})
            if (
                isinstance(args, dict)
                and set(args) <= {"action", "content"}
                and args.get("action") in {"read", "write", "test"}
            ):
                return RepositoryTool(str(self.workspace))
        raise ValueError("tool request is outside declared task schema")

    def verify(self, task, answer):
        if task.family == "data-pipeline":
            # Independent SQL implementation of the join/filter/grouping reference.
            import sqlite3

            db = sqlite3.connect(":memory:")
            try:
                db.executescript(
                    "CREATE TABLE products(product TEXT, price INTEGER); CREATE TABLE orders(product TEXT, region TEXT, quantity INTEGER, returned INTEGER);"
                )
                with (task.asset_path / "products.csv").open() as f:
                    db.executemany(
                        "INSERT INTO products VALUES (?,?)",
                        [
                            (r["product"], int(r["price_cents"]))
                            for r in csv.DictReader(f)
                        ],
                    )
                with (task.asset_path / "orders.csv").open() as f:
                    db.executemany(
                        "INSERT INTO orders VALUES (?,?,?,?)",
                        [
                            (
                                r["product"],
                                r["region"],
                                int(r["quantity"]),
                                int(r["returned"]),
                            )
                            for r in csv.DictReader(f)
                        ],
                    )
                totals = dict(
                    db.execute(
                        "SELECT region, SUM(price*quantity) FROM orders JOIN products USING(product) WHERE returned=0 GROUP BY region"
                    )
                )
                return dict(
                    passed=answer
                    == dict(
                        revenue_cents_by_region=totals, total_cents=sum(totals.values())
                    ),
                    reason="independent SQL reference",
                )
            finally:
                db.close()
        if answer != {"done": True}:
            return dict(passed=False, reason="missing completion answer")
        outcome = BoundedToolExecutor(
            {"hidden": HiddenRepositoryCheck(str(self.workspace / "pricing.py"))},
            timeout_seconds=20,
        ).execute([ToolCall("verify", "hidden", {})])["verify"]
        return dict(
            passed=outcome.status == "completed"
            and outcome.result.get("passed") is True,
            reason="independent hidden checks",
            diagnostics=outcome.result,
        )
