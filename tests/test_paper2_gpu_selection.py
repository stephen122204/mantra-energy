"""Device selection must preserve UUID identity and reject absent hardware."""
import sys
from types import SimpleNamespace

import pytest

from studies.paper2.cohort.server import gpu_device_index


@pytest.mark.parametrize("target", ["GPU-second", b"GPU-second"])
def test_resolves_uuid_and_closes_nvml(monkeypatch, target):
    calls = []
    monkeypatch.setitem(sys.modules, "pynvml", SimpleNamespace(
        nvmlInit=lambda: calls.append("init"),
        nvmlShutdown=lambda: calls.append("shutdown"),
        nvmlDeviceGetCount=lambda: 2,
        nvmlDeviceGetHandleByIndex=lambda i: i,
        nvmlDeviceGetUUID=lambda i: ["GPU-first", target][i],
    ))
    assert gpu_device_index("GPU-second") == 1
    assert calls == ["init", "shutdown"]


def test_missing_uuid_never_falls_back_to_gpu_zero(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pynvml", SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlShutdown=lambda: calls.append("shutdown"),
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda i: i,
        nvmlDeviceGetUUID=lambda i: "GPU-other",
    ))
    with pytest.raises(ValueError, match="refusing to select another device"):
        gpu_device_index("GPU-requested")
    assert calls == ["shutdown"]
