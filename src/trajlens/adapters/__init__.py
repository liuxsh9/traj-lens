from trajlens.core.registry import Registry
from . import openai_messages, claude_code, codex, swe_chat

ADAPTERS = Registry()
ADAPTERS.register("openai_messages", openai_messages)
ADAPTERS.register("claude_code", claude_code)
ADAPTERS.register("codex", codex)
ADAPTERS.register("swe_chat", swe_chat)


def detect_and_parse(raw) -> tuple:
    """Sniff registered adapters and parse with the first match.
    Returns (Trajectory, format_name).
    raw: dict (single-object formats like openai_messages) or list[dict] (JSONL session logs)."""
    for name, mod in ADAPTERS.items():
        if mod.sniff(raw):
            return mod.parse(raw), name
    raise ValueError("no adapter matched the input shape")
