"""One persistent vLLM OpenAI-compatible server per precision configuration.

A ``ServerConfig`` names everything that defines the treatment (checkpoint + revision,
weight/activation/KV precision, quantizer, memory budget, cache settings) and hashes to a
config id that every cohort record carries. ``VllmServer`` starts the server in its own
process group, waits for /health, checks the served model id, extracts the KV-cache capacity
and quantization/kernel lines from the startup log, and stops the whole process group.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ServerConfig:
    name: str                      # e.g. "devstral-w4a16"
    model: str                     # HF repo id or local path
    revision: str                  # exact commit of the checkpoint
    weight_precision: str          # bf16 | int8 | int4 | fp8
    activation_precision: str      # bf16 | int8 | fp8
    kv_precision: str = "bf16"     # vLLM --kv-cache-dtype auto keeps the model dtype
    quantizer: str = "none"        # e.g. "llm-compressor GPTQ W4A16 g128 asym actorder=weight"
    tokenizer_mode: str = "mistral"
    max_model_len: int = 65536
    gpu_memory_utilization: float = 0.90   # equal total-memory budget across arms
    num_gpu_blocks_override: Optional[int] = None  # set only for the equal-KV-capacity control
    max_num_seqs: int = 64
    enable_prefix_caching: bool = True
    extra_args: tuple = ()
    seed: int = 0

    def config_id(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return f"{self.name}-{hashlib.sha256(blob).hexdigest()[:12]}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["config_id"] = self.config_id()
        return d


def vllm_command(cfg: ServerConfig, *, port: int, python: str = sys.executable,
                 replay_forcing: bool = True) -> list[str]:
    cmd = [python, "-m", "vllm.entrypoints.openai.api_server", "--model", cfg.model]
    if not Path(cfg.model).exists():  # a local snapshot is already pinned by its manifest
        cmd += ["--revision", cfg.revision]
    cmd += ["--served-model-name", cfg.name,
           "--host", "127.0.0.1", "--port", str(port),
           "--tokenizer-mode", cfg.tokenizer_mode,
           "--max-model-len", str(cfg.max_model_len),
           "--gpu-memory-utilization", str(cfg.gpu_memory_utilization),
           "--max-num-seqs", str(cfg.max_num_seqs),
           "--kv-cache-dtype", "auto" if cfg.kv_precision in ("bf16", "auto") else cfg.kv_precision,
           "--seed", str(cfg.seed),
           "--enable-prompt-tokens-details",
           "--disable-log-requests"]
    cmd.append("--enable-prefix-caching" if cfg.enable_prefix_caching else "--no-enable-prefix-caching")
    if cfg.num_gpu_blocks_override:
        cmd += ["--num-gpu-blocks-override", str(cfg.num_gpu_blocks_override)]
    if replay_forcing:
        cmd += ["--logits-processors", "studies.paper2.cohort.forcing:ForcedTokens"]
    cmd += list(cfg.extra_args)
    return cmd


_KV_PATTERNS = (
    re.compile(r"GPU KV cache size:\s*([\d,]+)\s*tokens"),
    re.compile(r"# GPU blocks:\s*(\d+)"),
    re.compile(r"Maximum concurrency for ([\d,]+) tokens per request:\s*([\d.]+)x"),
)
_KERNEL_HINT = re.compile(r"(?i)(marlin|machete|cutlass|scaled_mm|compressed.tensors|gptq|w8a8|w4a16|fp8|"
                          r"quantiz|kernel|attention backend|using .* backend)")


def parse_startup_log(text: str) -> dict:
    out: dict = {"kernel_lines": []}
    for line in text.splitlines():
        m = _KV_PATTERNS[0].search(line)
        if m:
            out["kv_cache_tokens"] = int(m.group(1).replace(",", ""))
        m = _KV_PATTERNS[1].search(line)
        if m:
            out["gpu_blocks"] = int(m.group(1))
        m = _KV_PATTERNS[2].search(line)
        if m:
            out["max_concurrency"] = {"tokens_per_request": int(m.group(1).replace(",", "")),
                                      "concurrency": float(m.group(2))}
        if _KERNEL_HINT.search(line) and len(out["kernel_lines"]) < 60:
            out["kernel_lines"].append(line.strip()[:300])
    return out


def nvml_index(uuid: str) -> int:
    import pynvml
    pynvml.nvmlInit()
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            u = pynvml.nvmlDeviceGetUUID(pynvml.nvmlDeviceGetHandleByIndex(i))
            if (u.decode() if isinstance(u, bytes) else u) == uuid:
                return i
    finally:
        pynvml.nvmlShutdown()
    raise ValueError(f"GPU {uuid} not found")


def checkpoint_quantization(model: str) -> dict:
    """What the checkpoint itself declares (dtype + quantization_config, e.g. weights/input_activations/kv)."""
    p = Path(model) / "config.json"
    if not p.exists():
        return {"config": "not local"}
    c = json.loads(p.read_text())
    return {"torch_dtype": c.get("torch_dtype") or (c.get("text_config") or {}).get("torch_dtype"),
            "quantization_config": c.get("quantization_config"), "config_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


@dataclass
class VllmServer:
    cfg: ServerConfig
    port: int
    log_path: Path
    gpu_uuid: Optional[str] = None
    python: str = sys.executable
    proc: Optional[subprocess.Popen] = None
    started: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_s: float = 1800) -> dict:
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
        if self.gpu_uuid:  # vLLM 0.10.2 parses CUDA_VISIBLE_DEVICES as integers: pass the NVML index of the UUID
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"  # CUDA ordinals match NVML (PCI bus) order
            env["CUDA_VISIBLE_DEVICES"] = str(nvml_index(self.gpu_uuid))
        env.setdefault("VLLM_USE_V1", "1")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "w")
        t0 = time.time()
        self.proc = subprocess.Popen(vllm_command(self.cfg, port=self.port, python=self.python),
                                     stdout=log, stderr=subprocess.STDOUT, env=env, cwd=REPO_ROOT,
                                     start_new_session=True)
        try:
            while time.time() - t0 < timeout_s:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"vLLM exited with {self.proc.returncode}; see {self.log_path}")
                try:
                    with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as r:
                        if r.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(2)
            else:
                raise TimeoutError("vLLM did not become healthy")
            with urllib.request.urlopen(f"{self.base_url}/v1/models", timeout=10) as r:
                models = json.loads(r.read())
            served = [m["id"] for m in models.get("data", [])]
            if served != [self.cfg.name]:
                raise RuntimeError(f"served models {served} != [{self.cfg.name}]")
        except BaseException:
            self.stop()
            raise
        self.started = {"load_s": round(time.time() - t0, 1), "pid": self.proc.pid,
                        "served": served, "checkpoint": checkpoint_quantization(self.cfg.model),
                        "cuda_visible_devices": env.get("CUDA_VISIBLE_DEVICES"), "gpu_uuid": self.gpu_uuid,
                        **parse_startup_log(self.log_path.read_text(errors="replace"))}
        return self.started

    def stop(self, grace_s: float = 60) -> Optional[int]:
        if not self.proc or self.proc.poll() is not None:
            return self.proc.returncode if self.proc else None
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=30)
        except ProcessLookupError:
            pass
        return self.proc.returncode
