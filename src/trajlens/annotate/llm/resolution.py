"""SESSION-level LLM annotator — classifies whether the task was resolved."""
import json

from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["resolved", "partially_resolved", "unresolved", "indeterminate"],
        },
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify whether a coding agent session successfully resolved the user's task.

Analyze the FULL trajectory: initial request, agent actions, tool outputs, and final state.

Categories (choose exactly one):

- resolved — The agent completed the task. Evidence: tests pass, code compiles, user confirms, or the final state clearly satisfies the original request.
- partially_resolved — The agent made meaningful progress but left significant work undone: partial implementation, some tests failing, or the user had to manually finish.
- unresolved — The agent failed to solve the task: stuck in a loop, gave up, produced broken code, or the final state does not address the original request.
- indeterminate — Not enough information to judge: session was cut short, no clear success/failure signal, or the task itself is ambiguous.

Guidelines:
- Focus on the OUTCOME, not the process. A messy path that ends with working code is "resolved".
- Multiple user corrections followed by eventual success = "resolved" (the corrections helped).
- If the session ends mid-work with no completion signal, prefer "indeterminate" over guessing.
- A session that only has a single user message with no agent response is "indeterminate".

Respond in valid JSON only:
{"label": "<one of: resolved, partially_resolved, unresolved, indeterminate>", "reason": "<1-2 sentence explanation>"}"""


def _summarize(it: Item, max_chars: int = 300) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"[{it.role}] {c}"
    if it.type == "reasoning":
        return f"[reasoning] {it.content[:150]}…"
    if it.type == "function_call":
        return f"[call] {it.name}({it.arguments[:150]})"
    if it.type == "function_call_output":
        return f"[output] {it.output[:200]}"
    return ""


def build(unit: list, ctx: list) -> list[dict]:
    # ponytail: session-level = unit is the whole trajectory
    # Summarize with head + tail strategy to stay within token budget
    summaries = [_summarize(it) for it in unit if _summarize(it)]

    if len(summaries) > 40:
        # head 15 + ... + tail 20 — tail is more important for outcome
        head = summaries[:15]
        tail = summaries[-20:]
        body = "\n".join(head) + f"\n\n[... {len(summaries) - 35} items omitted ...]\n\n" + "\n".join(tail)
    else:
        body = "\n".join(summaries)

    prompt = f"Full session transcript:\n{body}\n\nClassify the resolution status of this session."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


_LABEL_MAP = {
    "resolved": "resolved",
    "partially_resolved": "partially_resolved",
    "unresolved": "unresolved",
    "indeterminate": "indeterminate",
}


def parse(response: str) -> dict:
    data = _loads(response)
    if data is None:
        return {"resolution": "indeterminate", "reason": "unparseable response"}
    raw_label = data.get("label", "indeterminate")
    return {
        "resolution": _LABEL_MAP.get(raw_label, "indeterminate"),
        "reason": data.get("reason", ""),
    }


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
