"""Optional real CPU cache qualification; requires Torch 2.10 / Transformers 5.3.

This uses a random, reduced Qwen MoE, not production weights or native offload.
It is intentionally separate from the lightweight fixture CI environment.
"""
import json
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from studies.energy_diagnosis.moe.native_backend import NativeDevice
from studies.energy_diagnosis.moe.prefix import GenerationWork, RequestPrefixCache


@pytest.mark.parametrize("attention", ["eager", "sdpa"])
def test_actual_qwen_cache_reuse_matches_fresh_generation(attention):
    torch.set_num_threads(1)
    torch.manual_seed(20260912)
    config = transformers.Qwen3MoeConfig(
        vocab_size=128, hidden_size=32, intermediate_size=64,
        moe_intermediate_size=16, num_hidden_layers=2, num_attention_heads=4,
        num_key_value_heads=2, head_dim=8, num_experts=4, num_experts_per_tok=2,
        max_position_embeddings=256, eos_token_id=None, bos_token_id=1, pad_token_id=0,
    )
    config._attn_implementation = attention
    model = transformers.Qwen3MoeForCausalLM(config).eval()
    device = NativeDevice.__new__(NativeDevice)
    device.model = model
    device.request_cache_mode = "exact_prefix"
    device.prefix_cache, device.request_work = RequestPrefixCache(), GenerationWork()
    device.hook_ns, device.max_context = 0, 256
    # Redirect only device placement/synchronization; execute the real bridge,
    # HF model, DynamicCache crop, attention, expert routing and generation.
    class CPUInput:
        def __init__(self, values):
            self.values = values

        def to(self, name):
            assert name == "cuda:0"
            return torch.tensor([self.values])

    device.tokenizer = SimpleNamespace(
        eos_token_id=0,
        apply_chat_template=lambda messages, **kw: messages[0]["content"],
        encode=lambda text, **kw: CPUInput(json.loads(text)),
        decode=lambda ids, **kw: json.dumps(ids.tolist()),
    )
    device.torch = SimpleNamespace(no_grad=torch.no_grad, ones_like=torch.ones_like,
                                   cuda=SimpleNamespace(synchronize=lambda: None))
    logits = []
    active = False

    def before(module, args, kwargs):
        if active:
            device.request_work.observe(int(kwargs["input_ids"].shape[1]))

    def after(module, args, output):
        logits.append(output.logits[:, -1, :].detach().clone())

    pre_hook = model.register_forward_pre_hook(before, with_kwargs=True)
    post_hook = model.register_forward_hook(after)
    prompts = [[1, 2, 3, 4], [1, 2, 3, 5], [1, 2, 3, 5], [1, 2],
               [9, 7, 3], [9, 7, 3, 6], [9, 7, 3, 6, 7]]
    reuse = []
    try:
        for prompt in prompts:
            ids = torch.tensor([prompt])
            logits.clear()
            with torch.no_grad():
                reference = model.generate(ids, attention_mask=torch.ones_like(ids),
                    do_sample=False, max_new_tokens=4, pad_token_id=0)
            reference_logits = list(logits)
            logits.clear()
            active = True
            result = device.generate(dict(prompt=json.dumps(prompt), max_tokens=4))
            active = False
            assert json.loads(result["text"]) == reference[0, len(prompt):].tolist()
            assert len(logits) == len(reference_logits) == 4
            for expected, actual in zip(reference_logits, logits):
                torch.testing.assert_close(actual, expected, atol=1e-6, rtol=1e-5)
            assert result["prefix_cache"]["new_prefill_tokens"] == len(prompt) - result["prefix_cache"]["reused_prefix_tokens"]
            assert result["prefix_cache"]["decode_forward_tokens"] == 3
            reuse.append(result["prefix_cache"]["reused_prefix_tokens"])
        assert reuse == [0, 3, 3, 1, 0, 3, 4]
    finally:
        pre_hook.remove()
        post_hook.remove()
