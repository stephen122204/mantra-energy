"""Regressions for missing evidence that must not qualify a campaign result."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.paper2.cohort import campaign, guards, pilot, records


@pytest.mark.parametrize('metrics', ['', 'vllm:num_requests_running 0\n',
                                    'vllm:num_requests_running NaN\nvllm:num_requests_waiting 0\n'])
def test_missing_or_invalid_request_metrics_do_not_establish_drain(monkeypatch, metrics):
    monkeypatch.setattr(guards, 'fetch_metrics', lambda _: metrics)
    assert guards.wait_drained('fixture', timeout_s=0)['drained'] is False


def test_zero_running_and_waiting_establish_drain(monkeypatch):
    monkeypatch.setattr(guards, 'fetch_metrics', lambda _: 'vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n')
    assert guards.wait_drained('fixture', timeout_s=0)['drained'] is True


def test_missing_cached_tokens_does_not_establish_cold_cache(monkeypatch):
    results = iter([(200, {'usage': {'prompt_tokens_details': {'cached_tokens': 0}}}),
                    (200, {'usage': {'prompt_tokens_details': {'cached_tokens': 64}}}),
                    (200, None), (200, {'usage': {}})])
    monkeypatch.setattr(guards, '_post', lambda *a, **k: next(results))
    assert guards.verified_cache_reset('fixture', 'm', list(range(64)))['ok'] is False


@pytest.mark.parametrize('qualification', [
    {'qualified': True},
    {'qualified': True, 'controls_valid': True, 'gold': {'passed': True, 'reason': 'resolved'},
     'noop': {'passed': False, 'reason': 'not resolved', 'infrastructure': True}},
])
def test_legacy_or_invalid_qualification_cannot_enter_campaign(tmp_path, qualification):
    (tmp_path / 'qualification.json').write_text(json.dumps([dict(instance_id='t', **qualification)]))
    with pytest.raises(SystemExit, match='not qualified'):
        pilot.check_qualified(tmp_path / 'catalog.json', [{'task_id': 't'}])


def test_complete_control_evidence_qualifies(tmp_path):
    q = dict(instance_id='t', qualified=True, controls_valid=True,
             gold=dict(passed=True, reason='resolved'), noop=dict(passed=False, reason='not resolved'))
    (tmp_path / 'qualification.json').write_text(json.dumps([q]))
    pilot.check_qualified(tmp_path / 'catalog.json', [{'task_id': 't'}])


def replay_summary(tmp_path, **changes):
    root = tmp_path / 'cohorts' / 'target-replay'
    root.mkdir(parents=True)
    summary = dict(failed=0, mismatched_turns=0, energy=dict(cpu_plus_gpu_j=10), drain=dict(drained=True))
    summary.update(changes)
    (root / 'replay-summary.json').write_text(json.dumps(summary))
    return campaign.cell_validity(tmp_path, 'target-replay', 'replay', {'source': 'source/live'},
                                  'target', 'cpu_package+gpu_board')


def test_cross_precision_replay_must_match_forced_tokens(tmp_path):
    assert any('fidelity' in x for x in replay_summary(tmp_path, mismatched_turns=1))


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, None])
def test_nonphysical_energy_is_invalid(tmp_path, value):
    assert any('no valid' in x for x in replay_summary(tmp_path, energy=dict(cpu_plus_gpu_j=value)))


def test_missing_drain_and_failed_verification_are_invalid(tmp_path):
    step = 'a-live'; root = tmp_path / 'cohorts' / step / step; root.mkdir(parents=True)
    (root / 'cohort-summary.json').write_text(json.dumps(dict(
        reconciliation=dict(reconciled=True), energy=dict(cpu_plus_gpu_j=10),
        sessions=[dict(task_id='t', outcome='completed', verdict='unavailable')],
        container_cleanup=dict(checked=False))))
    problems = campaign.cell_validity(tmp_path, step, 'live', {'task_ids': ['t']}, 'a', 'cpu_package+gpu_board')
    assert any('drain' in p for p in problems)
    assert any('verification' in p for p in problems)
    assert any('cleanup' in p for p in problems)


def collected(tmp_path, failures, metric='cpu_package+gpu_board'):
    plan = dict(gpu_uuid='UNBOUND', allocation='UNBOUND', passes=[
        dict(blocks={'a': dict(steps=[{'live': dict(name='live', task_ids=['t'])}])}),
        dict(blocks={'a': dict(steps=[{'replay': dict(name='replay', source='live')}])})])
    sha = campaign.canonical_sha(plan)
    bound = dict(plan, gpu_uuid='GPU-a', allocation='l', binding=dict(plan_sha256=sha, energy_metric=metric))
    manifest = dict(campaign_id='test', commit='c0', energy_metric='cpu_package+gpu_board',
                    nodes={'node': dict(gpu_class='A100', rounds=[dict(file='round.json', plan_sha256=sha)])})
    d = tmp_path / 'run'; d.mkdir(); (d/'plan.json').write_text(json.dumps(bound))
    ev = [dict(kind='driver_start', revision='c0', dirty=False, energy_metric=metric)] + failures + [dict(kind='driver_end')]
    (d/'driver-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in ev)); records.write_manifest(d)
    return campaign.collect(manifest, [d])


def test_failed_configuration_is_recorded_but_not_analysis_ready(tmp_path):
    cov = collected(tmp_path, [dict(kind='server_start_failed', config='a', pass_index=i) for i in (0, 1)])
    assert cov['rounds'][0]['status'] == 'complete_with_configuration_outcomes'
    assert not cov['analysable']


def test_failure_in_one_pass_does_not_excuse_missing_other_pass(tmp_path):
    cov = collected(tmp_path, [dict(kind='server_start_failed', config='a', pass_index=0)])
    assert cov['rounds'][0]['status'] == 'partial'
    assert cov['rounds'][0]['runs'][0]['missing_cells'] == ['a-replay']


def test_wrong_energy_metric_rejected_even_with_valid_checksums(tmp_path):
    cov = collected(tmp_path, [dict(kind='server_start_failed', config='a', pass_index=i) for i in (0, 1)], 'gpu_board')
    assert not cov['analysable']
    assert any('energy metric' in p for p in cov['rounds'][0]['runs'][0]['problems'])


def test_empty_campaign_is_not_analysable():
    assert not campaign.collect(dict(campaign_id='empty', nodes={}), [])['analysable']


def test_verifier_failure_invalidates_cohort():
    from studies.paper2.cohort.cohort import summarize
    spec = SimpleNamespace(cohort_id='c', config_id='a', mode='fixed', admission_limit=1)
    done = [SimpleNamespace(attempt_id='x', item={'task_id':'t'}, session_id='s', outcome='completed',
                            offered=0, admitted=0, ended=1)]
    summary = summarize(spec, done, {'x': {'verdict':'unavailable'}}, {'cpu_plus_gpu_j': 10}, [])
    assert summary['infra_invalid'] and summary['verified_pass'] == 0


@pytest.mark.parametrize('report,rc', [({}, 0), ({'t': {}}, 0), ({'t': {'resolved': 'false'}}, 0),
                                    ({'t': {'resolved': False}}, 1), ([], 0)])
def test_malformed_harness_report_is_infrastructure_failure(tmp_path, report, rc):
    from studies.paper2.cohort import swebench_workload as sw
    def run(argv, timeout, cwd=None):
        rid = argv[argv.index('--run_id') + 1]
        d = Path(cwd) / 'logs' / 'run_evaluation' / rid / 'paper2' / 't'
        d.mkdir(parents=True)
        (d / 'report.json').write_text(json.dumps(report))
        return rc, '', ''
    result = sw.evaluate_patch('t', 'diff --git a/x b/x\n', tmp_path, run=run)
    assert result['infrastructure'] and not result['passed']


@pytest.mark.parametrize('summary', [
    {}, {'drain': {'drained': False}},
    {'drain': {'drained': True}, 'container_cleanup': {'checked': False}},
    {'drain': {'drained': True}, 'container_cleanup': {'checked': True, 'leftover': ['container']}},
])
def test_unclean_boundary_prevents_next_measurement(summary):
    with pytest.raises(RuntimeError, match='stopping before another measurement'):
        guards.require_clean_boundary(summary)


def test_replay_keeps_server_drain_inside_measurement(tmp_path, monkeypatch):
    from studies.paper2.cohort import replay
    order = []
    def drained(*args, **kwargs):
        order.append('drain')
        return dict(drained=False)
    class Measurement:
        def start_goal(self): order.append('start')
        def finish_goal(self): order.append('finish')
    monkeypatch.setattr(guards, 'wait_drained', drained)
    result = replay.run_replay('r', [], 'http://fixture:80', 'm', tmp_path,
                               admission_limit=1, measurement=Measurement())
    assert order == ['start', 'drain', 'finish']
    assert result['drain']['drained'] is False
    assert any('drain' in p for p in replay_summary(tmp_path, drain=result['drain']))


def test_selected_gpu_must_have_its_own_advancing_counter(tmp_path):
    report = dict(gpus=dict(devices=[dict(name='A100', uuid='GPU-a', energy_counter=dict(advancing=False))]),
                  verdict=dict(gpu_energy_counter=True, task_sandbox_landlock_abi4=True, cpu_package_counters=True))
    manifest = dict(nodes={'n': dict(gpu_class='A100', rounds=[])})
    with pytest.raises(SystemExit, match='GPU energy counter not advancing'):
        campaign.bind(manifest, tmp_path, 'n', report, 'lease')
