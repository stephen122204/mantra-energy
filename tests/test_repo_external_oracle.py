"""The candidate cannot turn process exit or a pytest-looking string into success."""
import shutil
import sys
from pathlib import Path

import networkx
import pytest

from studies.energy_diagnosis.moe import repo_oracle as oracle, repo_workload as rw


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path/'candidate'
    shutil.copytree(Path(networkx.__file__).parent, root/'networkx',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return root


@pytest.mark.parametrize('case', oracle.CASES)
def test_correct_library_passes_and_injected_defect_fails(candidate, case):
    # Portable functional test. Linux qualification must repeat with Landlock.
    assert oracle.verify(candidate, case, seed=7123, require_landlock=False)['passed']
    spec = rw.CASES[case]
    path = candidate/spec['file']
    text = path.read_text()
    assert text.count(spec['old']) == 1
    path.write_text(text.replace(spec['old'], spec['new']))
    assert not oracle.verify(candidate, case, seed=7123, require_landlock=False)['passed']


@pytest.mark.parametrize('attack', [
    'import os; os._exit(0)',
    'print(\'100 passed\'); import os; os._exit(0)',
    'print(\'{"status":"ok","outputs":[]}\'); import os; os._exit(0)',
])
def test_exit_zero_and_forged_completion_are_not_success(candidate, attack):
    p = candidate/'networkx/__init__.py'
    p.write_text(attack+'\n'+p.read_text())
    result = oracle.verify(candidate, 'connected-components-bfs', seed=3, require_landlock=False)
    assert not result['passed']


def test_candidate_receives_no_expected_answers_or_grader(monkeypatch, candidate):
    def capture(source, entry, inputs, seconds, **kwargs):
        assert 'assert ' not in source and 'expected' not in source and 'reference' not in source
        assert entry == 'evaluate'
        assert kwargs['read_paths'] == [candidate.resolve()]
        assert kwargs['require_landlock'] is True
        assert all(set(d) == {'n','directed','multi','edges','sources'} for _, d in inputs)
        return 'refused', {'error':'landlock unavailable'}
    monkeypatch.setattr(oracle.sandbox, 'run', capture)
    with pytest.raises(RuntimeError, match='sandbox unavailable'):
        oracle.verify(candidate, 'connected-components-bfs')


def test_expected_values_are_not_candidate_owned(monkeypatch, candidate):
    monkeypatch.setattr(oracle.sandbox, 'run', lambda *a, **k: ('ok', {'outputs':[True]*33}))
    assert not oracle.verify(candidate, 'connected-components-bfs', seed=3)['passed']


def test_challenges_are_reproducible_and_vary():
    a = oracle.inputs('core-number-comparison', 1)
    assert a == oracle.inputs('core-number-comparison', 1)
    assert a != oracle.inputs('core-number-comparison', 2)


def test_nan_and_boolean_not_accepted_as_numeric_answer():
    assert not oracle.same(float('nan'), 0.2)
    assert not oracle.same(True, 1)
    assert not oracle.same(True, 1.0)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='requires Linux Landlock')
def test_linux_candidate_import_allowed_but_answers_outside_tree_denied(candidate, tmp_path):
    secret = tmp_path/'answers.json'
    secret.write_text('private-reference-marker')
    assert oracle.verify(candidate, 'connected-components-bfs', seed=3)['passed']
    package = candidate/'networkx/__init__.py'
    package.write_text(f"open({str(secret)!r}).read()\n" + package.read_text())
    result = oracle.verify(candidate, 'connected-components-bfs', seed=3)
    assert not result['passed']
    assert result['failure'] == 'runtime_error'


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='requires Linux Landlock')
def test_linux_read_permission_does_not_allow_candidate_modification(candidate):
    package = candidate/'networkx/__init__.py'
    original = package.read_text()
    attack = f"open({str(package)!r}, 'w').write('overwritten')\n" + original
    package.write_text(attack)
    result = oracle.verify(candidate, 'connected-components-bfs', seed=3)
    assert not result['passed']
    assert package.read_text() == attack
