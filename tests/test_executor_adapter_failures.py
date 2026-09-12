"""Regression coverage for structured adapter failures at executor boundaries."""

import importlib
import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


_EXECUTION_DIR = Path(__file__).parents[1] / "core" / "execution"
_execution_package = ModuleType("core.execution")
_execution_package.__path__ = [str(_EXECUTION_DIR)]
sys.modules.setdefault("core.execution", _execution_package)

_model_factory = ModuleType("core.execution.model_factory")
_model_factory.ModelFactory = SimpleNamespace(get_adapter=None)
sys.modules.setdefault("core.execution.model_factory", _model_factory)

_utils_package = ModuleType("core.utils")
_utils_package.__path__ = []
sys.modules.setdefault("core.utils", _utils_package)
_debug = ModuleType("core.utils.debug")
_debug.dprint = lambda *args, **kwargs: None
sys.modules.setdefault("core.utils.debug", _debug)

_tools = ModuleType("core.execution.tools.real_tools")
for _name in (
    "CalculatorTool", "DatabaseQueryTool", "FileProcessorTool", "WebSearchTool",
    "CodeExecutorTool", "APIQueryTool", "ToolResult",
):
    setattr(_tools, _name, type(_name, (), {}))
sys.modules.setdefault("core.execution.tools.real_tools", _tools)

LinearExecutor = importlib.import_module("core.execution.linear").LinearExecutor
AgenticExecutor = importlib.import_module("core.execution.agentic").AgenticExecutor
from core.execution.adapters.base import TextGenABC
from core.execution.adapters.openai_compat import OpenAICompatAdapter
from core.database.schema import CREATE_LLM_INTERACTIONS
from core.database.sqlite_adapter import SQLiteAdapter


class StubAdapter:
    require_success = OpenAICompatAdapter.require_success

    def __init__(self, result):
        self.result = result

    def call(self, prompt, temperature):
        return self.result

def adapter_result(*, failed):
    phase_metrics = {
        "total_time_ms": 12.0,
        "preprocess_ms": 1.0,
        "non_local_ms": 0.0,
        "local_compute_ms": 10.0,
        "postprocess_ms": 1.0,
        "app_throughput_kbps": 2.0,
        "cpu_percent_during_wait": 0.0,
        "streaming_enabled": 1,
    }
    if failed:
        return {
            "status": "error",
            "error": "stream interrupted",
            "content": "Error: stream interrupted",
            "partial_content": "partial",
            "tokens": {},
            "token_provenance": "unknown",
            "observed_tokens": {"prompt": 4},
            "total_time_ms": 12.0,
            "phase_metrics": phase_metrics,
            "bytes_sent": 3,
            "bytes_recv": 5,
            "tcp_retransmits": 1,
        }
    return {
        "status": "ok",
        "content": "answer",
        "tokens": {"prompt": 2, "completion": 1, "total": 3},
        "token_provenance": "provider",
        "total_time_ms": 12.0,
        "phase_metrics": phase_metrics,
        "bytes_sent": 3,
        "bytes_recv": 5,
        "tcp_retransmits": 0,
    }


def linear_executor(result):
    executor = LinearExecutor.__new__(LinearExecutor)
    executor.config = {"model_id": "fixture-model"}
    executor.provider = "ollama_local"
    executor.temperature = 0.0
    executor._adapter = StubAdapter(result)
    executor._effective_kbps_list = []
    return executor


def agentic_executor(result):
    executor = AgenticExecutor.__new__(AgenticExecutor)
    executor.config = {"model_id": "fixture-model", "is_local": True}
    executor.provider = "ollama_local"
    executor.temperature = 0.0
    executor.api_key = None
    executor._adapter = StubAdapter(result)
    executor.pending_interactions = []
    return executor


@pytest.mark.parametrize("kind", ["linear", "agentic"])
def test_structured_adapter_error_uses_failed_interaction_accounting(kind):
    raw = adapter_result(failed=True)
    if kind == "linear":
        result = linear_executor(raw).execute("hello")
        interaction = result["pending_interactions"][0]
        assert result["status"] == "failure"
        assert result["response"] == "Error: stream interrupted"
    else:
        result = agentic_executor(raw)._call_llm("hello")
        interaction = result["pending_interactions"][0]
        assert result["status"] == "error"
        assert result["content"] == "Error: stream interrupted"

    assert result["tokens"] == {}
    assert result["partial_content"] == "partial"
    assert result["observed_tokens"] == {"prompt": 4}
    assert interaction["status"] == "failure"
    assert interaction["response"].lower() == "error: stream interrupted"
    assert interaction["partial_content"] == "partial"
    assert interaction["observed_tokens"] == {"prompt": 4}
    assert interaction["prompt_tokens"] is None
    assert interaction["total_time_ms"] == 12.0
    assert interaction["local_compute_ms"] == 10.0


@pytest.mark.parametrize("kind", ["linear", "agentic"])
def test_successful_adapter_result_remains_successful(kind):
    raw = adapter_result(failed=False)
    if kind == "linear":
        result = linear_executor(raw).execute("hello")
        interaction = result["pending_interactions"][0]
        assert result["status"] == "success"
        assert result["response"] == "answer"
    else:
        result = agentic_executor(raw)._call_llm("hello")
        interaction = result["pending_interactions"][0]
        assert result["content"] == "answer"

    assert result["tokens"] == {"prompt": 2, "completion": 1, "total": 3}
    assert interaction["status"] == "success"
    assert interaction["response"] == "answer"


def test_default_adapter_contract_does_not_infer_legacy_failure_shapes():
    legacy = {
        "content": "Error: historical adapter sentinel",
        "execution": {"status": "failure"},
    }

    assert TextGenABC.require_success(None, legacy) is legacy


def test_existing_persistence_keeps_supported_failure_evidence():
    result = linear_executor(adapter_result(failed=True)).execute("hello")
    interaction = {**result["pending_interactions"][0], "run_id": 1}
    database = SQLiteAdapter({"path": ":memory:"})
    database.conn = sqlite3.connect(":memory:")
    database.conn.executescript(CREATE_LLM_INTERACTIONS)

    database.insert_llm_interaction(interaction)
    row = database.conn.execute(
        """SELECT status, error_message, response, prompt_tokens, completion_tokens, total_tokens,
                  total_time_ms, local_compute_ms, bytes_recv_approx
           FROM llm_interactions"""
    ).fetchone()

    assert row[0] == "failure"
    assert row[2] == "Error: stream interrupted"
    assert row[3:6] == (4, None, None)
    assert row[6:] == (12.0, 10.0, 5)
    assert "adapter_diagnostics=" in row[1]
    assert '"partial_content": "partial"' in row[1]
    assert '"token_provenance": "unknown"' in row[1]
    assert interaction["partial_content"] == "partial"
    assert interaction["observed_tokens"] == {"prompt": 4}
