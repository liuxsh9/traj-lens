from trajlens.core.registry import Registry
from . import openai_messages, claude_code, codex

ADAPTERS = Registry()
ADAPTERS.register("openai_messages", openai_messages)
ADAPTERS.register("claude_code", claude_code)
ADAPTERS.register("codex", codex)


def detect_and_parse(raw):
    """Sniff registered adapters and parse with the first match.
    raw: dict (single-object formats like openai_messages) or list[dict] (JSONL session logs)."""
    for _name, mod in ADAPTERS.items():
        if mod.sniff(raw):
            return mod.parse(raw)
    raise ValueError("no adapter matched the input shape")
