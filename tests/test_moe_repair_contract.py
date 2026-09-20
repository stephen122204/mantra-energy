"""Public repair constraints and independent arithmetic outcomes must agree."""
import pytest

from studies.energy_diagnosis.moe.workloads import (
    BUGGY, REPAIR_LANGUAGE, VERSION, HiddenRepositoryCheck, create_tasks,
)


def checked(tmp_path, source):
    path = tmp_path / "pricing.py"
    path.write_text(source)
    return HiddenRepositoryCheck(str(path)).execute()


def test_correct_integer_repair_and_versioned_public_contract(tmp_path):
    tasks = create_tasks(tmp_path / "assets")
    repair = next(t for t in tasks if t.family == "repository-repair")
    assert repair.task_id == "pricing-repair-v2" and VERSION == "moe-tools-v3"
    assert REPAIR_LANGUAGE in repair.prompt
    assert repair.lineage == "synthetic-pricing-v1"  # Same underlying task, not a new held-out lineage.
    assert checked(tmp_path, "# Allowed comment\ndef net_cents(price, count, discount):\n    return (price * count * (100 - discount) + 50) // 100\n") == {"passed": True, "checks": 90}
    assert not checked(tmp_path, BUGGY)["passed"]


@pytest.mark.parametrize("source", [
    "def net_cents(price, count, discount):\n    return round(price * count * (100 - discount) / 100)\n",
    "def net_cents(price, count, discount):\n    x = price * count\n    return x\n",
    "def net_cents(price, count, discount):\n    return 1.0\n",
    "def net_cents(price, count, discount):\n    return True\n",
    "def net_cents(price, count, discount=0):\n    return price\n",
    "def net_cents(price, count, discount) -> int:\n    return price\n",
    "def net_cents(price, count, discount):\n    return price\n    return count\n",
    "def net_cents(price, count, discount, other):\n    return price\n",
    "def net_cents(price, count, discount):\n    'docstring'\n    return price\n",
])
def test_disallowed_language_has_an_explicit_contract_failure(tmp_path, source):
    result = checked(tmp_path, source)
    assert result == {"passed": False, "reason": "source violates the declared constrained arithmetic repair language"}
