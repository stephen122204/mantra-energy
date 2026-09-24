"""Read-only tokenizer replay of saved conversations; no model or GPU required."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(campaign, tokenizer, *, max_context, max_tokens):
    for value in (max_context, max_tokens):
        if type(value) is not int or value < 1:
            raise ValueError('budgets must be positive integers')
    if max_tokens > max_context:
        raise ValueError('output budget exceeds context budget')
    root = Path(campaign)
    paths = sorted(root.glob('goals/*/model-calls.json'))
    if not paths:
        raise ValueError('no recorded model calls found')
    records = []
    errors = []
    for path in paths:
        payload = path.read_bytes()
        calls = json.loads(payload)
        if not isinstance(calls, list) or not calls:
            raise ValueError(f'empty or invalid model-call artifact: {path}')
        for step, call in enumerate(calls):
            request = call.get('request') if isinstance(call, dict) else None
            chat = isinstance(request, dict)
            if chat and not (isinstance(request.get('messages'), list) and isinstance(request.get('tools'), list)):
                raise ValueError(f'invalid chat request: {path}:{step}')
            if not chat and (not isinstance(call, dict) or not isinstance(call.get('prompt'), str)):
                raise ValueError(f'missing prompt: {path}:{step}')
            adapter = call.get('adapter')
            if not isinstance(adapter, dict):
                raise ValueError(f'missing adapter record: {path}:{step}')
            if chat:
                # chat-tools-v1: the same template call as native_backend.generate.
                rendered = tokenizer.apply_chat_template(
                    request['messages'], tools=request['tools'],
                    tokenize=False, add_generation_prompt=True,
                )
            else:
                rendered = tokenizer.apply_chat_template(
                    [dict(role='user', content=call['prompt'])],
                    tokenize=False, add_generation_prompt=True,
                )
            # Match native_backend.generate: encode the rendered template, not
            # apply_chat_template(tokenize=True), whose special-token rule differs.
            prompt_tokens = len(tokenizer.encode(rendered))
            response = adapter.get('content')
            checked = adapter.get('status') == 'ok' and isinstance(response, str) and bool(response)
            response_tokens = len(tokenizer.encode(response, add_special_tokens=False)) if checked else None
            reasons = []
            finish = adapter.get('finish_reason') if chat else None
            budget_outcome = None
            over_context = prompt_tokens + max_tokens > max_context
            if chat and finish == 'context_exhausted':
                # The harness recorded a context_exhausted outcome and generated
                # nothing; only an inconsistent replay is an error.
                budget_outcome = 'context_exhausted'
                if not over_context:
                    reasons.append('context_exhausted_but_replay_fits')
            elif chat and finish == 'length':
                budget_outcome = 'output_truncated'
                if over_context:
                    reasons.append('prompt_plus_output_exceeds_context')
                if not checked or response_tokens < max_tokens:
                    reasons.append('truncation_recorded_below_output_budget')
            else:
                if over_context:
                    reasons.append('prompt_plus_output_exceeds_context')
                if not checked:
                    reasons.append('response_unavailable_or_failed')
                elif response_tokens + 1 > max_tokens:
                    reasons.append('saved_response_plus_end_token_exceeds_output')
            row = dict(artifact=path.relative_to(root).as_posix(),
                       artifact_sha256=hashlib.sha256(payload).hexdigest(), step=step,
                       prompt_tokens=prompt_tokens, response_tokens=response_tokens,
                       output_budget=max_tokens, context_budget=max_context,
                       context_remaining=max_context-prompt_tokens-max_tokens,
                       response_margin=None if response_tokens is None else max_tokens-response_tokens-1,
                       budget_outcome=budget_outcome, reasons=reasons)
            records.append(row)
            if reasons:
                errors.append(dict(artifact=row['artifact'], step=step, reasons=reasons))
    template = getattr(tokenizer, 'chat_template', None)
    return dict(checked_calls=len(records), all_saved_calls_fit=not errors,
                chat_template_sha256=hashlib.sha256(template.encode()).hexdigest() if isinstance(template,str) else None,
                records=records, errors=errors,
                scope='Tokenizer replay of saved conversations only. One output token is reserved for termination. '
                      'Does not guarantee future model response length, unseen tool paths, correctness, or fidelity. '
                      'Scripted responses remain scripted evidence; token counts do not make them native runs.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--tokenizer-path', required=True, help='Local pinned tokenizer directory; no network access')
    parser.add_argument('--max-context', required=True, type=int)
    parser.add_argument('--max-tokens', required=True, type=int)
    args = parser.parse_args(argv)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path, local_files_only=True, trust_remote_code=False)
    report = audit(args.campaign, tokenizer, max_context=args.max_context, max_tokens=args.max_tokens)
    report['tokenizer_files'] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(args.tokenizer_path).iterdir()) if p.is_file() and p.suffix in {'.json','.jinja','.txt'}
    }
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['all_saved_calls_fit'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
