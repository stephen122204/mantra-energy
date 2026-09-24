"""Retain checker diagnostics without revealing them to the model or altering verdicts."""
import json
import pytest
from studies.energy_diagnosis.moe import run as campaign


@pytest.mark.parametrize('case',['returned','exception','non_json'])
def test_checker_detail_is_durable_private_artifact(tmp_path,monkeypatch,case):
    diagnostics={'passed':False,'reason':'source violates the declared constrained arithmetic repair language'}
    def verify(self,task,answer):
        if case=='exception':raise ValueError('checker input unavailable')
        return dict(passed=False,reason='independent hidden checks',diagnostics=diagnostics if case=='returned' else {1,2})
    monkeypatch.setattr(campaign.WorkloadRuntime,'verify',verify)
    root=tmp_path/'campaign'
    campaign.main(['--mode','fixture','--output',str(root),'--task','pricing-repair-v2','--policies','demand','--max-runs','1','--deadline','30'])
    record_path=next((root/'goals').glob('*/record.json'))
    record=json.loads(record_path.read_text())
    detail_path=record_path.with_name('verification.json')
    detail=json.loads(detail_path.read_text())
    assert record['verifier']['outcome']==('unavailable' if case=='exception' else 'fail')
    assert record['verifier']['evidence']==[str(detail_path.relative_to(root)).replace('\\','/')]
    if case=='returned':assert detail['result']['diagnostics']==diagnostics
    else:assert detail['status']==('error' if case=='exception' else 'unavailable')
    calls=json.loads(record_path.with_name('model-calls.json').read_text())
    assert all('independent hidden checks' not in json.dumps(c['request']) for c in calls)
    attempt=json.loads((root/'exports/attempts.jsonl').read_text().splitlines()[0])
    assert any(a['role']=='verification-detail' for a in attempt['attempt']['artifacts'])
