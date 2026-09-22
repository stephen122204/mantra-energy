"""Exercise patched routing against the pinned framework, with no GPU model."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest
import torch
from transformers import Qwen3MoeConfig
from transformers.models.qwen3_moe.modeling_qwen3_moe import Qwen3MoeTopKRouter

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('tokens', [1, 17])
@pytest.mark.parametrize('normalize', [False, True])
def test_patched_router_preserves_framework_probabilities(tmp_path, monkeypatch, tokens, normalize):
    destination = tmp_path / 'moe_infinity/models/qwen.py'
    destination.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'tests/fixtures/moe_reference/qwen.py', destination)
    subprocess.run(['git', 'apply', '--include=moe_infinity/models/qwen.py',
                    str(ROOT/'studies/energy_diagnosis/moe/patches/moe-infinity-transfer-lifecycle.patch')],
                   cwd=tmp_path, check=True)
    spec=importlib.util.spec_from_file_location('patched_qwen', destination)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    torch.manual_seed(31)
    config=Qwen3MoeConfig(hidden_size=32,moe_intermediate_size=16,num_experts=8,
                         num_experts_per_tok=4,norm_topk_prob=normalize)
    model=module.Qwen3MoEBlock(config).to(torch.bfloat16)
    reference=Qwen3MoeTopKRouter(config).to(torch.bfloat16)
    reference.weight.data.copy_(model.gate.weight)
    hidden=torch.randn(1,tokens,32,dtype=torch.bfloat16)
    class Executor:
        def dispatch_local(self, layer, h, mask, weights, **kwargs):
            self.mask,self.weights=mask,weights
            self.output=torch.zeros_like(h)
        def wait_dispatch_local(self): return self.output
    executor=Executor();model.expert_executor=executor
    with torch.no_grad():
        _,weights,indices=reference(hidden.reshape(-1,32))
        expected=torch.zeros(tokens,8,dtype=torch.float32).scatter_(1,indices,weights)
        monkeypatch.setenv('ALEMS_QWEN_REFERENCE_MATH','1')
        model(hidden)
        assert executor.weights.dtype==torch.float32
        assert torch.equal(executor.weights,expected)
        assert torch.equal(executor.mask,expected.ne(0))
        monkeypatch.delenv('ALEMS_QWEN_REFERENCE_MATH')
        model(hidden)
        assert executor.weights.dtype==torch.bfloat16
        assert torch.equal(executor.weights,expected.to(torch.bfloat16))
