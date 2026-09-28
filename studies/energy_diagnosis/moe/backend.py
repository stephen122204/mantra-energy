"""Owned subprocess bridge. RPC timeout terminates and reaps the model process."""
from __future__ import annotations
from contextlib import contextmanager
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
# Stock engines (no expert placement API) declare no expert controls. The lifecycle
# then issues no expert RPCs and admits only the demand (no-preparation) policy.
STOCK_ENGINES = frozenset({"vllm", "llamacpp"})


def expected_controls(config):
    return [] if (config or {}).get("engine") in STOCK_ENGINES else list(CONTROLS)


class ProcessBackend:
    def __init__(self, config, *, python, mode, log_path, timeout=600, deadline_ns=None):
        if mode not in {"native", "fixture"}:
            raise ValueError("explicit backend mode required")
        self.config, self.python, self.mode = config, python, mode
        self.log_path, self.timeout = Path(log_path), timeout
        self.process = None
        self.rpc_deadline_ns = deadline_ns
        self.seq = 0
        self.reset_evidence = {}
        self.idle_confirmed = True
        # True when an owned worker was killed while device work was not confirmed
        # idle: the process is reaped (owned work terminated) but its captured
        # energy interval is not a complete goal interval.
        self.termination_forced = False
        self.termination_confirmed = True

    @property
    def owned_work_terminated(self):
        # Process-group termination and device drain are separate evidence.
        return self.process is None and self.termination_confirmed

    def capabilities(self):
        # Real capability verification happens in reset before returning goal-start.
        controls = expected_controls(self.config)
        return dict(controls=controls, expert_controls=bool(controls), engine=self.config.get("engine", "native"),
                    mode=self.mode, verification="required_at_reset")

    def reset_goal_state(self):
        if self.process is not None:
            raise RuntimeError("reset requires previous process to be reaped")
        self.termination_forced = False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("ab")
        self.messages = queue.Queue(maxsize=4)
        self.termination_confirmed = False
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
            if set(result["controls"]) != set(expected_controls(self.config)) or result["mode"] != self.mode:
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

    @contextmanager
    def cleanup_scope(self, timeout_seconds=10):
        # Draining may outlive the task, but cannot extend the next generation.
        prior = self.rpc_deadline_ns
        self.rpc_deadline_ns = time.monotonic_ns() + int((timeout_seconds + 2) * 1e9)
        try:
            yield
        finally:
            self.rpc_deadline_ns = prior

    def _rpc(self, method, args=None, timeout=None):
        if self.process is None:
            raise RuntimeError("backend is not active")
        self.seq += 1
        if method in {"init", "generate", "prepare"}:
            self.idle_confirmed = False
        try:
            wait = 10 if timeout is None else timeout
            if self.rpc_deadline_ns is not None:
                wait = min(wait, (self.rpc_deadline_ns - time.monotonic_ns()) / 1e9)
                if wait <= 0:
                    raise TimeoutError("backend goal deadline reached before RPC admission")
            self.process.stdin.write(
                json.dumps(dict(id=self.seq, method=method, args=args)) + "\n"
            )
            self.process.stdin.flush()
            if self.rpc_deadline_ns is not None:
                wait = min(wait, max(0, (self.rpc_deadline_ns - time.monotonic_ns()) / 1e9))
            try:
                result = self.messages.get(timeout=wait)
            except queue.Empty:
                raise RuntimeError(
                    f"backend RPC {method!r} produced no response within {wait}s"
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

    def generate(self, prompt, timeout, max_tokens, chat=None):
        # chat: dict(messages, tools, sampling, meta) for the chat-tools protocol;
        # prompt is then None. meta is fixture-only and never rendered.
        args = dict(max_tokens=max_tokens, **chat) if chat else dict(prompt=prompt, max_tokens=max_tokens)
        return self._rpc("generate", args, timeout=timeout)

    # Bound for killed group members to finish exiting after the leader is reaped.
    release_settle_seconds = 60

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
            # Killed group members (e.g. the model server holding the pinned model) can still be
            # exiting when the leader is reaped; wait for them within a finite bound, then fail closed.
            settle_deadline = time.monotonic() + self.release_settle_seconds
            if os.name == "posix":
                # Reaping only the leader does not prove the process group is empty.
                import psutil

                while True:
                    remaining = []
                    for child in psutil.process_iter(["pid", "status"]):
                        try:
                            if os.getpgid(child.pid) == p.pid and child.status() != psutil.STATUS_ZOMBIE:
                                remaining.append(child.pid)
                        except (ProcessLookupError, psutil.NoSuchProcess):
                            pass
                    if not remaining:
                        break
                    if time.monotonic() >= settle_deadline:
                        raise RuntimeError(f"backend process group termination unverified: {remaining}")
                    time.sleep(0.1)
            if self.reader_thread is not threading.current_thread():
                self.reader_thread.join(timeout=max(2, settle_deadline - time.monotonic()))
            if self.reader_thread.is_alive():
                raise RuntimeError("backend output reader did not terminate")
            self.termination_confirmed = True
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
            return self._error(exc, started)

    def chat(self, request, sampling, meta):
        """One chat-tools turn. finish_reason is stop, length or context_exhausted."""
        started = time.monotonic_ns()
        try:
            result = self.backend.generate(
                None,
                self.model_config["request_timeout_seconds"],
                self.model_config["max_tokens"],
                chat=dict(request, sampling=sampling, meta=meta),
            )
            return dict(
                status="ok",
                content=result["text"],
                finish_reason=result["finish_reason"],
                tokens=result["tokens"],
                token_provenance="tokenizer"
                if self.backend.mode == "native"
                else "estimated",
                backend=result,
            )
        except Exception as exc:
            return self._error(exc, started)

    def _error(self, exc, started):
        return dict(
            status="error",
            error=str(exc),
            tokens={},
            token_provenance="unknown",
            elapsed_ns=time.monotonic_ns() - started,
            owned_work_terminated=self.backend.owned_work_terminated,
        )
