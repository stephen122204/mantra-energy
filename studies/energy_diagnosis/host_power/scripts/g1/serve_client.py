"""Streaming client for an OpenAI-compatible /v1/completions server (llama-server or vLLM), batch 1, greedy,
forced length (ignore_eos). Records CLOCK_MONOTONIC ns for every streamed chunk with text.

    python serve_client.py STACK URL MODEL_NAME PROMPT_FILE OUT.json [--n 512] [--warm 64] [--reps 3]
"""
import hashlib
import json
import sys
import time
import urllib.request

stack, url, model, prompt_file, out = sys.argv[1:6]
arg = lambda k, d: int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
N, WARM, REPS = arg("--n", 512), arg("--warm", 64), arg("--reps", 3)
prompt = open(prompt_file).read()


def gen(n):
    body = dict(model=model, prompt=prompt, max_tokens=n, temperature=0, stream=True, ignore_eos=True,
                stream_options=dict(include_usage=True))
    if stack == "vllm":
        body["min_tokens"] = n
    else:
        body["n_predict"] = n
        body["cache_prompt"] = False
    req = urllib.request.Request(url + "/v1/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    stamps, text, usage, extra = [], [], None, {}
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            t = time.monotonic_ns()
            msg = json.loads(payload)
            if msg.get("usage"):
                usage = msg["usage"]
            if msg.get("timings"):
                extra["timings"] = msg["timings"]
            for ch in msg.get("choices", []):
                if ch.get("text"):
                    stamps.append(t)
                    text.append(ch["text"])
    tokens = (usage or {}).get("completion_tokens") or extra.get("timings", {}).get("predicted_n")
    return dict(tokens=tokens, chunks=len(stamps), stamps=stamps, usage=usage, **extra,
                output_sha=hashlib.sha256("".join(text).encode()).hexdigest())


result = dict(stack=stack, model=model, n=N)
result["warmup"] = {k: v for k, v in gen(WARM).items() if k != "stamps"}
result["gens"] = [gen(N) for _ in range(REPS)]
json.dump(result, open(out, "w"))
print("CLIENT_DONE", [(g["tokens"], g["chunks"]) for g in result["gens"]])
