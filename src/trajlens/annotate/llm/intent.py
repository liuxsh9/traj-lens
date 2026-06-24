"""USER_TURN LLM annotator — classifies user prompt intent (implement/debug/refactor/explain/other)."""
import json

from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["implement", "debug", "refactor", "explain", "other"]},
        "reason": {"type": "string"},
    },
    "required": ["intent", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify the intent of a user prompt in a coding agent session.

Categories (choose exactly one):

- implement — The user asks the agent to build, add, or create new functionality, features, files, or code. Includes requests to write new tests, add new endpoints, create new components, etc.
- debug — The user reports a bug, error, or unexpected behavior and asks the agent to investigate or fix it. Includes pasting error messages, describing broken behavior, or asking why something doesn't work.
- refactor — The user asks to restructure, clean up, optimize, simplify, rename, or reorganize existing code WITHOUT changing its external behavior. Includes migration, dependency upgrades, and performance optimization.
- explain — The user asks the agent to explain, describe, analyze, or teach something. Includes "how does X work?", "what does this do?", code review requests focused on understanding.
- other — Anything that doesn't fit the above: configuration changes, deployment commands, project setup, general conversation, or ambiguous short prompts like "continue" or "ok".

Rules:
- Classify based on the PRIMARY intent. If the user says "fix this bug and also add a test", the primary intent is debug.
- Short continuations like "continue", "go ahead", "yes" → other.
- A prompt that says "look at X and then fix it" is debug, not explain.

Respond in valid JSON only:
{"intent": "<category>", "reason": "<1 sentence>"}"""


def _summarize(it: Item, max_chars: int = 150) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"{it.role}: {c}"
    if it.type == "function_call":
        return f"call {it.name}({it.arguments[:80]})"
    if it.type == "function_call_output":
        return f"output: {it.output[:80]}"
    return ""


def build(unit: list, ctx: list) -> list[dict]:
    user_text = next((it.content for it in unit if it.type == "message" and it.role == "user"), "")
    unit_ids = {id(it) for it in unit}
    before = [it for it in ctx if id(it) not in unit_ids]

    recent = [_summarize(it) for it in before[-3:]]
    context_summary = "\n".join(recent) if recent else "(start of session)"

    prompt = f"Preceding context:\n{context_summary}\n\nUser prompt to classify:\n{user_text}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def parse(response: str) -> dict:
    data = _loads(response)
    if data is None:
        return {"intent": "other", "reason": "unparseable response"}
    intent = data.get("intent", "other")
    if intent not in ("implement", "debug", "refactor", "explain", "other"):
        intent = "other"
    return {"intent": intent, "reason": data.get("reason", "")}


def _loads(response: str) -> dict | None:
    for candidate in (response, _strip_fences(response), _braces(response)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _braces(s: str) -> str:
    lo, hi = s.find("{"), s.rfind("}")
    return s[lo:hi + 1] if 0 <= lo < hi else ""
