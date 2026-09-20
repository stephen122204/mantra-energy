"""Encode caller-supplied fixed diagnostic text using original tokenizer files."""
import argparse
import json
from pathlib import Path
from .capture_fixed_forward import digest, validate_case


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tokenizer',required=True)
    p.add_argument('--input',required=True,help='JSON: case_id, model_revision, prompt_text, continuation_text; optional primer with both text fields')
    p.add_argument('--output',required=True)
    a = p.parse_args()
    from transformers import AutoTokenizer
    root = Path(a.tokenizer)
    tok = AutoTokenizer.from_pretrained(root,local_files_only=True,trust_remote_code=False)
    case = json.loads(Path(a.input).read_text())
    for key in ('case_id','model_revision','prompt_text','continuation_text'):
        if not isinstance(case.get(key),str) or not case[key]:
            raise ValueError(f'missing or invalid {key}')
    def encode(row):
        rendered = tok.apply_chat_template([dict(role='user',content=row['prompt_text'])],tokenize=False,add_generation_prompt=True)
        prompt = tok.encode(rendered)
        continuation = tok.encode(row['continuation_text'],add_special_tokens=False)
        for key,ids in [('prompt_ids',prompt),('continuation_ids',continuation)]:
            if key in row and row[key] != ids:
                raise ValueError(f'existing {key} differ; do not silently change a diagnostic')
            row[key] = ids
        validate_case(row,len(tok),4096)
    encode(case)
    if 'primer' in case:
        encode(case['primer'])
    case['tokenizer_files'] = {name:digest(root/name) for name in ('tokenizer.json','tokenizer_config.json','chat_template.jinja') if (root/name).is_file()}
    if 'tokenizer.json' not in case['tokenizer_files'] or 'tokenizer_config.json' not in case['tokenizer_files']:
        raise ValueError('original tokenizer JSON files are required')
    case['source_input_sha256'] = digest(a.input)
    case['preparation_script_sha256'] = digest(__file__)
    case['continuation_origin'] = 'Caller-supplied forced diagnostic text; not an observed generated response.'
    with Path(a.output).open('x') as f:
        json.dump(case,f,indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
