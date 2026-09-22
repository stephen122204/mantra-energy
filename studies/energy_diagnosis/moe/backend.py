"""Owned subprocess bridge. RPC timeout terminates and reaps the model process."""
from __future__ import annotations
from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from .control import Expert

CONTROLS = [
    "acknowledged_preparation",
    "completed_transfers",
    "cancel_queued",
    "drain",
    "expert_snapshot",
]


class ProcessBackend:
    def __init__(self, config, *, python, mode, log_path, timeout=600):
        if mode not in {"native", "fixture"}:
            raise ValueError("explicit backend mode required")
        self.config, self.python, self.mode = config, python, mode
        self.log_path, self.timeout = Path(log_path), timeout
        self.process = None
        self.seq = 0
        self.reset_evidence = {}
        self.idle_confirmed = True
        # True when an owned worker was killed while device work was not confirmed
        # idle: the process is reaped (owned work terminated) but its captured
        # energy interval is not a complete goal interval.
        self.termination_forced = False

    @property
    def owned_work_terminated(self):
        # process is cleared only after a verified exit (wait + reader join); a
        # dead process cannot own device work, even when idle was never confirmed.
        return self.process is None

    def capabilities(self):
        # Real capability verification happens in reset before returning goal-start.
        return dict(controls=CONTROLS, mode=self.mode, verification="required_at_reset")

    def reset_goal_state(self):
        if self.process is not None:
            raise RuntimeError("reset requires previous process to be reaped")
        self.termination_forced = False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("ab")
        self.messages = queue.Queue(maxsize=4)
        self.process = subprocess.Popen(
            [self.python, "-m", "studies.energy_diagnosis.moe.worker", self.mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
            start_new_session=(os.name == "posix"),
        )

        def read():
            try:
                while True:
                    line = self.process.stdout.readline(64 * 1024 * 1024 + 1)
                    if not line:
                        self.messages.put(
                            RuntimeError("backend exited before RPC completion")
                        )
                        return
                    if len(line) > 64 * 1024 * 1024:
                        self.messages.put(
                            RuntimeError("backend response exceeds bound")
                        )
                        return
                    self.messages.put(json.loads(line))
            except Exception as exc:
                self.messages.put(exc)

        self.reader_thread = threading.Thread(target=read, daemon=True)
        self.reader_thread.start()
        try:
            result = self._rpc("init", self.config, timeout=self.timeout)
            if set(result["controls"]) != set(CONTROLS) or result["mode"] != self.mode:
                raise RuntimeError("backend capability or mode mismatch")
            self.reset_evidence = dict(
                method="new_owned_process",
                pid=self.process.pid,
                boot=result,
                preceding_process_reaped=True,
            )
        except BaseException:
            self.end_goal()
            raise

    def _rpc(self, method, args=None, timeout=None):
        if self.process is None:
            raise RuntimeError("backend is not active")
        self.seq += 1
        if method in {"init", "generate", "prepare"}:
            self.idle_confirmed = False
        try:
            self.process.stdin.write(
                json.dumps(dict(id=self.seq, method=method, args=args)) + "\n"
            )
            self.process.stdin.flush()
            wait = 10 if timeout is None else timeout
            try:
                result = self.messages.get(timeout=wait)
            except queue.Empty:
                raise RuntimeError(
                    f"backend RPC {method!r} produced no response within {wait}s; owned worker terminated"
                ) from None
            if isinstance(result, Exception):
                raise result
            if result.get("id") != self.seq:
                raise RuntimeError("mismatched backend acknowledgment")
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "backend RPC failed"))
            if method in {"init", "generate", "drain"}:
                self.idle_confirmed = True
            return result["result"]
        except BaseException:
            self.end_goal()
            raise

    def snapshot_experts(self):
        return [Expert(**e) for e in self._rpc("snapshot")]

    def prepare_experts(self, experts, generation, budget):
        return self._rpc(
            "prepare",
            dict(
                experts=[asdict(e) for e in experts],
                generation=generation,
                budget=budget,
            ),
        )

    def cancel_pending_preparation(self, generation):
        return self._rpc("cancel", dict(generation=generation))

    def drain_owned_work(self, timeout_seconds):
        return self._rpc(
            "drain", dict(timeout=timeout_seconds), timeout=timeout_seconds + 2
        )

    def drain_transfers(self):
        result = self._rpc("transfers")
        return result["records"], result["dropped"]

    def drain_demands(self):
        return self._rpc("demands")

    def generate(self, prompt, timeout, max_tokens):
        return self._rpc(
            "generate", dict(prompt=prompt, max_tokens=max_tokens), timeout=timeout
        )

    def end_goal(self):
        p = self.process
        if p is None:
            return
        if p.poll() is None and not self.idle_confirmed:
            self.termination_forced = True
        # Explicitly own the whole process tree. Native threads can otherwise outlive RPC failure.
        try:
            if os.name == "posix":
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                import psutil

                parent = psutil.Process(p.pid)
                descendants = parent.children(recursive=True)
                for child in reversed(descendants):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                if p.poll() is None:
                    p.kill()
                _, alive = psutil.wait_procs(descendants, timeout=10)
                if alive:
                    raise RuntimeError("backend child termination unverified")
            # Releasing a large pinned host-memory model can delay Linux process
            # exit after SIGKILL. Keep a finite bound, but allow the observed
            # multi-gigabyte teardown to finish before rejecting ownership.
            p.wait(timeout=60)
            if self.reader_thread is not threading.current_thread():
                self.reader_thread.join(timeout=2)
            if self.reader_thread.is_alive():
                raise RuntimeError("backend output reader did not terminate")
        finally:
            if p.poll() is not None:
                for handle in (p.stdin, p.stdout, self.log):
                    handle.close()
                self.process = None


class BackendAdapter:
    def __init__(self, backend, max_tokens=512):
        self.backend = backend
        self.model_config = {"request_timeout_seconds": 120, "max_tokens": max_tokens}

    def call(self, prompt, temperature):
        if temperature != 0:
            raise ValueError("this adapter requires greedy generation")
        started = time.monotonic_ns()
        try:
            result = self.backend.generate(
                prompt,
                self.model_config["request_timeout_seconds"],
                self.model_config["max_tokens"],
            )
            return dict(
                status="ok",
                content=result["text"],
                tokens=result["tokens"],
                token_provenance="tokenizer"
                if self.backend.mode == "native"
                else "estimated",
                backend=result,
            )
        except Exception as exc:
            return dict(
                status="error",
                error=str(exc),
                tokens={},
                token_provenance="unknown",
                elapsed_ns=time.monotonic_ns() - started,
                owned_work_terminated=self.backend.owned_work_terminated,
            )
