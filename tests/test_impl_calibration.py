"""Qualification never infers correctness from a timeout or a last good repetition."""
import json
import pytest
from studies.energy_diagnosis.moe import impl_prepare as mod


def run_case(tmp_path, monkeypatch, mode):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'problems': {'Toy/1': dict(entry='f', base_input=[[1]], plus_input=[[2]],
        pe_inputs=[[10]], canonical='canonical', fast_ref='fast', slow_ref='slow')}}))
    count = {}
    def timed(src, entry, inputs, cap):
        k = (src, len(inputs)); count[k] = count.get(k, 0) + 1
        if src == 'canonical' and mode == 'canonical_timeout':
            return 'timeout', 300, None
        if src == 'slow' and len(inputs) == 1 and mode == 'slow_timeout':
            return 'timeout', 120, None
        wrong = mode == 'wrong_first_repeat' and src == 'fast' and len(inputs) == 1 and count[k] == 1
        return 'ok', (8.0 if src == 'slow' else 0.1), {'outputs': [999 if wrong else 2 for _ in inputs]}
    monkeypatch.setattr(mod, '_timed', timed)
    output = tmp_path / 'out.json'
    mod.calibrate(source, output, reps=2)
    return json.loads(output.read_text())['problems']['Toy/1']


@pytest.mark.parametrize('mode', ['canonical_timeout', 'slow_timeout', 'wrong_first_repeat'])
def test_incomplete_or_incorrect_reference_is_ineligible(tmp_path, monkeypatch, mode):
    row = run_case(tmp_path, monkeypatch, mode)
    assert row['eligible'] is False and row['all_references_correct'] is False


def test_all_repetitions_must_pass(tmp_path, monkeypatch):
    row = run_case(tmp_path, monkeypatch, 'correct')
    assert row['eligible'] and row['all_references_correct']
    assert row['fast_ref']['perf_correct_each'] == [True, True]
