"""vLLM V1 logits processor that forces a recorded output token sequence (replay).

Loaded into the server with ``--logits-processors studies.paper2.cohort.forcing:ForcedTokens``
(the repository root must be on the server's PYTHONPATH). A request opts in by passing
``vllm_xargs={"forced_tokens": "12,345,678"}``; every other request is untouched.

At decode step k the processor keeps only the logit of forced_tokens[k] for that row, so
greedy or sampled decoding emits exactly the recorded tokens. Requests should also set
``max_tokens = len(forced_tokens)`` and ``ignore_eos = true`` so length matches the record.
The masking cost is part of replay overhead and is measured by the same-precision
live/replay fidelity check, not assumed to be zero.
"""
from __future__ import annotations

from typing import Optional

try:  # vLLM is only present on the inference node.
    import torch
    from vllm.v1.sample.logits_processor import BatchUpdate, LogitsProcessor
except ImportError:  # pragma: no cover - lets the parser below be tested without vLLM
    torch = None
    BatchUpdate = object  # type: ignore[assignment,misc]
    LogitsProcessor = object  # type: ignore[assignment,misc]

XARG = "forced_tokens"


def parse_forced(value) -> Optional[list[int]]:
    """Comma-separated token ids (vllm_xargs only carries str/int/float) -> list, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return [value]
    ids = [int(t) for t in str(value).split(",") if t.strip()]
    if not ids:
        return None
    if any(t < 0 for t in ids):
        raise ValueError("forced token ids must be non-negative")
    return ids


def encode_forced(ids: list[int]) -> str:
    return ",".join(str(int(t)) for t in ids)


class ForcedTokens(LogitsProcessor):  # type: ignore[misc]
    """Per-request forced decoding; state follows vLLM's persistent-batch updates."""

    def __init__(self, vllm_config, device, is_pin_memory: bool) -> None:
        # batch row -> (forced ids, live reference to that request's output token list)
        self.rows: dict[int, tuple[list[int], list[int]]] = {}

    def is_argmax_invariant(self) -> bool:
        return False

    def update_state(self, batch_update: Optional["BatchUpdate"]) -> None:
        if not batch_update:
            return
        for index in batch_update.removed:
            self.rows.pop(index, None)
        for index, params, _prompt_ids, output_ids in batch_update.added:
            forced = parse_forced((params.extra_args or {}).get(XARG)) if params else None
            if forced is None:
                self.rows.pop(index, None)
            else:
                self.rows[index] = (forced, output_ids)
        for a, b, direction in batch_update.moved:
            ra, rb = self.rows.pop(a, None), self.rows.pop(b, None)
            if ra is not None:
                self.rows[b] = ra
            if rb is not None and getattr(direction, "name", "") == "SWAP":
                self.rows[a] = rb

    def apply(self, logits):
        if not self.rows:
            return logits
        rows, cols = [], []
        for index, (forced, output_ids) in self.rows.items():
            step = len(output_ids)
            if step < len(forced):
                rows.append(index)
                cols.append(forced[step])
        if not rows:
            return logits
        r = torch.tensor(rows, dtype=torch.long, device=logits.device)
        c = torch.tensor(cols, dtype=torch.long, device=logits.device)
        keep = logits[r, c].clone()
        logits[r] = float("-inf")
        logits[r, c] = torch.where(torch.isfinite(keep), keep, torch.zeros_like(keep))
        return logits
