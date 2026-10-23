"""Substantive local task tools with per-goal workspaces and independent checks."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import csv
import json
import math
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from fractions import Fraction

from studies.energy_diagnosis.workloads.pilot_tasks import (
    PilotTask,
    _hash as asset_hash,
    asset_files,
    copy_workspace,
    workspace_write,
)
from studies.energy_diagnosis.workloads.bounded_executor import (
    BoundedToolExecutor,
    ToolCall,
)

VERSION = "moe-tools-v4"
BUGGY = "def net_cents(price, count, discount):\n    return price * count * (100 - discount) // 100\n"
REPAIR_LANGUAGE = (
    "This is a constrained arithmetic repair: pricing.py must contain exactly one "
    "function def net_cents(price, count, discount), with exactly one return statement. "
    "Its expression may use only these three parameters, integer literals, parentheses, "
    "+, -, *, //, %, and unary + or -. No imports, function calls, assignments, "
    "annotations, defaults, decorators, extra parameters, docstrings, or other statements "
    "are allowed. Return a Python int. Comments are allowed."
)
ETL_BUGGY = "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] + row['tax_cents']} for row in rows]\n"
ETL_LANGUAGE = (
    "This is a bounded ETL repair: etl.py must contain exactly one function "
    "def transform_rows(rows) with one return statement. It must return a list "
    "of dictionaries with region and net_cents, where net_cents is gross_cents "
    "minus tax_cents, and it must preserve input row order. No imports, calls, "
    "assignments, annotations, defaults, decorators, or extra statements are allowed."
)


def _write_database(path):
    db = sqlite3.connect(path)
    try:
        db.executescript(
            "CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, segment TEXT);"
            "CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, "
            "amount_cents INTEGER, status TEXT);"
        )
        db.executemany("INSERT INTO customers VALUES (?, ?)", [(1, "enterprise"), (2, "small"), (3, "enterprise"), (4, "startup")])
        db.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            (101, 1, 1200, "paid"), (102, 1, 800, "refunded"), (103, 2, 500, "paid"),
            (104, 2, 700, "paid"), (105, 3, 2500, "paid"), (106, 3, 100, "cancelled"),
            (107, 4, 450, "paid"), (108, 4, 550, "refunded"), (109, 1, 300, "paid"),
        ])
        db.commit()
    finally:
        db.close()


def _sqlite_dump(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return list(db.iterdump())
    finally:
        db.close()


def _same_asset(existing, generated):
    """Byte-identical inputs; SQLite files compare by logical dump, since the
    same schema/rows can serialize differently across library versions."""
    existing_files = {p.relative_to(existing).as_posix(): p for p in asset_files(existing)}
    generated_files = {p.relative_to(generated).as_posix(): p for p in asset_files(generated)}
    if existing_files.keys() != generated_files.keys():
        return False
    for name, new in generated_files.items():
        old = existing_files[name]
        if name.endswith(".sqlite"):
            if _sqlite_dump(old) != _sqlite_dump(new):
                return False
        elif old.read_bytes() != new.read_bytes():
            return False
    return True


def _materialize(root, name, writer):
    """Create root/name once. A later call reuses an identical existing asset and
    refuses a different one; it never rewrites files under an existing directory."""
    target = root / name
    staging = Path(tempfile.mkdtemp(prefix=f".{name}.staging-", dir=root))
    try:
        writer(staging)
        if not target.exists():
            staging.rename(target)
            return target
        if target.is_dir() and _same_asset(target, staging):
            return target
        raise RuntimeError(
            f"existing task asset {target} differs from the {VERSION} definition; "
            "inputs are frozen per campaign directory, use a new output directory"
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write_orders(data):
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


def _write_repository(repo):
    (repo / "pricing.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (repo / "visible_checks.py").write_text(
        "from pricing import net_cents\nassert net_cents(101, 1, 50) == 51\nassert net_cents(250, 2, 10) == 450\nprint('2 visible checks passed')\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_etl(etl):
    (etl / "etl.py").write_text(ETL_BUGGY, encoding="utf-8", newline="\n")
    (etl / "visible_checks.py").write_text(
        "from etl import transform_rows\nassert transform_rows([{'region':'west','gross_cents':105,'tax_cents':5}]) == [{'region':'west','net_cents':100}]\nprint('1 visible ETL check passed')\n",
        encoding="utf-8", newline="\n",
    )


def _write_numerical(numeric):
    with (numeric / "observations.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["x", "y"])
        writer.writerows((x, 3 * x + 2 + (-1 if x % 3 == 0 else 1 if x % 3 == 1 else 0)) for x in range(1, 10))


def create_tasks(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data = _materialize(root, "orders", _write_orders)
    repo = _materialize(root, "repository", _write_repository)
    database = _materialize(root, "database", lambda d: _write_database(d / "orders.sqlite"))
    etl = _materialize(root, "etl-repository", _write_etl)
    numeric = _materialize(root, "numerical", _write_numerical)
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
            "pricing-repair-v2",
            "repository-repair",
            "synthetic-pricing-v1",
            repo,
            {},
            asset_hash(repo),
            (),
            "Repair net_cents(price, count, discount) to return integer cents rounded half up after applying an integer percentage discount. Inputs are nonnegative integer price/count and discount 0..100. "
            + REPAIR_LANGUAGE
            + " Read the source, edit pricing.py, and execute visible tests. Return {done:true} when finished.",
        ),
        PilotTask(
            "customer-orders-db-v1", "database-analysis", "synthetic-customer-orders-v1", database,
            {}, asset_hash(database), (),
            "Using the read-only database tool, calculate paid order count and paid revenue in cents by customer segment. Exclude refunded and cancelled orders. Return {by_segment:{segment:{order_count:int,revenue_cents:int}},total_cents:int}.",
        ),
        PilotTask(
            "normalize-etl-v1", "etl-repair", "synthetic-etl-v1", etl,
            {}, asset_hash(etl), (),
            "Repair etl.py so transform_rows(rows) emits one ordered record per input with region and gross_cents-tax_cents. Return {done:true} after running visible tests. " + ETL_LANGUAGE,
        ),
        PilotTask(
            "linear-fit-v1", "numerical-analysis", "synthetic-linear-fit-v1", numeric,
            {}, asset_hash(numeric), (),
            "Use the numerical tool to inspect observations.csv and return the ordinary least-squares line y=slope*x+intercept and RMSE. Return {slope:number,intercept:number,rmse:number} with finite numbers rounded to 6 decimal places.",
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
class DatabaseTool:
    database: str

    def execute(self, action, sql=None, workers=1):
        if workers != 1 or action not in {"schema", "query"}:
            raise ValueError("use one-worker schema or query")
        if action == "schema" and sql is not None:
            raise ValueError("schema takes no SQL")
        if action == "query" and (
            not isinstance(sql, str) or not sql.lstrip().lower().startswith("select")
            or ";" in sql or len(sql.encode()) > 32768
        ):
            raise ValueError("query must be one bounded SELECT")
        db = sqlite3.connect(Path(self.database).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            if action == "schema":
                value = {name: [dict(name=row[1], type=row[2]) for row in db.execute(f"PRAGMA table_info({name})")] for name in ("customers", "orders")}
                return {"tables": value}
            result = db.execute(sql)
            rows = result.fetchmany(128)
            return {"columns": [column[0] for column in result.description], "rows": [list(row) for row in rows], "truncated": len(rows) == 128}
        finally:
            db.close()


@dataclass
class NumericalTool:
    root: str

    def execute(self, action="read", workers=1):
        if workers != 1 or action != "read":
            raise ValueError("use one-worker read")
        with (Path(self.root) / "observations.csv").open(newline="", encoding="utf-8") as handle:
            return {"rows": [[int(row["x"]), int(row["y"])] for row in csv.DictReader(handle)]}


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
            workspace_write(path / "pricing.py", content, encoding="utf-8", newline="\n")
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
class ETLRepositoryTool:
    root: str

    def execute(self, action, content=None, workers=1):
        path = Path(self.root)
        if action == "read" and content is None:
            return {name: (path / name).read_text() for name in ("etl.py", "visible_checks.py")}
        if action == "write" and isinstance(content, str) and len(content.encode()) <= 32768:
            workspace_write(path / "etl.py", content, encoding="utf-8", newline="\n")
            return {"written": "etl.py"}
        if action == "test" and content is None:
            result = subprocess.run(
                [sys.executable, "-c", "import py_compile; py_compile.compile('etl.py', doraise=True); exec(open('visible_checks.py').read())"],
                cwd=path, capture_output=True, text=True, timeout=15,
            )
            return dict(exit_code=result.returncode, stdout=result.stdout[-8192:], stderr=result.stderr[-8192:])
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
            try:
                # type_comments=True makes the type_comment checks below effective.
                tree = ast.parse(source, type_comments=True)
            except SyntaxError:
                return {"passed": False, "reason": "invalid Python source"}
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
                ast.USub,
                ast.UAdd,
            )
            if (
                len(tree.body) != 1
                or not isinstance(tree.body[0], ast.FunctionDef)
                or tree.body[0].name != "net_cents"
                or tree.body[0].decorator_list
                or tree.body[0].returns is not None
                or tree.body[0].type_comment is not None
                or getattr(tree.body[0], "type_params", [])
                or len(tree.body[0].body) != 1
                or not isinstance(tree.body[0].body[0], ast.Return)
                or [a.arg for a in tree.body[0].args.args] != ["price", "count", "discount"]
                or tree.body[0].args.posonlyargs
                or tree.body[0].args.kwonlyargs
                or tree.body[0].args.vararg is not None
                or tree.body[0].args.kwarg is not None
                or tree.body[0].args.defaults
                or tree.body[0].args.kw_defaults
                or any(not isinstance(n, allowed) for n in ast.walk(tree))
                or any(isinstance(n, ast.arg) and (n.annotation is not None or n.type_comment is not None) for n in ast.walk(tree))
                or any(isinstance(n, ast.Constant) and type(n.value) is not int for n in ast.walk(tree))
                or any(
                    isinstance(n, ast.Name)
                    and n.id not in {"price", "count", "discount"}
                    for n in ast.walk(tree)
                )
            ):
                return {
                    "passed": False,
                    "reason": "source violates the declared constrained arithmetic repair language",
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
                + "\nactual=[net_cents(*c) for c in cases]\nprint(json.dumps({'passed': all(type(v) is int for v in actual) and actual == expected, 'checks': len(cases)}))\n"
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
class HiddenETLCheck:
    source: str

    def execute(self, workers=1):
        source = Path(self.source).read_text(encoding="utf-8")
        import ast

        try:
            # type_comments=True makes "# type:" annotations visible to the checks below.
            tree = ast.parse(source, type_comments=True)
        except SyntaxError:
            return {"passed": False, "reason": "invalid Python source"}
        allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.ListComp,
                   ast.comprehension, ast.Dict, ast.Subscript, ast.Name, ast.Load, ast.Store,
                   ast.Constant, ast.BinOp, ast.Sub, ast.Add, ast.Mult, ast.USub)
        function = tree.body[0] if len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef) else None
        if (
            function is None or function.name != "transform_rows" or function.decorator_list
            or function.returns is not None or function.type_comment is not None
            or getattr(function, "type_params", []) or len(function.body) != 1
            or not isinstance(function.body[0], ast.Return)
            or [argument.arg for argument in function.args.args] != ["rows"]
            or function.args.posonlyargs or function.args.kwonlyargs
            or function.args.vararg is not None or function.args.kwarg is not None
            or function.args.defaults or function.args.kw_defaults
            or any(not isinstance(node, allowed) for node in ast.walk(tree))
            # Declared restrictions: no annotations of any form, only int/str
            # literals, and no comprehension filters (every input row is emitted).
            or any(isinstance(node, ast.arg) and (node.annotation is not None or node.type_comment is not None) for node in ast.walk(tree))
            or any(isinstance(node, ast.Constant) and type(node.value) not in {int, str} for node in ast.walk(tree))
            or any(isinstance(node, ast.comprehension) and (node.ifs or node.is_async) for node in ast.walk(tree))
        ):
            return {"passed": False, "reason": "source violates the bounded ETL language"}
        cases = [
            [{"region": "west", "gross_cents": 105, "tax_cents": 5}, {"region": "east", "gross_cents": 999, "tax_cents": 99}],
            [{"region": "north", "gross_cents": 0, "tax_cents": 0}],
            [],
        ]
        expected = [[{"region": row["region"], "net_cents": row["gross_cents"] - row["tax_cents"]} for row in rows] for rows in cases]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "etl.py"
            path.write_text(source, encoding="utf-8")
            script = "from etl import transform_rows\nimport json\ncases=" + repr(cases) + "\nexpected=" + repr(expected) + "\nactual=[transform_rows(case) for case in cases]\nprint(json.dumps({'passed': actual == expected, 'checks': len(cases)}))\n"
            result = subprocess.run([sys.executable, "-c", script], cwd=path.parent, capture_output=True, text=True, timeout=15)
        if result.returncode:
            return {"passed": False, "reason": "hidden ETL execution failed"}
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            return {"passed": False, "reason": "invalid hidden ETL output"}
        return {"passed": payload == {"passed": True, "checks": len(cases)}, "checks": len(cases)}


@dataclass
class InjectedFailureTool:
    timeout: bool = False

    def execute(self, workers=1):
        if self.timeout:
            import time

            time.sleep(20)
        raise RuntimeError("injected tool failure")


def _repair_tool_contract(name, source_file, argument_help):
    return {
        name: {
            "description": (
                f"Read the workspace, replace {source_file}, or run its visible checks. "
                "Only action and (for write) content are accepted. Invoke dependent "
                "read/write/test steps in order using separate decisions or explicit "
                "depends_on call IDs."
            ),
            "args": {"action": "read|write|test", "content": argument_help},
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read", "write", "test"]},
                    "content": {"type": "string", "description": argument_help},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            "example_call": {"id": f"{name}_read_1", "tool": name, "args": {"action": "read"}},
        }
    }


# Prompt-visible tool contracts. Every entry states the exact accepted arguments,
# a JSON-schema form of them, one example call and any ordering requirement; the
# runtime's tool() method enforces the same argument sets.
TOOL_CONTRACTS = {
    "data-pipeline": {
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
    },
    "repository-repair": _repair_tool_contract(
        "repo", "pricing.py", "only for write; complete pricing.py source"
    ),
    "etl-repair": _repair_tool_contract(
        "etl", "etl.py", "only for write; complete etl.py source"
    ),
    "database-analysis": {
        "database": {
            "description": "Read-only SQLite database with tables customers(customer_id, segment) and orders(order_id, customer_id, amount_cents, status). action=schema takes no other argument and returns column names/types. action=query requires sql: exactly one SELECT statement without a semicolon; at most 128 rows are returned and truncated=true marks a cut-off result, so aggregate in SQL. Writes, PRAGMA and multiple statements are rejected. Run schema before query in separate decisions or with depends_on.",
            "args": {"action": "schema|query", "sql": "only for query; one SELECT statement"},
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["schema", "query"]},
                    "sql": {"type": "string", "description": "only for query; one SELECT statement"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            "example_call": {"id": "database_schema_1", "tool": "database", "args": {"action": "schema"}},
        }
    },
    "numerical-analysis": {
        "numerical": {
            "description": "Reads the immutable observations.csv and returns rows as [x, y] integer pairs in file order. The only accepted argument is action=read; it cannot filter, sort or compute. Compute the least-squares fit and RMSE from the returned rows.",
            "args": {"action": "read"},
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["read"]}},
                "required": ["action"],
                "additionalProperties": False,
            },
            "example_call": {"id": "numerical_read_1", "tool": "numerical", "args": {"action": "read"}},
        }
    },
}


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
        copy_workspace(task.asset_path, self.workspace)
        if asset_hash(self.workspace) != task.asset_sha256:
            raise RuntimeError("workspace reset does not reproduce task input")

    def context(self, task):
        tools = TOOL_CONTRACTS[task.family]
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
        if task.family == "database-analysis" and call.get("tool") == "database":
            args = call.get("args", {})
            if isinstance(args, dict) and set(args) <= {"action", "sql"}:
                return DatabaseTool(str(self.workspace / "orders.sqlite"))
        if task.family == "numerical-analysis" and call.get("tool") == "numerical":
            args = call.get("args", {})
            if isinstance(args, dict) and args == {"action": "read"}:
                return NumericalTool(str(self.workspace))
        if task.family == "etl-repair" and call.get("tool") == "etl":
            args = call.get("args", {})
            if isinstance(args, dict) and set(args) <= {"action", "content"} and args.get("action") in {"read", "write", "test"}:
                return ETLRepositoryTool(str(self.workspace))
        raise ValueError("tool request is outside declared task schema")

    def verify(self, task, answer):
        if task.family == "data-pipeline":
            # Independent SQL implementation of the join/filter/grouping reference.
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
        if task.family == "database-analysis":
            if not isinstance(answer, dict) or set(answer) != {"by_segment", "total_cents"}:
                return {"passed": False, "reason": "invalid database answer shape"}
            if type(answer["total_cents"]) is not int or not isinstance(answer["by_segment"], dict):
                return {"passed": False, "reason": "invalid database answer types"}
            if any(
                not isinstance(value, dict)
                or set(value) != {"order_count", "revenue_cents"}
                or type(value["order_count"]) is not int
                or type(value["revenue_cents"]) is not int
                for value in answer["by_segment"].values()
            ):
                return {"passed": False, "reason": "invalid database segment types"}
            expected = {}
            # Read-only URI: the reference is recomputed from the immutable asset.
            db = sqlite3.connect((task.asset_path / "orders.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
            try:
                rows = db.execute("SELECT c.segment, o.amount_cents FROM orders o JOIN customers c ON c.customer_id=o.customer_id WHERE o.status='paid'")
                for segment, amount in rows:
                    bucket = expected.setdefault(segment, {"order_count": 0, "revenue_cents": 0})
                    bucket["order_count"] += 1
                    bucket["revenue_cents"] += amount
            finally:
                db.close()
            expected_answer = {"by_segment": expected, "total_cents": sum(item["revenue_cents"] for item in expected.values())}
            return {"passed": answer == expected_answer, "reason": "independent Python reference over immutable database"}
        if task.family == "numerical-analysis":
            if not isinstance(answer, dict) or set(answer) != {"slope", "intercept", "rmse"} or any(type(answer.get(key)) not in {int, float} or not math.isfinite(answer[key]) for key in ("slope", "intercept", "rmse")):
                return {"passed": False, "reason": "invalid numerical answer shape"}
            with (task.asset_path / "observations.csv").open(newline="", encoding="utf-8") as handle:
                points = [(Fraction(int(row["x"])), Fraction(int(row["y"]))) for row in csv.DictReader(handle)]
            mean_x = sum(x for x, _ in points) / len(points)
            mean_y = sum(y for _, y in points) / len(points)
            slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum((x - mean_x) ** 2 for x, _ in points)
            intercept = mean_y - slope * mean_x
            rmse = math.sqrt(float(sum((y - (slope * x + intercept)) ** 2 for x, y in points) / len(points)))
            expected = {"slope": round(float(slope), 6), "intercept": round(float(intercept), 6), "rmse": round(rmse, 6)}
            return {"passed": answer == expected, "reason": "independent exact-fraction regression reference"}
        if task.family == "etl-repair":
            if answer != {"done": True}:
                return {"passed": False, "reason": "missing completion answer"}
            outcome = BoundedToolExecutor({"hidden": HiddenETLCheck(str(self.workspace / "etl.py"))}, timeout_seconds=20).execute([ToolCall("verify", "hidden", {})])["verify"]
            return {"passed": outcome.status == "completed" and outcome.result.get("passed") is True, "reason": "independent hidden ETL checks", "diagnostics": outcome.result}
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
