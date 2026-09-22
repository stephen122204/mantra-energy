import json
import pytest
from studies.energy_diagnosis.moe.audit_token_budget import audit


class Tokenizer:
    chat_template='owned-test-template'
    def apply_chat_template(self,messages,*,tokenize,add_generation_prompt):
        assert tokenize is False and add_generation_prompt is True
        assert messages[0]['role']=='user'
        return '<u>'+messages[0]['content']+'<a>'
    def encode(self,text,add_special_tokens=True):
        return list(text)+([0] if add_special_tokens else [])


def saved(tmp_path,adapter=None):
    path=tmp_path/'goals'/'run1'/'model-calls.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps([dict(prompt='abc',adapter=adapter or dict(status='ok',content='xyz'))]))
    return path


def test_exact_context_and_output_boundaries(tmp_path):
    path=saved(tmp_path);before=path.read_bytes()
    result=audit(tmp_path,Tokenizer(),max_context=14,max_tokens=4)
    assert result['all_saved_calls_fit']
    assert result['records'][0]['prompt_tokens']==10
    assert result['records'][0]['response_margin']==0
    assert result['records'][0]['context_remaining']==0
    assert path.read_bytes()==before
    assert audit(tmp_path,Tokenizer(),max_context=13,max_tokens=4)['errors'][0]['reasons']==['prompt_plus_output_exceeds_context']
    assert audit(tmp_path,Tokenizer(),max_context=14,max_tokens=3)['errors'][0]['reasons']==['saved_response_plus_end_token_exceeds_output']


@pytest.mark.parametrize('adapter',[dict(status='error',content='x'),dict(status='ok',content=''),dict(status='ok')])
def test_failed_or_absent_response_is_not_qualified(tmp_path,adapter):
    saved(tmp_path,adapter)
    report=audit(tmp_path,Tokenizer(),max_context=100,max_tokens=50)
    assert not report['all_saved_calls_fit']
    assert report['errors'][0]['reasons']==['response_unavailable_or_failed']


def test_no_artifacts_and_invalid_budgets_fail(tmp_path):
    with pytest.raises(ValueError,match='no recorded'):audit(tmp_path,Tokenizer(),max_context=100,max_tokens=50)
    saved(tmp_path)
    for context,output in ((True,1),(0,1),(10,11),(10,-1)):
        with pytest.raises(ValueError):audit(tmp_path,Tokenizer(),max_context=context,max_tokens=output)


def test_malformed_artifact_fails(tmp_path):
    path=saved(tmp_path);path.write_text('[{}]')
    with pytest.raises(ValueError,match='missing prompt'):audit(tmp_path,Tokenizer(),max_context=100,max_tokens=50)
