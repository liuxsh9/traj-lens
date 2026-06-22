from trajlens.core.registry import Registry
from . import openai_messages

ADAPTERS = Registry()
ADAPTERS.register("openai_messages", openai_messages)


def detect_and_parse(raw):
    """Sniff registered adapters and parse with the first match."""
    for _name, mod in ADAPTERS.items():
        if mod.sniff(raw):
            return mod.parse(raw)
    raise ValueError("no adapter matched the input shape")
