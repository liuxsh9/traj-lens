"""Single-worker background job queue.

All annotator + semgrep jobs run serially on ONE worker thread that owns ONE
persistent event loop for the process lifetime. Two consequences we rely on:

1. Serial execution — only one job runs at a time, so concurrent LLM annotators
   no longer multiply the real request rate against the provider. The LLM rate
   limiter (llm_client) is finally a true global ceiling instead of per-job.
2. Persistent loop — the limiter's asyncio.Semaphore binds to this loop once and
   stays bound, so it's shared across every job (the old per-job asyncio.run gave
   each job a fresh loop and thus its own semaphore).

ponytail: FIFO, no priorities. Rule annotators are fast; if one lands behind an
LLM job it just waits. Add a PriorityQueue only if rule-first ordering matters.
"""
import asyncio
import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)

# Each task is `fn(loop)` where loop is the worker's persistent event loop.
# Sync jobs (semgrep) ignore it; async jobs use loop.run_until_complete(...).
_queue: "queue.Queue[Callable]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def _run_worker() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        fn = _queue.get()
        try:
            fn(loop)
        except Exception:  # noqa: BLE001 — a single bad job must not kill the worker
            log.exception("background job failed")
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, daemon=True, name="job-worker")
            _worker.start()


def submit(fn: Callable) -> int:
    """Enqueue `fn(loop)` to run on the single worker thread. Returns queue depth
    at enqueue time (0 = will start immediately, N = N jobs ahead of it)."""
    _ensure_worker()
    depth = _queue.qsize()
    _queue.put(fn)
    return depth
