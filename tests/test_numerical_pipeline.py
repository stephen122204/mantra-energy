"""Injected model/sensors; real numerical tools, executor, ledger and exports.

This test wires the additive adapter without changing the production runner.
Production CLI/provenance checks are in test_task_pack_cli.py; native evidence is separate.
"""
import json
import pytest
from studies.energy_diagnosis.moe import run as campaign
from studies.energy_diagnosis.moe.numerical_workload import create_task, RegressionRuntime


class ModelFixture:
    def __init__(self, wrong=False):
        self.model_config = {'request_timeout_seconds':30, 'max_tokens':512}
        self.wrong = wrong

    def call(self, prompt, temperature):
        context = json.loads(prompt)
        assert 'expected' not in context
        outputs = context.get('tool_results', [])
        if not outputs:
            value = {'tool_calls':[{'id':'fit','tool':'regression','args':{'action':'fit'}}]}
        else:
            value = {'answer':outputs[-1]['result']}
            if self.wrong:
                value['answer']['by_group']['g0']['count'] += 1
        return {'status':'ok','content':json.dumps(value),'tokens':{'prompt':10,'completion':10},'token_provenance':'estimated'}


@pytest.mark.parametrize('case', ['success','wrong_answer','missing_telemetry'])
def test_full_local_numerical_run_and_resume(tmp_path, monkeypatch, case):
    monkeypatch.setattr(campaign,'create_tasks',lambda root:(create_task(root/'numerical',rows=8192),))
    monkeypatch.setattr(campaign,'WorkloadRuntime',lambda root, fixture_case=None:RegressionRuntime(root))
    monkeypatch.setattr(campaign,'BackendAdapter',lambda backend, max_tokens:ModelFixture(case=='wrong_answer'))
    output=tmp_path/'run'
    args=['--mode','fixture','--output',str(output),'--policies','demand',
          '--max-runs','1','--deadline','30','--fixture-case',case]
    campaign.main(args)
    manifest=json.loads((output/'moe-manifest.json').read_text())
    assert manifest['task_catalog'][0]['family']=='grouped-regression'
    files=list((output/'goals').glob('*/record.json'))
    assert len(files)==1
    record=json.loads(files[0].read_text())
    assert record['verifier']['outcome']==('fail' if case=='wrong_answer' else 'pass')
    assert record['simulated'] is True
    if case=='missing_telemetry':
        assert any(m['energy_j'] is None for m in record['measurements'])
    else:
        assert all(m['status']=='valid' for m in record['measurements'])
    before=(output/'exports/attempts.jsonl').read_bytes()
    campaign.main(args)
    assert (output/'exports/attempts.jsonl').read_bytes()==before
    assert len(list((output/'goals').glob('*/record.json')))==1
