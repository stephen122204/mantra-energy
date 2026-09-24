"""Prefix ownership, exact matching and failure invalidation without GPU."""
import pytest

from studies.energy_diagnosis.moe.prefix import (
    GenerationWork, RequestPrefixCache, validate_prefix_configuration,
)


@pytest.mark.parametrize("changed", [
    {"rope_scaling": {"rope_type": "dynamic", "factor": 2}},
    {"rope_parameters": {"rope_type": "dynamic", "factor": 2}},
    {"use_sliding_window": True},
    {"sliding_window": 128},
])
def test_reuse_rejects_unqualified_position_or_window_semantics(changed):
    config = dict(rope_scaling=None, sliding_window=None, use_sliding_window=False)
    validate_prefix_configuration(config)
    with pytest.raises(ValueError, match="prefix reuse requires"):
        validate_prefix_configuration(config | changed)


class Cache:
    def __init__(self, size):
        self.size = size

    def get_seq_length(self):
        return self.size

    def crop(self, size):
        self.size = min(self.size, size)


def primed():
    state = RequestPrefixCache()
    assert state.prepare([1, 2, 3])["new_prefill_tokens"] == 3
    state.finish([1, 2, 3, 4, 5], Cache(4))
    return state


@pytest.mark.parametrize("prompt,reused", [
    ([1, 2, 3, 6], 3), ([1, 2, 7, 8], 2), ([7, 8], 0),
    ([1, 2, 3], 2), ([1], 0), ([1, 2, 3, 4, 5, 6], 4),
])
def test_only_cached_exact_prefix_is_reused(prompt, reused):
    state = primed()
    result = state.prepare(prompt)
    assert result["reused_prefix_tokens"] == reused
    assert result["new_prefill_tokens"] == len(prompt) - reused
    assert (result["past_key_values"] is None) == (reused == 0)
    if reused:
        assert result["past_key_values"].get_seq_length() == reused


def test_no_concurrent_request_or_external_cache_mutation():
    state = primed()
    state.cache.size = 2
    with pytest.raises(RuntimeError, match="outside its owner"):
        state.prepare([1, 2, 3])
    assert state.cache is None
    state.prepare([1])
    with pytest.raises(RuntimeError, match="unfinished"):
        state.prepare([2])


@pytest.mark.parametrize("sequence,cache,message", [
    ([1, 2, 3, 4], Cache(2), "cache length"),
    ([1, 2, 7, 4], Cache(3), "preserve"),
    ([1, 2, 3], Cache(3), "no continuation"),
    ([1, 2, 3, 4], object(), "reusable cache"),
])
def test_failed_generation_cannot_leave_reusable_state(sequence, cache, message):
    state = RequestPrefixCache()
    state.prepare([1, 2, 3])
    with pytest.raises(RuntimeError, match=message):
        state.finish(sequence, cache)
    assert state.cache is None and state.pending is None and state.tokens == ()


def test_new_goal_has_no_previous_state():
    state = primed()
    state.clear()
    assert state.prepare([1, 2, 3])["reused_prefix_tokens"] == 0
    assert RequestPrefixCache().prepare([1, 2, 3])["reused_prefix_tokens"] == 0


def test_one_token_suffix_is_prefill_not_decode():
    work = GenerationWork()
    work.observe(1)
    assert work.phase == "prefill" and work.prefill_tokens == 1
    work.observe(1)
    assert work.phase == "decode" and work.decode_tokens == 1
    work.reset()
    assert work.forward_calls == 0 and work.phase == "unobserved"


def test_native_bridge_accounts_reuse_and_discards_failed_cache():
    # Exercise NativeDevice.generate itself without loading weights or CUDA.
    from contextlib import nullcontext
    import json
    from types import SimpleNamespace
    from studies.energy_diagnosis.moe.native_backend import NativeDevice

    class Vector:
        def __init__(self, data):
            self.data, self.shape = data, (len(data),)

        def tolist(self):
            return self.data

    class Matrix:
        def __init__(self, data):
            self.data, self.shape = data, (1, len(data))

        def to(self, device):
            return self

        def __getitem__(self, index):
            return Vector(self.data[index[1]] if isinstance(index, tuple) else self.data)

    device = NativeDevice.__new__(NativeDevice)
    device.request_cache_mode = "exact_prefix"
    device.prefix_cache = RequestPrefixCache()
    device.request_work = GenerationWork()
    device.hook_ns, device.max_context = 0, 100
    device.tokenizer = SimpleNamespace(
        eos_token_id=0,
        apply_chat_template=lambda messages, **kw: messages[0]["content"],
        encode=lambda prompt, **kw: Matrix(json.loads(prompt)),
        decode=lambda output, **kw: str(output.tolist()),
    )
    device.torch = SimpleNamespace(no_grad=nullcontext, ones_like=lambda t: t, cuda=SimpleNamespace(synchronize=lambda: None))
    seen = []

    def generate(inputs, **kwargs):
        seen.append(kwargs)
        kwargs["streamer"].put(inputs)
        past = kwargs.get("past_key_values")
        device.request_work.observe(inputs.shape[1] - (past.get_seq_length() if past else 0))
        device.request_work.observe(1)
        sequences = Matrix(inputs.data + [80, 81])
        for token in [80, 81]:
            kwargs["streamer"].put(Vector([token]))
        kwargs["streamer"].end()
        return SimpleNamespace(sequences=sequences, past_key_values=Cache(len(sequences.data)-1)) if kwargs.get("return_dict_in_generate") else sequences

    device.model = SimpleNamespace(generate=generate)
    first = device.generate(dict(prompt="[1,2,3]", max_tokens=2))
    second = device.generate(dict(prompt="[1,2,4]", max_tokens=2))
    assert first["prefix_cache"]["reused_prefix_tokens"] == 0
    assert second["prefix_cache"]["reused_prefix_tokens"] == 2
    assert second["prefix_cache"]["new_prefill_tokens"] == 1
    assert second["tokens"] == {"prompt": 3, "completion": 2}
    assert second["generation_timing"]["generated_tokens"] == 2
    assert seen[-1]["use_cache"] is True and seen[-1]["do_sample"] is False

    def failed(inputs, **kwargs):
        raise RuntimeError("failed during generation")

    device.model.generate = failed
    with pytest.raises(RuntimeError, match="during generation"):
        device.generate(dict(prompt="[1,2,4]", max_tokens=2))
    assert device.prefix_cache.cache is None and device.prefix_cache.pending is None
    device.model.generate = generate
    device.request_cache_mode = "disabled"
    disabled = device.generate(dict(prompt="[1,2,4]", max_tokens=2))
    assert disabled["prefix_cache"]["reused_prefix_tokens"] == 0
    assert disabled["prefix_cache"]["new_prefill_tokens"] == 3
    assert "past_key_values" not in seen[-1]
