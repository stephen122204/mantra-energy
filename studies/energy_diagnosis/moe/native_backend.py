"""Pinned MoE-Infinity bridge, imported only in the GPU worker process."""
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

from .backend import CONTROLS
from .control import Expert

BACKEND_COMMIT = "6da092fc98e7246bfa1b2f9b2a480524b8697a7e"
MODEL_REVISION = "0d7cf23991f47feeb3a57ecb4c9cee8ea4a17bfe"


class NativeDevice:
    def __init__(self, config):
        import torch
        from transformers import AutoTokenizer
        from moe_infinity import MoE

        self.torch = torch
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
            prefetch=False,
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
        if executor.prefetcher is not None or executor.precision_policy is not None:
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
        self.original_dispatch = self.model.engine.expert_executor.dispatch_local

        def observed_dispatch(layer_id, hidden, mask, weights, *args, **kwargs):
            begin = time.monotonic_ns()
            counts = mask.detach().sum(dim=0).cpu().tolist()
            for expert, tokens in enumerate(counts):
                if not tokens:
                    continue
                tensor = int(self.mapping[(int(layer_id), expert)])
                node, size, device = self.native.alems_expert_info(tensor)
                phase = "prefill" if mask.shape[0] > 1 else "decode"
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
        self.model.engine.expert_executor.dispatch_local = observed_dispatch
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
        return [
            asdict(
                Expert(
                    layer,
                    expert,
                    int(tensor),
                    *self.native.alems_expert_info(int(tensor)),
                )
            )
            for (layer, expert), tensor in sorted(self.mapping.items())
        ]

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
        prompt = self.tokenizer.apply_chat_template(
            [dict(role="user", content=arg["prompt"])],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer.encode(prompt, return_tensors="pt").to("cuda:0")
        if inputs.shape[1] + arg["max_tokens"] > self.max_context:
            raise ValueError("prompt plus output exceeds fixed context budget")
        with self.torch.inference_mode():
            result = self.model.generate(
                inputs,
                do_sample=False,
                max_new_tokens=arg["max_tokens"],
                pad_token_id=self.tokenizer.eos_token_id,
            )
        self.torch.cuda.synchronize()
        output = result[0, inputs.shape[1] :]
        return dict(
            text=self.tokenizer.decode(output, skip_special_tokens=True),
            tokens=dict(prompt=int(inputs.shape[1]), completion=int(output.shape[0])),
            hook_ns=self.hook_ns - before,
        )
