"""Fixture OpenAI-compatible completions server for runner tests. Never used for measurements.

Streams token ids like vLLM 0.10.x with ``return_token_ids``; honours ``vllm_xargs.forced_tokens``
(replay); serves /health, /v1/models and a Prometheus /metrics page; tracks peak concurrency.
Behaviour per request is chosen by ``mode``: ``submit`` (submit_answer {}), ``text`` (no tool
call), ``error`` (HTTP 500), ``stream_error`` (HTTP 200 with an error event, as vLLM 0.10.2 does), ``slow`` (submit after ``delay_s``), ``tool`` (call the first task tool
listed in the prompt, then submit once a tool result is present).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .forcing import parse_forced


# Valid first calls for the C2 business and numerical tools (the ``tool`` mode).
FIXTURE_TOOL_ARGS = {"sql": {"action": "schema"}, "regression": {"action": "inspect"}}


class FakeVllm:
    def __init__(self, renderer, served_model="fixture", mode="submit", delay_s=0.0):
        self.renderer, self.served_model, self.mode, self.delay_s = renderer, served_model, mode, delay_s
        self.lock = threading.Lock()
        self.inflight = self.peak = self.requests = 0
        self.prompt_tokens = self.generation_tokens = 0
        self.seen_prefixes: set = set()
        self.cached = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def answer_ids(self):
        r = self.renderer
        tc, ar = r.inner.get_control_token("[TOOL_CALLS]"), r.inner.get_control_token("[ARGS]")
        return [tc] + r.inner.encode("submit_answer", bos=False, eos=False) + [ar] + \
            r.inner.encode('{"answer": {}}', bos=False, eos=False) + [r.eos_id]

    def _handler(server):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    return self._send(200, "")
                if self.path == "/v1/models":
                    return self._send(200, json.dumps(dict(data=[dict(id=server.served_model)])))
                if self.path == "/metrics":
                    with server.lock:
                        text = (f"vllm:num_requests_running{{model_name=\"x\"}} {server.inflight}\n"
                                f"vllm:num_requests_waiting{{model_name=\"x\"}} 0\n"
                                f"vllm:prompt_tokens_total{{model_name=\"x\"}} {server.prompt_tokens}\n"
                                f"vllm:generation_tokens_total{{model_name=\"x\"}} {server.generation_tokens}\n"
                                f"vllm:prefix_cache_hits_total{{model_name=\"x\"}} {server.cached}\n")
                    return self._send(200, text, "text/plain")
                self._send(404, "")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with server.lock:
                    server.inflight += 1
                    server.requests += 1
                    server.peak = max(server.peak, server.inflight)
                try:
                    if server.mode == "error":
                        return self._send(500, json.dumps(dict(error="fixture failure")))
                    if server.mode == "stream_error" or body.get("skip_special_tokens") is False:
                        # vLLM 0.10.2 + Mistral tokenizer: HTTP 200, then an error event and [DONE]
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        err = dict(error=dict(message="", type="BadRequestError", param=None, code=400))
                        self.wfile.write(f"data: {json.dumps(err)}\n\ndata: [DONE]\n\n".encode())
                        return
                    prompt = body["prompt"]
                    forced = parse_forced((body.get("vllm_xargs") or {}).get("forced_tokens"))
                    if forced is not None:
                        ids = forced[: body["max_tokens"]]
                    elif server.mode == "tool" and server.renderer.inner.get_control_token("[TOOL_RESULTS]") not in prompt:
                        import re
                        text = server.renderer.inner.decode(prompt)
                        names = [n for n in re.findall(r'"name": "([A-Za-z_][A-Za-z0-9_]*)"', text) if n != "submit_answer"]
                        r = server.renderer
                        ids = [r.inner.get_control_token("[TOOL_CALLS]")] + r.inner.encode(names[0], bos=False, eos=False) + \
                            [r.inner.get_control_token("[ARGS]")] + r.inner.encode(json.dumps(FIXTURE_TOOL_ARGS.get(names[0], {})), bos=False, eos=False) + [r.eos_id]
                    elif server.mode == "text":
                        ids = server.renderer.inner.encode("I will think about it.", bos=False, eos=False) + [server.renderer.eos_id]
                    else:
                        ids = server.answer_ids()
                    if server.mode == "slow" or server.delay_s:
                        time.sleep(server.delay_s)
                    with server.lock:
                        cached = 0
                        for n in range(len(prompt), 0, -16):
                            if tuple(prompt[:n]) in server.seen_prefixes:
                                cached = n
                                break
                        for n in range(16, len(prompt) + 1, 16):
                            server.seen_prefixes.add(tuple(prompt[:n]))
                        server.prompt_tokens += len(prompt)
                        server.generation_tokens += len(ids)
                        server.cached += cached
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for i in range(0, len(ids), 4):
                        part = ids[i:i + 4]
                        last = i + 4 >= len(ids)
                        chunk = dict(choices=[dict(index=0, text="", token_ids=part,
                                                   finish_reason=("length" if len(ids) >= body["max_tokens"] else "stop") if last else None)])
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    usage = dict(prompt_tokens=len(prompt), completion_tokens=len(ids),
                                 prompt_tokens_details=dict(cached_tokens=cached))
                    self.wfile.write(f"data: {json.dumps(dict(choices=[], usage=usage))}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                finally:
                    with server.lock:
                        server.inflight -= 1
        return H
