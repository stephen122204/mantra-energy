"""Opt-in capture of provider HTTP entity bytes, without headers or requests."""

import hashlib
from pathlib import Path
import time


class ProviderResponseCapture:
    """Tee decoded body bytes before line/JSON parsing; retain partial failures.

    These are the bytes exposed by requests after HTTP transfer/content decoding,
    not TCP framing or compressed wire bytes. EOF and provider completion are
    separate facts. Capture I/O and draining remain inside the adapter call.
    """

    def __init__(self, path, deadline_ns):
        self.path = Path(path)
        self.file = self.path.open("xb")
        self.deadline_ns = deadline_ns
        self.sha256 = hashlib.sha256()
        self.byte_count = 0
        self.body_complete = False
        self.chunks = iter(())

    def attach(self, response):
        self.response = response
        self.chunks = self._chunks(response)

    def _chunks(self, response):
        for chunk in response.iter_content(chunk_size=512):
            # Save received bytes even when this read exhausted the deadline.
            self.file.write(chunk)
            self.sha256.update(chunk)
            self.byte_count += len(chunk)
            if time.perf_counter_ns() > self.deadline_ns:
                raise TimeoutError("provider response capture exceeded request deadline")
            yield chunk
        self.body_complete = True

    def lines(self):
        # Same byte-line splitting as requests.Response.iter_lines, including
        # partial lines across chunks. The saved body keeps original separators.
        pending = None
        for chunk in self.chunks:
            if pending is not None:
                chunk = pending + chunk
            lines = chunk.splitlines()
            if lines and lines[-1] and chunk and lines[-1][-1] == chunk[-1]:
                pending = lines.pop()
            else:
                pending = None
            yield from lines
        if pending is not None:
            yield pending

    def finish(self):
        # Preserve all body bytes, including bytes after the protocol's done
        # marker, without feeding those trailing bytes into the existing parser.
        for _ in self.chunks:
            pass

    def json(self):
        self.finish()
        self.file.flush()
        # iter_content consumed the transport once. Populate Requests' content
        # cache only when it was not already filled by a non-streaming request,
        # then let the original response apply its encoding/JSON error policy.
        if self.response._content is False:
            self.response._content = self.path.read_bytes()
            self.response._content_consumed = True
        return self.response.json()

    def close(self):
        self.file.close()
        return dict(body_complete=self.body_complete, bytes_received=self.byte_count,
                    sha256=self.sha256.hexdigest())
