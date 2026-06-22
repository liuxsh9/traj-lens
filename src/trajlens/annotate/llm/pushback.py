"""USER_TURN LLM annotator — classifies user pushback (correction/rejection/failure_report/none)."""
import json

from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["correction", "rejection", "failure_report", "none"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["category", "confidence", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify a user's message in a coding-agent conversation as one of four pushback categories:

- "correction": the user corrects the assistant's previous work (e.g. "no, that's wrong", "fix this", "use X instead").
- "rejection": the user rejects the assistant's approach or direction (e.g. "don't do that", "stop", "undo").
- "failure_report": the user reports something failed (e.g. "it doesn't work", "I got an error", "tests fail").
- "none": a normal instruction or question with no pushback.

You are given recent context (the assistant's prior messages/actions) and the user's message.
Respond with ONLY a JSON object matching this schema:
{"category": "<one of the four>", "confidence": <number 0..1>, "reason": "<short justification>"}
Do not include any text outside the JSON."""

_DEFAULT = {"category": "none", "confidence": 0.0, "reason": "unparseable response"}


def _summarize(it: Item) -> str:
    if it.type == "message":
        return f"{it.role}: {it.content}"
    if it.type == "reasoning":
        return f"reasoning: {it.content}"
    if it.type == "function_call":
        return f"call {it.name}({it.arguments})"
    if it.type == "function_call_output":
        return f"output: {it.output}"
    return ""


def build(unit: list, ctx: list) -> list[dict]:
    user_text = next((it.content for it in unit if it.type == "message" and it.role == "user"), "")
    # ponytail: ctx is ordered (window: before + unit + after); keep the assistant
    # context preceding the unit by dropping the unit items, then take the last few.
    unit_ids = {id(it) for it in unit}
    before = [_summarize(it) for it in ctx if id(it) not in unit_ids]
    context_summary = "\n".join(before[-4:]) if before else "(no prior context)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[Context]\n{context_summary}\n\n[User message]\n{user_text}"},
    ]


def parse(response: str) -> dict:
    data = _loads(response)
    if data is None:
        return dict(_DEFAULT)
    out = {
        "category": data.get("category", "none"),
        "confidence": data.get("confidence", 0.0),
        "reason": data.get("reason", ""),
    }
    if out["category"] not in {"correction", "rejection", "failure_report", "none"}:
        out["category"] = "none"
    return out


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
