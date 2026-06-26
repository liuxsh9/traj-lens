"""LLM annotators. Shared failure type so a model response we cannot parse is
treated as a *read failure* (no annotation written, retryable on re-run) rather
than a fabricated default label that silently pollutes results."""


class UnparseableResponse(ValueError):
    """Raised by a parser when the model response yields no usable JSON.

    runner.py catches this per-target: it logs, records the error on the job,
    and writes NO annotation — so the target stays a gap and a re-run retries it.
    """

    def __init__(self, response: str):
        # ponytail: keep a 200-char preview so job errors/logs show what came back
        preview = response[:200] if response else "(empty)"
        super().__init__(f"unparseable LLM response: {preview!r}")
