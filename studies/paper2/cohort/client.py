"""Chat adapter for the ALEMS agent loop against one shared OpenAI-compatible vLLM server.

Implements the duck-typed adapter contract of ``GoalExecutor._chat``: ``model_config`` (mutated
per turn) and ``chat(request, sampling, meta)``. The conversation is rendered client-side with
the model's own ``mistral_common`` tokenizer and sent to ``/v1/completions`` as token ids, so
every precision arm receives identical prompt tokens and the exact ids are recorded for replay.
Output token ids are streamed back (``return_token_ids``) and decoded locally with control
tokens kept, so the existing tekken-v13 tool-call parser sees ``[TOOL_CALLS]name[ARGS]{...}``.

Every request appends one record (timing, token ids as a delta against the session's previous
prompt, cached prompt tokens, finish reason, errors) to the session's request log.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import time
from typing import Callable, Optional
from urllib.parse import urlparse

TOOL_ID_LEN = 9  # mistral_common requires 9-character alphanumeric tool-call ids


def tool_call_id(harness_id: str) -> str:
    """Deterministic 9-char alphanumeric id for a harness call id such as ``t03c1``."""
    clean = "".join(ch for ch in harness_id if ch.isalnum())
    if len(clean) <= TOOL_ID_LEN:
        return clean.ljust(TOOL_ID_LEN, "0")
    return hashlib.sha256(harness_id.encode()).hexdigest()[:TOOL_ID_LEN]


def _ids_sha(ids) -> str:
    return hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()


class MistralRenderer:
    """Render ALEMS chat requests with mistral_common (tekken) and decode with control tokens."""

    def __init__(self, tekken_path: str):
        from mistral_common.tokens.tokenizers.mistral import MistralTokenizer
        self.tok = MistralTokenizer.from_file(str(tekken_path))
        self.inner = self.tok.instruct_tokenizer.tokenizer
        self.eos_id = self.inner.eos_id

    @staticmethod
    def to_openai(messages):
        out = []
        for m in messages:
            m = dict(m)
            if m.get("role") == "assistant" and m.get("tool_calls"):
                m["tool_calls"] = [dict(type="function", id=tool_call_id(c["id"]),
                                        function=dict(name=c["function"]["name"],
                                                      arguments=json.dumps(c["function"]["arguments"])
                                                      if not isinstance(c["function"]["arguments"], str)
                                                      else c["function"]["arguments"]))
                                   for c in m["tool_calls"]]
                if not m.get("content"):
                    m["content"] = None
            if m.get("role") == "tool":
                m["tool_call_id"] = tool_call_id(m["tool_call_id"])
            out.append(m)
        return out

    def encode(self, messages, tools) -> list[int]:
        from mistral_common.protocol.instruct.request import ChatCompletionRequest
        req = ChatCompletionRequest.from_openai(messages=self.to_openai(messages), tools=tools)
        return list(self.tok.encode_chat_completion(req).tokens)

    def decode(self, ids) -> str:
        from mistral_common.tokens.tokenizers.base import SpecialTokenPolicy
        body = [t for t in ids if t != self.eos_id]
        return self.inner.decode(body, special_token_policy=SpecialTokenPolicy.KEEP)


def sampling_payload(sampling: dict) -> dict:
    if sampling.get("mode", "greedy") == "greedy":
        return dict(temperature=0.0)
    if sampling["mode"] != "sampled":
        raise ValueError("unknown decoding mode")
    return dict(temperature=sampling["temperature"], top_p=sampling["top_p"], top_k=sampling["top_k"],
                min_p=sampling["min_p"], seed=sampling["seed"])


def completion_request(served_model: str, prompt: list, max_tokens: int, sampling: dict, extra: Optional[dict] = None) -> dict:
    """The exact streaming /v1/completions body agent sessions send (also used by the engine check).

    Output text is decoded client-side from the returned token ids (special tokens kept), so the
    server's own detokenization keeps its default; vLLM 0.10.2 with the Mistral tokenizer fails
    every request that sets skip_special_tokens=False."""
    return dict(model=served_model, prompt=prompt, max_tokens=max_tokens, stream=True,
                stream_options=dict(include_usage=True), return_token_ids=True,
                **sampling_payload(sampling), **(extra or {}))


def stream_completion(host: str, port: int, payload: dict, timeout: float):
    """POST a streaming completion; returns (first_token_ns, ids, finish, usage, server_text).
    An error event in the stream raises (it is never read as an empty completion)."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("POST", "/v1/completions", body=json.dumps(payload),
                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        r = conn.getresponse()
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}: {r.read()[:500]!r}")
        first_ns, ids, finish, usage, text = None, [], None, {}, []
        done = False
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            chunk = json.loads(data)
            if chunk.get("error") is not None:
                raise RuntimeError(f"server error in stream: {json.dumps(chunk['error'])[:500]}")
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                got = ch.get("token_ids") or []
                if got and first_ns is None:
                    first_ns = time.monotonic_ns()
                ids.extend(got)
                text.append(ch.get("text") or "")
                finish = ch.get("finish_reason") or finish
        if not done or finish is None:
            raise RuntimeError("incomplete completion stream: missing terminal event or finish reason")
        if usage.get("completion_tokens", 0) and not ids:
            raise RuntimeError("completion stream reported generated tokens without token IDs")
        return first_ns, ids, finish, usage, "".join(text)
    finally:
        conn.close()


class SharedServerAdapter:
    def __init__(self, base_url: str, served_model: str, renderer, *, max_tokens: int, max_model_len: int,
                 record: Callable[[dict], None], session_id: str, extra_body: Optional[dict] = None):
        self.base = urlparse(base_url)
        self.served_model, self.renderer = served_model, renderer
        self.max_model_len = max_model_len
        self.model_config = {"request_timeout_seconds": 600, "max_tokens": max_tokens}
        self.record, self.session_id = record, session_id
        self.extra_body = extra_body or {}
        self.turn = 0
        self._prev_prompt: list[int] = []

    def _delta(self, ids):
        prev = self._prev_prompt
        n = 0
        for a, b in zip(prev, ids):
            if a != b:
                break
            n += 1
        return n, ids[n:]

    def _stream(self, payload, timeout):
        return stream_completion(self.base.hostname, self.base.port, payload, timeout)

    def chat(self, request, sampling, meta):
        self.turn += 1
        rec = dict(kind="request", session_id=self.session_id, turn=self.turn, task_id=meta.get("task_id"),
                   t_submit_wall=time.time(), t_submit_ns=time.monotonic_ns())
        try:
            prompt = self.renderer.encode(request["messages"], request["tools"])
            max_tokens = int(self.model_config["max_tokens"])
            same, suffix = self._delta(prompt)
            rec.update(prompt_len=len(prompt), prompt_sha256=_ids_sha(prompt), prefix_same_as_prev=same,
                       prompt_suffix_ids=suffix, max_tokens=max_tokens, sampling=sampling)
            if len(prompt) + max_tokens > self.max_model_len:
                rec.update(finish_reason="context_exhausted", completion_tokens=0, t_done_ns=time.monotonic_ns())
                self.record(rec)
                self._prev_prompt = prompt
                return dict(status="ok", content="", finish_reason="context_exhausted",
                            tokens=dict(prompt=len(prompt), completion=0), token_provenance="tokenizer", backend=rec)
            payload = completion_request(self.served_model, prompt, max_tokens, sampling, self.extra_body)
            first_ns, ids, finish, usage, server_text = self._stream(payload, float(self.model_config["request_timeout_seconds"]))
            done_ns = time.monotonic_ns()
            content = self.renderer.decode(ids)
            details = usage.get("prompt_tokens_details") or {}
            rec.update(t_first_ns=first_ns, t_done_ns=done_ns, output_ids=ids, completion_tokens=len(ids),
                       usage=usage, cached_tokens=details.get("cached_tokens"), finish_reason=finish,
                       server_text_chars=len(server_text))
            self.record(rec)
            self._prev_prompt = prompt
            if usage.get("prompt_tokens") not in (None, len(prompt)):
                raise RuntimeError(f"server counted {usage.get('prompt_tokens')} prompt tokens, sent {len(prompt)}")
            reason = "length" if finish == "length" else "stop"
            return dict(status="ok", content=content, finish_reason=reason,
                        tokens=dict(prompt=len(prompt), completion=len(ids)), token_provenance="tokenizer",
                        backend=dict(t_first_ns=first_ns, t_done_ns=done_ns, cached_tokens=rec["cached_tokens"]))
        except Exception as exc:
            rec.update(error=f"{type(exc).__name__}: {exc}", t_done_ns=time.monotonic_ns())
            self.record(rec)
            # A closed stream aborts the request inside vLLM; nothing else is owned by this session.
            return dict(status="error", error=rec["error"], tokens={}, token_provenance="unknown",
                        owned_work_terminated=True)
