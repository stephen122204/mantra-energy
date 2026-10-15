"""Synthetic capability checks; no CUDA runtime or workload is invoked."""
import pytest
from studies.energy_diagnosis.diagnostics.qualify_counters import gpu_dtype


@pytest.mark.parametrize("capability,expected", [((7, 0), "float16"), ((7, 5), "float16"), ((8, 0), "bfloat16"), ((9, 0), "bfloat16")])
def test_native_load_dtype(capability, expected):
    assert gpu_dtype(capability) == expected


def test_reject_unsupported_bf16_and_preserve_explicit_supported_dtype():
    with pytest.raises(ValueError, match="8.0"):
        gpu_dtype((7, 0), "bfloat16")
    assert gpu_dtype((7, 0), "float32") == "float32"
    assert gpu_dtype((8, 0), "float16") == "float16"


def test_qualification_retains_initialization_failure_and_closes_reader(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from studies.energy_diagnosis.diagnostics import qualify_counters as q
    from studies.energy_diagnosis.runtime import node_measurement as node

    closed = []
    class FailedReader:
        def __init__(self, index):
            assert index == 3
        def device_identity(self):
            return {"status": "unavailable"}
        def close(self):
            closed.append(True)

    monkeypatch.setattr(node, "NodeCounterReader", FailedReader)
    monkeypatch.setattr(q.subprocess, "check_output", lambda *a, **k: "fixture-revision")
    args = SimpleNamespace(output=str(tmp_path/"attempt"), allocation="fixture", isolation_note="simulated",
                           gpu_index=3, gpu_dtype="auto", seconds=1, backend_python="unused")
    with pytest.raises(RuntimeError, match="identity unavailable"):
        q.main(args)
    failure = json.loads((tmp_path/"attempt/0-idle-failure.json").read_text())
    assert failure["source_revision"] == "fixture-revision"
    assert failure["measurement_complete"] is False
    assert "identity unavailable" in failure["error"]
    assert closed == [True]
    assert (tmp_path/"attempt/configuration.json").is_file()
    with pytest.raises(FileExistsError):
        q.main(args)
