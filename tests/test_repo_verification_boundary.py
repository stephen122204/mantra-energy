"""Verify the production wiring, not just the new oracle in isolation."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import networkx
import pytest

from studies.energy_diagnosis.moe import repo_oracle, repo_test_process, repo_workload as rw


@pytest.fixture
def repository(tmp_path, monkeypatch):
    assets = tmp_path/'assets'
    workspace = tmp_path/'workspace'
    shutil.copytree(Path(networkx.__file__).parent, assets/'visible/networkx',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (assets/'task.json').write_text(json.dumps({'case':'connected-components-bfs', 'version':rw.VERSION,
        'oracle_version':repo_oracle.VERSION, 'oracle_seed':'7123'}))
    (assets/'heldout').mkdir()
    (assets/'heldout/answers.py').write_text('PRIVATE_ANSWER_MARKER = 23')
    spec = rw.CASES['connected-components-bfs']
    p = assets/'visible'/spec['file']
    p.write_text(p.read_text().replace(spec['old'], spec['new']))
    shutil.copytree(assets/'visible', workspace)
    original = repo_oracle.verify
    # Portable functional wiring; separate tests require actual Linux confinement.
    monkeypatch.setattr(repo_oracle, 'verify', lambda w,c,**kw: original(w,c,require_landlock=False,**kw))
    return assets, workspace


def test_unfixed_bug_cannot_pass_from_pytest_exit_zero(repository, monkeypatch):
    assets, workspace = repository
    def forged_pytest(*args, **kwargs):
        pytest.fail('unfixed candidate must be rejected before pytest can fake success')
    monkeypatch.setattr(rw, 'run_pytest', forged_pytest)
    result = rw.verify_workspace(assets, workspace, sys.executable)
    assert not result['passed'] and result['failure'] == 'mismatch'


def test_fixed_candidate_requires_full_public_regression_and_no_private_tests(repository, monkeypatch):
    assets, workspace = repository
    spec = rw.CASES['connected-components-bfs']
    p = workspace/spec['file']
    p.write_text(p.read_text().replace(spec['new'], spec['old']))
    def regression(python, tree, targets, sandbox):
        assert targets == ['networkx/algorithms']
        assert not (tree/'heldout').exists()
        assert not any('PRIVATE_ANSWER_MARKER' in p.read_text() for p in tree.rglob('*.py'))
        return subprocess.CompletedProcess([], 0, 'passed', '')
    monkeypatch.setattr(rw, 'run_pytest', regression)
    result = rw.verify_workspace(assets, workspace, sys.executable)
    assert result['passed'] and result['independent_oracle']['passed']
    assert result['changed_files'] == [spec['file']]


def test_regression_timeout_is_not_wrong_answer(repository, monkeypatch):
    assets, workspace = repository
    monkeypatch.setattr(repo_oracle, 'verify', lambda *a,**kw: {'passed':True})
    def timed_out(*a, **kw):
        raise subprocess.TimeoutExpired('pytest', 240)
    monkeypatch.setattr(rw, 'run_pytest', timed_out)
    result = rw.verify_workspace(assets, workspace, sys.executable)
    assert result['failure'] == 'budget' and not result['passed']


def test_private_asset_symlink_is_rejected(repository):
    assets, workspace = repository
    (workspace/'networkx/leak.py').symlink_to(assets/'heldout/answers.py')
    result = rw.verify_workspace(assets, workspace, sys.executable)
    assert not result['passed'] and 'symlink' in result['reason']


def test_pytest_wrapper_runs_visible_tests_and_uses_scratch(tmp_path):
    root = tmp_path/'public'
    root.mkdir()
    (root/'test_ok.py').write_text('def test_ok(tmp_path):\n    (tmp_path/"x").write_text("ok")\n')
    result = repo_test_process.run(sys.executable, root, ['test_ok.py'], timeout=20, require_landlock=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform.startswith('linux'), reason='non-Linux refusal')
def test_production_pytest_never_silently_disables_boundary(tmp_path):
    with pytest.raises(RuntimeError, match='sandbox unavailable'):
        repo_test_process.run(sys.executable, tmp_path, ['test.py'], timeout=20)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux boundary')
def test_pytest_candidate_cannot_read_adjacent_answers(tmp_path):
    root = tmp_path/'public'
    root.mkdir()
    secret = tmp_path/'answers.json'
    secret.write_text('PRIVATE_ANSWER_MARKER')
    (root/'test_boundary.py').write_text(
        'import pytest\ndef test_hidden():\n'
        f'    with pytest.raises(PermissionError):\n        open({str(secret)!r}).read()\n')
    result = repo_test_process.run(sys.executable, root, ['test_boundary.py'], timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux boundary')
def test_pytest_cannot_read_installed_pristine_library(tmp_path):
    pristine = Path(networkx.__file__).resolve()
    (tmp_path/'test_reference.py').write_text(
        'import pytest\ndef test_reference():\n'
        f'    with pytest.raises(PermissionError):\n        open({str(pristine)!r}).read()\n')
    result = repo_test_process.run(sys.executable, tmp_path, ['test_reference.py'], timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux boundary')
def test_scipy_solver_works_without_allowing_fork(tmp_path):
    pytest.importorskip('scipy')
    (tmp_path/'test_solver.py').write_text(
        'import os, pytest\nfrom scipy.optimize import linprog\n'
        'def test_solver():\n    assert linprog([1.], bounds=[(1,None)]).success\n'
        '    with pytest.raises(OSError):\n        os.fork()\n')
    result = repo_test_process.run(sys.executable, tmp_path, ['test_solver.py'], timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('target', ['../answers.py', '/etc/passwd', '--help'])
def test_pytest_rejects_outside_targets(tmp_path, target):
    with pytest.raises(ValueError):
        repo_test_process.run(sys.executable, tmp_path, [target], timeout=20)
