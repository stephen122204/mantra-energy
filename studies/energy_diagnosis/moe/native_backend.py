"""Pinned MoE-Infinity bridge, imported only in the GPU worker process."""
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time

from .backend import CONTROLS
from .control import Expert
from .prefix import GenerationWork, RequestPrefixCache, validate_prefix_configuration
from .token_timing import TokenTiming

DIAGNOSTIC_KEYS = {"profile_calls", "profile_dir", "observation", "keep_trace"}

BACKEND_COMMIT = "6da092fc98e7246bfa1b2f9b2a480524b8697a7e"
MODEL_REVISION = "0d7cf23991f47feeb3a57ecb4c9cee8ea4a17bfe"


class NativeDevice:
    def __init__(self, config):
        import torch
        from transformers import AutoTokenizer
        from moe_infinity import MoE

        if config.get("reference_arithmetic") != "transformers-5.3-grouped-bf16-v1":
            raise ValueError("explicit qualified reference_arithmetic is required")
        if importlib.metadata.version("transformers") != "5.3.0":
            raise ValueError("reference arithmetic requires Transformers 5.3.0")
        os.environ["ALEMS_QWEN_REFERENCE_MATH"] = "1"
        if config.get("reference_experts_implementation") != "grouped_mm":
            raise ValueError("explicit grouped_mm reference implementation is required")
        self.torch = torch
        self.request_cache_mode = config.get("request_prefix_cache", "disabled")
        if self.request_cache_mode not in {"disabled", "exact_prefix"}:
            raise ValueError("request_prefix_cache must be disabled or exact_prefix")
        self.prefix_cache = RequestPrefixCache()
        self.request_work = GenerationWork()
        if torch.cuda.device_count() != 1:
            raise ValueError(
                "expose exactly one allocated GPU through CUDA_VISIBLE_DEVICES"
            )
        if (
            config.get("backend_commit") != BACKEND_COMMIT
            or config.get("model_revision") != MODEL_REVISION
        ):
            raise ValueError(
                "model and backend revision must match the pinned launch manifest"
            )
        path = Path(config["model_path"]).resolve(strict=True)
        manifest = json.loads((path / "alems-weights.json").read_text())
        if manifest["revision"] != MODEL_REVISION:
            raise ValueError("wrong checkpoint revision")
        for name, digest in manifest["files"].items():
            p = path / name
            from .prepare import file_sha

            if p.resolve().parent != path or file_sha(p) != digest:
                raise ValueError(f"checkpoint bytes changed: {name}")
        required = {
            p.name
            for p in path.iterdir()
            if p.suffix in {".json", ".safetensors", ".jinja"}
            and p.name != "alems-weights.json"
        }
        if not required <= manifest["files"].keys():
            raise ValueError("unmanifested model/tokenizer files")
        from .prepare import verify_build

        build = verify_build(Path(config["build_manifest"]))
        model_config = json.loads((path / "config.json").read_text())
        if self.request_cache_mode == "exact_prefix":
            validate_prefix_configuration(model_config)
        if (
            model_config.get("model_type") != "qwen3_moe"
            or model_config.get("num_experts") != 128
            or model_config.get("num_experts_per_tok") != 8
        ):
            raise ValueError("unexpected Qwen architecture/routing")
        if (
            model_config.get("dtype", model_config.get("torch_dtype")) != "bfloat16"
            or "quantization_config" in model_config
        ):
            raise ValueError("only unquantized bfloat16 checkpoint is supported")
        ratio = config["device_memory_ratio"]
        if not isinstance(ratio, (float, int)) or not 0 < ratio < 1:
            raise ValueError("explicit GPU expert memory ratio required")
        self.applied = dict(
            offload_path=config["offload_path"],
            device_memory_ratio=ratio,
            use_native_engine=False,
            # builtin arm only: MoE-Infinity's own activation-aware prefetcher.
            prefetch=bool(config.get("builtin_prefetch", False)),
            speculative_prefetch=False,
            speculative_prefetch_overlap=False,
            enable_attention_offload=False,
            gpu_only_expert_routing=False,
            num_threads=1,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            path, local_files_only=True, trust_remote_code=False
        )
        self.model = MoE(str(path), self.applied)
        self.native = self.model.engine.archer_engine
        if (
            not hasattr(self.native, "alems_transfer_api_version")
            or self.native.alems_transfer_api_version() != 1
        ):
            raise RuntimeError(
                "required native transfer patch is not loaded; no fallback"
            )
        actual = self.model.engine.archer_config
        for key, value in self.applied.items():
            if getattr(actual, key) != value:
                raise RuntimeError(f"backend changed requested {key}")
        executor = self.model.engine.expert_executor
        if executor.precision_policy is not None or (
            executor.prefetcher is not None and not self.applied["prefetch"]
        ):
            raise RuntimeError("uncontrolled prefetch or precision policy is active")
        self.mapping = dict(self.model.engine.expert_tensor_map)
        if not self.mapping:
            raise RuntimeError("backend did not expose expert tensors")
        self.node_to_key = {}
        for key, tensor in self.mapping.items():
            node, size, device = self.native.alems_expert_info(int(tensor))
            if node in self.node_to_key:
                raise RuntimeError(
                    "multiple expert identities share an unhandled native node"
                )
            self.node_to_key[node] = key
        self.demands, self.dropped_demands = {}, 0
        self.generation = 1
        self.max_context = config.get("max_context", 4096)
        # Diagnostic-only switches; a config carrying them is never campaign evidence.
        self.diagnostic = config.get("diagnostic")
        if self.diagnostic is not None:
            if not isinstance(self.diagnostic, dict) or not set(self.diagnostic) <= DIAGNOSTIC_KEYS \
                    or self.diagnostic.get("observation", "full") not in {"full", "off"}:
                raise ValueError("invalid diagnostic configuration")
        self.call_index = 0
        self.original_dispatch = self.model.engine.expert_executor.dispatch_local

        def observed_dispatch(layer_id, hidden, mask, weights, *args, **kwargs):
            begin = time.monotonic_ns()
            counts = mask.detach().sum(dim=0).cpu().tolist()
            for expert, tokens in enumerate(counts):
                if not tokens:
                    continue
                tensor = int(self.mapping[(int(layer_id), expert)])
                node, size, device = self.native.alems_expert_info(tensor)
                phase = self.request_work.phase
                if phase not in {"prefill", "decode"}:
                    raise RuntimeError("expert dispatch without an observed model forward")
                key = (int(layer_id), expert, phase)
                observed = time.monotonic_ns()
                if key not in self.demands and len(self.demands) >= 65536:
                    self.dropped_demands += 1
                    continue
                event = self.demands.setdefault(
                    key,
                    dict(
                        layer=int(layer_id),
                        expert=expert,
                        tensor=tensor,
                        node=node,
                        bytes=size,
                        tokens=0,
                        dispatches=0,
                        resident_dispatches=0,
                        first_dispatch_resident=device.startswith("cuda"),
                        phase=phase,
                        first_observed_ns=observed,
                        observation_scope="request-layer-expert-phase aggregate",
                    ),
                )
                event["tokens"] += int(tokens)
                event["dispatches"] += 1
                event["resident_dispatches"] += int(device.startswith("cuda"))
                event["last_observed_ns"] = observed
            self.hook_ns += time.monotonic_ns() - begin
            return self.original_dispatch(
                layer_id, hidden, mask, weights, *args, **kwargs
            )

        self.hook_ns = 0
        if (self.diagnostic or {}).get("observation", "full") == "full":
            self.model.engine.expert_executor.dispatch_local = observed_dispatch

        def observe_forward(module, args, kwargs):
            started = time.monotonic_ns()
            ids = kwargs.get("input_ids", args[0] if args else None)
            if ids is None or len(ids.shape) != 2 or ids.shape[0] != 1:
                raise RuntimeError("expected batch-one token input for generation accounting")
            self.request_work.observe(int(ids.shape[1]))
            self.hook_ns += time.monotonic_ns() - started

        self.forward_hook = self.model.model.register_forward_pre_hook(
            observe_forward, with_kwargs=True
        )
        torch.cuda.synchronize()
        clock_before = time.monotonic_ns()
        native_ns = self.native.alems_clock_ns()
        clock_after = time.monotonic_ns()
        self.boot = dict(
            build=build,
            clock_alignment=dict(
                native_ns=native_ns,
                host_lower_ns=clock_before,
                host_upper_ns=clock_after,
                uncertainty_ns=clock_after - clock_before,
            ),
            controls=CONTROLS,
            mode="native",
            reference_arithmetic=config["reference_arithmetic"],
            diagnostic=self.diagnostic,
            request_prefix_cache=self.request_cache_mode,
            applied_config=self.applied,
            backend_commit=BACKEND_COMMIT,
            model_revision=MODEL_REVISION,
            chat_template_sha256=hashlib.sha256(
                self.tokenizer.chat_template.encode()
            ).hexdigest(),
            versions={
                n: importlib.metadata.version(n)
                for n in ("torch", "transformers", "accelerate")
            },
            device=torch.cuda.get_device_name(0),
            cuda=torch.version.cuda,
            expert_count=len(self.mapping),
            expert_cache_limit_bytes=self.native.get_expert_cache_limit(0),
            expert_occupancy_bytes=self.native.get_expert_occupancy_bytes(),
            measurement_limits=[
                "transfer duration is a host bracket including admission/eviction/copy, not CUDA kernel time",
                "demand observations are pre-dispatch residency, not byte-level demand-copy attribution",
                "Python routing observation overhead is included; report hook_ns separately",
            ],
        )

    def snapshot(self, _):
        if self.native.get_inflight_prefetch_bytes():
            raise RuntimeError("snapshot requires settled transfers")
        rows = []
        for (layer, expert), tensor in sorted(self.mapping.items()):
            node, nbytes, device = self.native.alems_expert_info(int(tensor))
            # The native API returns scalar IDs/bytes and a device string.
            # Read live placement every time, without constructing then deeply
            # copying a dataclass for each of thousands of experts.
            rows.append(dict(layer=layer, expert=expert, tensor=int(tensor),
                             node=node, nbytes=nbytes, device=device))
        return rows

    def prepare(self, arg):
        experts = [Expert(**e) for e in arg["experts"]]
        for e in experts:
            if self.mapping.get(e.key) != e.tensor:
                raise RuntimeError("expert/tensor mapping mismatch")
        self.generation = arg["generation"]
        ack = self.native.schedule_prefetch_tensors(
            [e.tensor for e in experts], 1, arg["generation"], -1, arg["budget"]
        )
        return dict(
            accepted_nodes=list(ack.accepted_tensor_ids),
            accepted_bytes=ack.accepted_bytes,
            rejected_bytes=ack.rejected_bytes,
            inflight_bytes=ack.inflight_bytes,
        )

    def cancel(self, arg):
        return self.native.cancel_prefetch_generation(arg["generation"], -1, [])

    def drain(self, arg):
        deadline = time.monotonic() + arg["timeout"]
        while self.native.get_inflight_prefetch_bytes():
            if time.monotonic() >= deadline:
                raise TimeoutError("native transfers did not drain")
            time.sleep(0.001)
        self.torch.cuda.synchronize()
        return {"inflight_bytes": 0}

    def transfers(self, _):
        records = []
        for s in self.native.drain_prefetch_samples():
            layer, expert = self.node_to_key[int(s.tensor_id)]
            fields = (
                "generation",
                "bytes",
                "transferred_bytes",
                "enqueue_ns",
                "start_ns",
                "end_ns",
                "queue_wait_ns",
                "transfer_ns",
                "source_device",
                "outcome",
            )
            records.append(
                dict(
                    layer=layer,
                    expert=expert,
                    node=int(s.tensor_id),
                    tensor=int(self.mapping[(layer, expert)]),
                    native_clock_domain="std::chrono::steady_clock",
                    **{k: getattr(s, k) for k in fields},
                )
            )
        for row in self.native.alems_drain_placements():
            layer, expert = self.node_to_key.get(int(row.node), (None, None))
            records.append(
                dict(
                    kind="placement",
                    generation=self.generation,
                    layer=layer,
                    expert=expert,
                    node=int(row.node),
                    logical_bytes=row.bytes,
                    start_ns=row.start_ns,
                    return_ns=row.return_ns,
                    source=row.source,
                    destination=row.destination,
                    backend_on_demand=row.on_demand,
                    completed_at_return=row.completed_at_return,
                    completion_observed_upper_ns=time.monotonic_ns(),
                    native_clock_domain="std::chrono::steady_clock",
                    action="eviction"
                    if row.source.startswith("cuda")
                    and not row.destination.startswith("cuda")
                    else "placement",
                )
            )
        return dict(
            records=records,
            dropped=self.native.get_dropped_prefetch_samples()
            + self.native.alems_dropped_placements(),
        )

    def demands_rpc(self, _):
        if self.dropped_demands:
            raise RuntimeError("expert demand event buffer overflow")
        rows, self.demands = list(self.demands.values()), {}
        return rows

    def generate(self, arg):
        before = self.hook_ns
        chat = "messages" in arg
        if chat:
            # chat-tools-v1: the model's own template renders history and tools.
            prompt = self.tokenizer.apply_chat_template(
                arg["messages"], tools=arg["tools"], tokenize=False, add_generation_prompt=True,
            )
        else:
            prompt = self.tokenizer.apply_chat_template(
                [dict(role="user", content=arg["prompt"])],
                tokenize=False,
                add_generation_prompt=True,
            )
        inputs = self.tokenizer.encode(prompt, return_tensors="pt").to("cuda:0")
        if inputs.shape[1] + arg["max_tokens"] > self.max_context:
            if chat:
                # A budget outcome, not a backend failure: nothing was generated.
                return dict(text="", finish_reason="context_exhausted", hook_ns=0,
                            tokens=dict(prompt=int(inputs.shape[1]), completion=0))
            raise ValueError("prompt plus output exceeds fixed context budget")
        sampling = arg.get("sampling") or dict(mode="greedy")
        if sampling["mode"] == "greedy":
            decode = dict(do_sample=False)
        elif sampling["mode"] == "sampled":
            self.torch.manual_seed(sampling["seed"])
            decode = dict(do_sample=True, temperature=sampling["temperature"], top_p=sampling["top_p"],
                          top_k=sampling["top_k"], min_p=sampling["min_p"])
        else:
            raise ValueError("unknown decoding mode")
        self.request_work.reset()
        reused = retained = 0
        options = {}
        use_prefix = self.request_cache_mode == "exact_prefix"
        if use_prefix:
            prepared = self.prefix_cache.prepare(inputs[0].tolist())
            reused = prepared["reused_prefix_tokens"]
            options = dict(
                past_key_values=prepared["past_key_values"],
                return_dict_in_generate=True,
                use_cache=True,
            )
        # Native expert workers update output tensors from separate threads.
        # InferenceMode is thread-local and makes those cross-thread writes fail.
        # no_grad preserves gradient-free generation with ordinary tensors.
        index = getattr(self, "call_index", 0)
        self.call_index = index + 1
        diagnostic = getattr(self, "diagnostic", None)
        profiler = None
        if diagnostic and index in diagnostic.get("profile_calls", []):
            from .diagnostic_profile import CallProfiler
            profiler = CallProfiler(self.torch, diagnostic["profile_dir"], index,
                                    keep_trace=bool(diagnostic.get("keep_trace")))
        timing = TokenTiming(on_first_token=profiler.mark_first_token if profiler else None)
        try:
            with self.torch.no_grad(), (profiler if profiler else contextlib.nullcontext()):
                result = self.model.generate(
                    inputs,
                    attention_mask=self.torch.ones_like(inputs),
                    max_new_tokens=arg["max_tokens"],
                    **decode,
                    pad_token_id=self.tokenizer.eos_token_id,
                    streamer=timing,
                    **options,
                )
            self.torch.cuda.synchronize()
            sequences = result.sequences if use_prefix else result
            output = sequences[0, inputs.shape[1] :]
            if self.request_work.prefill_tokens != inputs.shape[1] - reused:
                raise RuntimeError("observed prefill work differs from declared prefix reuse")
            if self.request_work.decode_tokens != output.shape[0] - 1:
                raise RuntimeError("observed decode work differs from generated tokens")
            if use_prefix:
                retained = self.prefix_cache.finish(sequences[0].tolist(), result.past_key_values)
        except BaseException:
            self.prefix_cache.clear()
            raise
        ids = output.tolist()
        stop_ids = {self.tokenizer.eos_token_id}
        if chat:
            stop_ids |= {i for i in self.tokenizer.convert_tokens_to_ids(["<|im_end|>", "<|endoftext|>"])
                         if isinstance(i, int) and i != self.tokenizer.unk_token_id}
        stopped = bool(ids) and ids[-1] in stop_ids
        if chat:
            # Keep tool-call markup; drop only the terminating token.
            text = self.tokenizer.decode(ids[:-1] if stopped else ids, skip_special_tokens=False)
        else:
            text = self.tokenizer.decode(output, skip_special_tokens=True)
        return dict(
            text=text,
            finish_reason="stop" if stopped or len(ids) < arg["max_tokens"] else "length",
            tokens=dict(prompt=int(inputs.shape[1]), completion=int(output.shape[0])),
            generation_timing=timing.result(len(ids)),
            hook_ns=self.hook_ns - before,
            prefix_cache=dict(
                mode=self.request_cache_mode,
                scope="within owned goal only; no cross-goal cache",
                reused_prefix_tokens=reused,
                new_prefill_tokens=self.request_work.prefill_tokens,
                decode_forward_tokens=self.request_work.decode_tokens,
                cached_tokens_for_next_request=retained,
            ),
        )
