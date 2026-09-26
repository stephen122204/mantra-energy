"""vLLM engine behind the ALEMS native worker protocol (comparison engine, not a new policy).

Selected with config key "engine": "vllm". Prompts are rendered with the model's own chat template by the
same tokenizer as the native backend, so the engine receives identical prompt token IDs. vLLM exposes no
expert placement API, so the engine declares no expert controls and the lifecycle issues no expert RPCs.
Timing uses host token availability from the engine step loop (same schema and clock as TokenTiming).
"""
import importlib.metadata
import json
import os
import time
from pathlib import Path

VLLM_VERSION = "0.10.2"


class VllmDevice:
    def __init__(self, config):
        if config.get("engine") != "vllm":
            raise ValueError("VllmDevice requires engine=vllm")
        if importlib.metadata.version("vllm") != VLLM_VERSION:
            raise ValueError(f"vLLM {VLLM_VERSION} is required")
        import torch
        from transformers import AutoTokenizer
        from vllm import EngineArgs, LLMEngine

        if torch.cuda.device_count() != 1:
            raise ValueError("expose exactly one allocated GPU through CUDA_VISIBLE_DEVICES")
        path = Path(config["model_path"]).resolve(strict=True)
        manifest = json.loads((path / "alems-weights.json").read_text())
        if manifest["revision"] != config["model_revision"]:
            raise ValueError("wrong checkpoint revision")
        from . import stock_engine

        files = [path / name for name in manifest["files"]]
        if any(p.resolve().parent != path for p in files):
            raise ValueError("checkpoint file outside the model directory")
        if config.get("checkpoint_verification", "full") == "full":
            from .prepare import file_sha

            for name, digest in manifest["files"].items():
                if file_sha(path / name) != digest:
                    raise ValueError(f"checkpoint bytes changed: {name}")
            integrity = dict(mode="full")
        else:
            integrity = stock_engine.verify(files + [path / "alems-weights.json"], config)
        self.request_cache_mode = config.get("request_prefix_cache", "exact_prefix")
        if self.request_cache_mode != "exact_prefix":
            raise ValueError("vLLM comparison runs use exact-prefix (automatic prefix caching) only")
        self.max_context = int(config["max_context"])
        self.tokenizer = AutoTokenizer.from_pretrained(str(path))
        self.applied = dict(
            cpu_offload_gb=float(config["cpu_offload_gb"]),
            gpu_memory_utilization=float(config.get("gpu_memory_utilization", 0.90)),
            max_model_len=self.max_context,
            max_num_seqs=1,
            enable_prefix_caching=True,
            seed=0,
        )
        # Optional: one profiled call (vLLM's torch profiler), for the kernel-launch/GPU-idle measurement.
        self.profile_call = int(config.get("profile_call_index", 0))
        if self.profile_call:
            os.environ["VLLM_TORCH_PROFILER_DIR"] = str(config["torch_profile_dir"])
        t0 = time.monotonic_ns()
        self.engine = LLMEngine.from_engine_args(EngineArgs(model=str(path), dtype="bfloat16", **self.applied))
        t1 = time.monotonic_ns()
        self.seq = 0
        self.boot = dict(
            build=dict(engine="vllm", vllm=VLLM_VERSION, torch=torch.__version__,
                       transformers=importlib.metadata.version("transformers")),
            clock_alignment=dict(native_ns=t1, host_lower_ns=t1, host_upper_ns=t1, uncertainty_ns=0),
            controls=[],
            expert_controls=False,
            mode="native",
            engine="vllm",
            checkpoint_integrity=integrity,
            placement=stock_engine.numa_placement(os.getpid()),
            engine_init_ns=t1 - t0,
            request_prefix_cache=self.request_cache_mode,
            applied_config=self.applied,
        )

    def drain(self, arg):
        # Each generate call runs the engine loop to completion, so no request is in flight.
        if self.engine.has_unfinished_requests():
            raise RuntimeError("vLLM engine still has unfinished requests")
        return {"inflight_bytes": 0}

    def generate(self, arg):
        from vllm import SamplingParams, TokensPrompt
        from vllm.sampling_params import RequestOutputKind

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
        stop_ids = [self.tokenizer.eos_token_id]
        if chat:
            stop_ids += [i for i in self.tokenizer.convert_tokens_to_ids(["<|im_end|>", "<|endoftext|>"])
                         if isinstance(i, int) and i != self.tokenizer.unk_token_id]
        common = dict(max_tokens=arg["max_tokens"], stop_token_ids=sorted(set(stop_ids)), skip_special_tokens=False,
                      detokenize=False, output_kind=RequestOutputKind.DELTA)
        if sampling["mode"] == "greedy":
            params = SamplingParams(temperature=0.0, **common)
        elif sampling["mode"] == "sampled":
            params = SamplingParams(temperature=sampling["temperature"], top_p=sampling["top_p"],
                                    top_k=sampling["top_k"], min_p=sampling["min_p"], seed=sampling["seed"], **common)
        else:
            raise ValueError("unknown decoding mode")
        self.seq += 1
        rid = f"alems-{self.seq}"
        started = time.monotonic_ns()
        first = last = None
        ids, cached = [], None
        profiling = self.profile_call and self.seq == self.profile_call
        if profiling:
            self.engine.start_profile()
        self.engine.add_request(rid, TokensPrompt(prompt_token_ids=ids_in), params)
        while self.engine.has_unfinished_requests():
            for out in self.engine.step():
                if out.request_id != rid:
                    continue
                new = list(out.outputs[0].token_ids)
                if new:
                    stamp = time.monotonic_ns()
                    if first is None:
                        first = stamp
                    last = stamp
                    ids += new
                if cached is None and out.num_cached_tokens is not None:
                    cached = int(out.num_cached_tokens)
        ended = time.monotonic_ns()
        if profiling:
            self.engine.stop_profile()
        if not ids:
            raise RuntimeError("vLLM produced no tokens")
        stopped = ids[-1] in set(stop_ids)
        text = (self.tokenizer.decode(ids[:-1] if stopped else ids, skip_special_tokens=False) if chat
                else self.tokenizer.decode(ids, skip_special_tokens=True))
        reused = min(cached or 0, len(ids_in))
        return dict(
            text=text,
            finish_reason="stop" if stopped or len(ids) < arg["max_tokens"] else "length",
            tokens=dict(prompt=len(ids_in), completion=len(ids)),
            generation_timing=dict(
                version="host-token-availability-v1", clock_domain="host_monotonic_ns",
                started_ns=started, first_token_ready_ns=first, last_token_ready_ns=last, stream_end_ns=ended,
                generated_tokens=len(ids), time_to_first_token_ns=first - started,
                subsequent_tokens_ns=last - first,
                scope="Host availability of tokens from the vLLM engine step loop (DELTA outputs), measured from "
                      "generation entry; excludes prompt rendering/tokenization. Tokens that arrive in one step "
                      "share one timestamp.",
            ),
            hook_ns=0,
            profiled=bool(profiling),
            prefix_cache=dict(
                mode=self.request_cache_mode,
                scope="vLLM automatic prefix caching within the owned engine process (one goal); block-granular",
                reused_prefix_tokens=reused,
                new_prefill_tokens=len(ids_in) - reused,
                decode_forward_tokens=len(ids) - 1,
                cached_tokens_for_next_request=None,
            ),
        )
