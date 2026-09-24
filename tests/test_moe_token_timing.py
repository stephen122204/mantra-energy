from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe.token_timing import TokenTiming


def value(*shape):
    return SimpleNamespace(shape=shape)


def test_first_token_and_subsequent_tokens_have_distinct_windows():
    clock = iter([100, 140, 150, 175, 180]).__next__
    t = TokenTiming(clock)
    t.put(value(1, 600))
    for _ in range(3):
        t.put(value(1))
    t.end()
    r = t.result(3)
    assert r["time_to_first_token_ns"] == 40
    assert r["subsequent_tokens_ns"] == 35
    assert r["generated_tokens"] == 3


def test_one_token_has_no_subsequent_decode_window():
    t = TokenTiming(iter([1, 3, 5]).__next__)
    t.put(value(1, 1))
    t.put(value(1))
    t.end()
    assert t.result(1)["subsequent_tokens_ns"] == 0


def test_incomplete_wrong_count_or_wrong_shape_is_not_valid_timing():
    t = TokenTiming()
    with pytest.raises(RuntimeError, match="incomplete"):
        t.result(0)
    with pytest.raises(RuntimeError, match="batch-one"):
        t.put(value(2, 10))
    t.put(value(1, 10))
    with pytest.raises(RuntimeError, match="one generated"):
        t.put(value(2))
    t.put(value(1))
    t.end()
    with pytest.raises(RuntimeError, match="inconsistent"):
        t.result(2)
    with pytest.raises(RuntimeError, match="after stream end"):
        t.put(value(1))


def test_backwards_clock_fails():
    t = TokenTiming(iter([10, 9]).__next__)
    t.put(value(1, 3))
    with pytest.raises(RuntimeError, match="backwards"):
        t.put(value(1))
