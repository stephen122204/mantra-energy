"""Exact token-prefix reuse within one owned model process/goal.

This owns a mutable Transformers cache; it never shares it across goals or
pretends that a failed or unsupported cache operation succeeded.
"""


def validate_prefix_configuration(config):
    """Accept only the pinned full-attention, fixed-position cache semantics.

    Exact tokens alone are insufficient when a longer request changes rotary
    frequencies or a sliding cache has discarded earlier positions.
    """
    if config.get("rope_scaling") is not None or config.get("rope_parameters") is not None:
        raise ValueError("prefix reuse requires the pinned fixed rotary configuration")
    if config.get("use_sliding_window", False) or config.get("sliding_window") is not None:
        raise ValueError("prefix reuse requires full attention without a sliding window")


class GenerationWork:
    """Distinguish the first forward from decode even for a one-token suffix."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.forward_calls = self.prefill_tokens = self.decode_tokens = 0
        self.phase = "unobserved"

    def observe(self, tokens):
        if type(tokens) is not int or tokens < 1:
            raise RuntimeError("invalid observed forward length")
        self.forward_calls += 1
        self.phase = "prefill" if self.forward_calls == 1 else "decode"
        if self.phase == "prefill":
            self.prefill_tokens += tokens
        else:
            self.decode_tokens += tokens


class RequestPrefixCache:
    def __init__(self):
        self.clear()

    def clear(self):
        self.cache = None
        self.tokens = ()
        self.pending = None

    def prepare(self, prompt_tokens):
        if self.pending is not None:
            raise RuntimeError("previous prefix-cache request is unfinished")
        prompt = tuple(prompt_tokens)
        if not prompt or any(type(t) is not int or t < 0 for t in prompt):
            raise ValueError("nonempty integer token sequence required")
        reused = 0
        try:
            if self.cache is not None:
                size = self.cache.get_seq_length()
                if size != len(self.tokens):
                    raise RuntimeError("cache length changed outside its owner")
                # Keep one prompt token to compute the next-token distribution,
                # even when the complete prompt is identical to cached input.
                for before, after in zip(self.tokens, prompt[:-1]):
                    if before != after:
                        break
                    reused += 1
                if reused:
                    self.cache.crop(reused)
                    if self.cache.get_seq_length() != reused:
                        raise RuntimeError("cache crop did not apply")
                else:
                    self.cache = None
            self.tokens = self.tokens[:reused]
            self.pending = prompt
            return dict(
                past_key_values=self.cache,
                reused_prefix_tokens=reused,
                new_prefill_tokens=len(prompt) - reused,
            )
        except BaseException:
            self.clear()
            raise

    def finish(self, full_sequence, cache):
        try:
            if self.pending is None:
                raise RuntimeError("no pending prefix-cache request")
            sequence = tuple(full_sequence)
            if sequence[:len(self.pending)] != self.pending:
                raise RuntimeError("generation did not preserve the supplied prompt")
            if len(sequence) <= len(self.pending):
                raise RuntimeError("generation produced no continuation")
            if not callable(getattr(cache, "crop", None)):
                raise RuntimeError("backend did not return a reusable cache")
            size = cache.get_seq_length()
            # Greedy HF generation does not forward the last generated token.
            # Reject a cache with a different token-accounting contract.
            if size != len(sequence) - 1:
                raise RuntimeError("returned cache length differs from forwarded tokens")
            self.cache, self.tokens, self.pending = cache, sequence[:size], None
            return size
        except BaseException:
            self.clear()
            raise
