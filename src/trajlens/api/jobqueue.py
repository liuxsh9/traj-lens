"""Background job queue — two independent lanes, each a single worker thread.

Why two lanes instead of one shared queue: a 2-second rule job should not wait
behind a 5-minute LLM job. Splitting by resource decouples their latency.

  LLM lane — one worker owning one persistent event loop. Serial by design: the
    llm_client rate limiter's asyncio.Semaphore binds to this loop once and stays
    a true global ceiling. Running LLM jobs concurrently would give each its own
    loop+semaphore and multiply the real request rate against the provider.

  CPU lane — rule annotators + semgrep scans. Also serial, but for a different
    reason: rule annotators are pure-Python CPU work that holds the GIL, so
    running them in parallel buys no throughput, only SQLite write contention.
    semgrep already saturates cores via its own ThreadPoolExecutor internally.

ponytail: if a rule annotator ever releases the GIL (C extension, subprocess),
swap the CPU lane's single worker for a small ThreadPoolExecutor — the lane
boundary already isolates that change from the LLM path.
"""
import asyncio
import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)


class _Lane:
    """One FIFO queue drained by one daemon worker thread. `needs_loop` gives the
    worker a persistent event loop to pass into each task (LLM lane); the CPU lane
    passes None."""

    def __init__(self, name: str, needs_loop: bool):
        self._name = name
        self._needs_loop = needs_loop
        self._queue: "queue.Queue[Callable]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def _run_worker(self) -> None:
        loop = None
        if self._needs_loop:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        while True:
            fn = self._queue.get()
            try:
                fn(loop)
            except Exception:  # noqa: BLE001 — one bad job must not kill the lane
                log.exception("%s lane: job failed", self._name)
            finally:
                self._queue.task_done()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run_worker, daemon=True, name=f"{self._name}-worker")
                self._worker.start()

    def submit(self, fn: Callable) -> int:
        """Enqueue `fn(loop)`. Returns queue depth at enqueue time (0 = starts now,
        N = N jobs ahead of it in THIS lane)."""
        self._ensure_worker()
        depth = self._queue.qsize()
        self._queue.put(fn)
        return depth


_llm_lane = _Lane("llm", needs_loop=True)
_cpu_lane = _Lane("cpu", needs_loop=False)


def submit_llm(fn: Callable) -> int:
    """Enqueue an async LLM job onto the serial LLM lane. `fn(loop)` should run its
    coroutine via loop.run_until_complete(...)."""
    return _llm_lane.submit(fn)


def submit_cpu(fn: Callable) -> int:
    """Enqueue a CPU-bound job (rule annotator, semgrep) onto the CPU lane.
    `fn(loop)` receives loop=None."""
    return _cpu_lane.submit(fn)
