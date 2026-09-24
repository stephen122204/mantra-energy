"""Host token-availability timing through the Transformers generation streamer.

No token values are retained. Transformers hands the streamer CPU tensors,
so timestamps describe host availability, not CUDA kernel durations. The same
streamer is installed for every native policy; its synchronization overhead is
part of the measured execution and must not be assumed to be free.
"""
import time


class TokenTiming:
    def __init__(self, clock=time.monotonic_ns):
        self.clock = clock
        self.started_ns = clock()
        self.prompt_seen = False
        self.first_ns = self.last_ns = self.ended_ns = None
        self.generated = 0

    def put(self, value):
        if self.ended_ns is not None:
            raise RuntimeError("token after stream end")
        shape = tuple(value.shape)
        if not self.prompt_seen:
            if len(shape) != 2 or shape[0] != 1 or shape[1] < 1:
                raise RuntimeError("expected initial batch-one prompt")
            self.prompt_seen = True
            return
        if shape != (1,):
            raise RuntimeError("expected one generated token per streamer callback")
        stamp = self.clock()
        if stamp < (self.last_ns if self.last_ns is not None else self.started_ns):
            raise RuntimeError("token clock went backwards")
        if self.first_ns is None:
            self.first_ns = stamp
        self.last_ns = stamp
        self.generated += 1

    def end(self):
        if self.ended_ns is not None:
            raise RuntimeError("duplicate stream end")
        self.ended_ns = self.clock()

    def result(self, expected_tokens):
        if (not self.prompt_seen or self.ended_ns is None or self.generated < 1
                or type(expected_tokens) is not int or self.generated != expected_tokens):
            raise RuntimeError("incomplete or inconsistent token timing stream")
        if self.ended_ns < self.last_ns:
            raise RuntimeError("stream end precedes token availability")
        return dict(
            version="host-token-availability-v1", clock_domain="host_monotonic_ns",
            started_ns=self.started_ns, first_token_ready_ns=self.first_ns,
            last_token_ready_ns=self.last_ns, stream_end_ns=self.ended_ns,
            generated_tokens=self.generated, time_to_first_token_ns=self.first_ns - self.started_ns,
            subsequent_tokens_ns=self.last_ns - self.first_ns,
            scope="Host availability including stop tokens, measured from generation entry; excludes prompt rendering/tokenization. "
                  "Not GPU kernel time or phase-specific energy. Streamer CPU synchronization is included in all native arms.",
        )
