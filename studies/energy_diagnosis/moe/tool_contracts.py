"""Model-visible argument contracts shared with pre-dispatch validation."""


def action_contract(actions):
    """Actions map to the one optional payload required for that action."""
    variants = []
    for action, field in actions.items():
        properties = {"action": {"const": action}}
        required = ["action"]
        if field:
            properties[field] = {"type": "string", "minLength": 1}
            required.append(field)
        variants.append(
            dict(
                type="object",
                properties=properties,
                required=required,
                additionalProperties=False,
            )
        )
    return {"oneOf": variants}


def validate_action(args, actions):
    if (
        not isinstance(args, dict)
        or not isinstance(args.get("action"), str)
        or args["action"] not in actions
    ):
        raise ValueError("a declared action is required")
    field = actions[args["action"]]
    if set(args) != ({"action", field} if field else {"action"}):
        raise ValueError("arguments do not match the selected action")
    if field and (
        not isinstance(args[field], str)
        or not args[field].strip()
        or len(args[field].encode()) > 32768
    ):
        raise ValueError("action payload must be nonempty text up to 32768 bytes")


SQL_ACTIONS = {"schema": None, "query": "sql"}
ETL_ACTIONS = {"read": None, "write": "content", "test": None}
REGRESSION_ACTIONS = {"inspect": None, "fit": None}


def sql_contract(engine):
    return dict(
        description=f"Read-only {engine} database. The action argument is mandatory on every call. "
        'First call action="schema" with no sql argument; the result gives table and column names/types. '
        'Use those exact names, not guessed columns. Then call action="query" with sql containing one SELECT statement. '
        "Queries return columns, rows and truncated. Aggregate in SQL; at most 128 rows and 65536 output bytes are returned. "
        "The query time limit is 10 seconds and SQL text limit is 32768 bytes. No database writes, attachments, PRAGMA, external files or extensions. "
        "Use standard joins, subqueries, CASE and supported aggregate/scalar functions; ranking functions such as ROW_NUMBER are not exposed. "
        "Perform schema and query in separate decisions so the query can use the observed schema.",
        args={
            "action": "required: schema or query",
            "sql": "required only for query; omit for schema",
        },
        parameters=action_contract(SQL_ACTIONS),
        example_call={"id": "schema_1", "tool": "sql", "args": {"action": "schema"}},
    )
