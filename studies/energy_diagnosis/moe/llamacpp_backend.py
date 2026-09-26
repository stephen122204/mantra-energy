"""llama.cpp engine behind the ALEMS native worker protocol (comparison engine, not a new policy).

Selected with config key "engine": "llamacpp". The worker starts one ``llama-server`` child in its
own process group (so goal teardown reaps it), bound to loopback, and waits for it to load. Prompts
are rendered with the Hugging Face chat template of ``model_path`` by the same tokenizer as the other
engines and sent as token IDs, so every engine receives the same prompt tokens; the GGUF vocabulary
is checked against that tokenizer at boot. Placement is the stock server flags in
``placement_args`` (e.g. ``["--n-cpu-moe", "48"]`` keeps every expert on the CPU). llama.cpp exposes
no expert placement API, so the engine declares no expert controls. Timing is host availability of
streamed tokens (same schema and clock as the other engines).
"""
import http.client
import json
import os
import socket
import subprocess
import time
from pathlib import Path


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaCppDevice:
    def __init__(self, config):
        if config.get("engine") != "llamacpp":
            raise ValueError("LlamaCppDevice requires engine=llamacpp")
        from transformers import AutoTokenizer
        from . import stock_engine

        self.request_cache_mode = config.get("request_prefix_cache", "exact_prefix")
        if self.request_cache_mode != "exact_prefix":
            raise ValueError("llama.cpp comparison runs use exact-prefix (prompt cache) only")
        server = Path(config["server_bin"]).resolve(strict=True)
        gguf = Path(config["gguf_path"]).resolve(strict=True)
        integrity = stock_engine.verify([gguf], config)
        self.max_context = int(config["max_context"])
        self.tokenizer = AutoTokenizer.from_pretrained(str(Path(config["model_path"]).resolve(strict=True)))
        placement = [str(x) for x in config.get("placement_args", [])]
        self.port = _free_port()
        cmd = [str(server), "-m", str(gguf), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(self.max_context), "-np", "1", "-ngl", str(config.get("n_gpu_layers", 999)),
               "-t", str(int(config["threads"])), "--no-webui", "--seed", "0", *placement]
        self.applied = dict(command=cmd[1:], placement_args=placement, threads=int(config["threads"]),
                            max_context=self.max_context)
        t0 = time.monotonic_ns()
        # Same process group as the worker: backend teardown kills and reaps the server too.
        self.server = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + float(config.get("load_timeout_seconds", 900))
        while True:
            if self.server.poll() is not None:
                raise RuntimeError(f"llama-server exited during load (rc={self.server.returncode})")
            try:
                status, _ = self._request("GET", "/health", timeout=5)
                if status == 200:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("llama-server did not become ready")
            time.sleep(0.5)
        t1 = time.monotonic_ns()
        probe = "<|im_start|>user\nvocabulary check: 3.14 données ✓<|im_end|>\n"
        _, body = self._request("POST", "/tokenize", dict(content=probe, add_special=False, parse_special=True))
        server_ids = json.loads(body)["tokens"]
        if server_ids != self.tokenizer.encode(probe):
            raise ValueError("GGUF vocabulary disagrees with the Hugging Face tokenizer")
        _, props = self._request("GET", "/props")
        props = json.loads(props)
        version = subprocess.run([str(server), "--version"], capture_output=True, text=True).stderr.strip().splitlines()
        self.seq = 0
        self.boot = dict(
            build=dict(engine="llamacpp", server=str(server), version=version[-2:] if version else None,
                       gguf=str(gguf), model_alias=props.get("model_alias") or props.get("model_path")),
            clock_alignment=dict(native_ns=t1, host_lower_ns=t1, host_upper_ns=t1, uncertainty_ns=0),
            controls=[],
            expert_controls=False,
            mode="native",
            engine="llamacpp",
            engine_init_ns=t1 - t0,
            request_prefix_cache=self.request_cache_mode,
            applied_config=self.applied,
            checkpoint_integrity=integrity,
            placement=dict(worker=stock_engine.numa_placement(os.getpid()),
                           server=stock_engine.numa_placement(self.server.pid)),
        )

    def _request(self, method, path, payload=None, timeout=600):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            body = json.dumps(payload) if payload is not None else None
            conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            return r.status, r.read().decode()
        finally:
            conn.close()

    def drain(self, arg):
        # generate() consumes the whole stream; the single slot is idle afterwards.
        if self.server.poll() is not None:
            raise RuntimeError("llama-server is not running")
        return {"inflight_bytes": 0}

    def generate(self, arg):
        chat = "messages" in arg
        if chat:
            prompt = self.tokenizer.apply_chat_template(arg["messages"], tools=arg["tools"], tokenize=False,
                                                        add_generation_prompt=True)
        else:
            prompt = self.tokenizer.apply_chat_template([dict(role="user", content=arg["prompt"])], tokenize=False,
                                                        add_generation_prompt=True)
        ids_in = self.tokenizer.encode(prompt)
        if len(ids_in) + arg["max_tokens"] > self.max_context:
            if chat:
                return dict(text="", finish_reason="context_exhausted", hook_ns=0,
                            tokens=dict(prompt=len(ids_in), completion=0))
            raise ValueError("prompt plus output exceeds fixed context budget")
        sampling = arg.get("sampling") or dict(mode="greedy")
        stop_ids = {self.tokenizer.eos_token_id}
        if chat:
            stop_ids |= {i for i in self.tokenizer.convert_tokens_to_ids(["<|im_end|>", "<|endoftext|>"])
                         if isinstance(i, int) and i != self.tokenizer.unk_token_id}
        payload = dict(prompt=ids_in, n_predict=arg["max_tokens"], stream=True, cache_prompt=True,
                       return_tokens=True, id_slot=0, n_probs=0)
        if sampling["mode"] == "greedy":
            payload.update(temperature=0.0, top_k=1)
        elif sampling["mode"] == "sampled":
            payload.update(temperature=sampling["temperature"], top_p=sampling["top_p"], top_k=sampling["top_k"],
                           min_p=sampling["min_p"], seed=sampling["seed"])
        else:
            raise ValueError("unknown decoding mode")
        self.seq += 1
        started = time.monotonic_ns()
        first = last = None
        ids, final = [], None
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1800)
        try:
            conn.request("POST", "/completion", body=json.dumps(payload), headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            if r.status != 200:
                raise RuntimeError(f"llama-server returned {r.status}: {r.read()[:300]!r}")
            while True:
                line = r.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                chunk = json.loads(line[5:])
                new = chunk.get("tokens") or []
                if new:
                    stamp = time.monotonic_ns()
                    if first is None:
                        first = stamp
                    last = stamp
                    ids += new
                if chunk.get("stop"):
                    final = chunk
                    break
        finally:
            conn.close()
        ended = time.monotonic_ns()
        if final is None:
            raise RuntimeError("llama-server stream ended without a final chunk")
        timings = final.get("timings") or {}
        stop_type = final.get("stop_type")
        # vLLM counts the stop token among generated tokens; llama.cpp does not stream it. Count it
        # once so completion tokens mean the same thing (decode forwards = completion - 1).
        stopped = stop_type == "eos"
        completion = len(ids) + (1 if stopped and (not ids or ids[-1] not in stop_ids) else 0)
        if completion == 0 or first is None:
            raise RuntimeError("llama.cpp produced no tokens")
        body_ids = [t for t in ids if t not in stop_ids]
        text = (self.tokenizer.decode(body_ids, skip_special_tokens=False) if chat
                else self.tokenizer.decode(body_ids, skip_special_tokens=True))
        new_prefill = timings.get("prompt_n")
        if not isinstance(new_prefill, int) or not 0 <= new_prefill <= len(ids_in):
            raise RuntimeError("llama-server did not report processed prompt tokens")
        return dict(
            text=text,
            finish_reason="stop" if stopped else "length",
            tokens=dict(prompt=len(ids_in), completion=completion),
            generation_timing=dict(
                version="host-token-availability-v1", clock_domain="host_monotonic_ns",
                started_ns=started, first_token_ready_ns=first, last_token_ready_ns=last, stream_end_ns=ended,
                generated_tokens=completion, time_to_first_token_ns=first - started,
                subsequent_tokens_ns=last - first,
                scope="Host availability of tokens streamed by llama-server (SSE), measured from generation entry; "
                      "excludes prompt rendering/tokenization. The unstreamed stop token is counted but has no stamp.",
            ),
            hook_ns=0,
            profiled=False,
            engine_report=dict(stop_type=stop_type, timings=timings, tokens_cached=final.get("tokens_cached"),
                               streamed_tokens=len(ids)),
            prefix_cache=dict(
                mode=self.request_cache_mode,
                scope="llama-server prompt cache within the owned server process (one goal, one slot)",
                reused_prefix_tokens=len(ids_in) - new_prefill,
                new_prefill_tokens=new_prefill,
                decode_forward_tokens=completion - 1,
                cached_tokens_for_next_request=None,
            ),
        )
