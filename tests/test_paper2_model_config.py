import json
import sys
from types import SimpleNamespace

import pytest

from studies.paper2.cohort.server import validate_model_rope


@pytest.mark.parametrize('loaded', [SimpleNamespace(), SimpleNamespace(rope_theta=10000)])
def test_rejects_relocated_or_changed_rope_before_server_start(tmp_path, monkeypatch, loaded):
    (tmp_path / 'config.json').write_text(json.dumps(dict(rope_theta=1e9)))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        AutoConfig=SimpleNamespace(from_pretrained=lambda _: loaded)))
    with pytest.raises(ValueError, match='pinned Transformers'):
        validate_model_rope(str(tmp_path))


def test_accepts_checkpoint_rope_value(tmp_path, monkeypatch):
    (tmp_path / 'config.json').write_text(json.dumps(dict(rope_theta=1e9)))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        AutoConfig=SimpleNamespace(from_pretrained=lambda _: SimpleNamespace(rope_theta=1e9))))
    validate_model_rope(str(tmp_path))
