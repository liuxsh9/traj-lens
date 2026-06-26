"""SESSION-level LLM annotator — classifies whether the task was resolved."""
import json

from trajlens.annotate.llm import UnparseableResponse
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

- resolved — The agent completed the task. Requires POSITIVE completion evidence in the FINAL turns: tests pass, code compiles, the agent states it is done, the user confirms, or the final state clearly and fully satisfies the original request. Absence of errors is NOT enough.
- partially_resolved — The agent made meaningful progress but left significant work undone: partial implementation, some tests failing, the user had to manually finish, OR the session ends with the agent still mid-task (announcing or about to perform further work).
- unresolved — The agent failed to solve the task: stuck in a loop, gave up, produced broken code, or the final state does not address the original request.
- indeterminate — Not enough information to judge: session was cut short, no clear success/failure signal, or the task itself is ambiguous.

Guidelines:
- Focus on the OUTCOME, not the process. A messy path that ends with working code is "resolved".
- Multiple user corrections followed by eventual success = "resolved" (the corrections helped).
- CRITICAL — do not over-credit in-progress work. If the final assistant turn announces or is about to do more work ("next, I'll…", "now let me…", "let me continue…", "I'll start by…"), or the session ends on a pending tool call / tool output with no concluding wrap-up, the task is NOT finished → choose "partially_resolved" (clear progress) or "indeterminate" (cut short), NEVER "resolved".
- "resolved" demands an affirmative end state, not merely the lack of a visible failure.
- Information gathering is NOT resolution. For research/explanation tasks ("how does X work?", "is there a mechanism that…?"), the agent must actually deliver a synthesized answer to the user. A session full of Read/Grep/Glob calls that ends without the agent organizing its findings into an answer is "partially_resolved" (found the info, never answered) or "unresolved" (never answered) — never "resolved", no matter how thorough the searching looked.
- A session that only has a single user message with no agent response is "indeterminate".

Pay special attention to the "How the session ends" section below — it is the strongest signal for whether the task actually finished.

Respond in valid JSON only:
{"label": "<one of: resolved, partially_resolved, unresolved, indeterminate>", "reason": "<1-2 sentence explanation>"}"""


def _summarize(it: Item, max_chars: int = 150) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"[{it.role}] {c}"
    if it.type == "reasoning":
        return f"[reasoning] {it.content[:80]}…"
    if it.type == "function_call":
        return f"[call] {it.name}({it.arguments[:80]})"
    if it.type == "function_call_output":
        return f"[output] {it.output[:100]}"
    return ""


def _ending_signal(unit: list) -> str:
    """Describe how the session ends — the key signal for whether it finished.

    Surfaces the final assistant message in fuller form (it's the completion
    signal, otherwise buried as a 150-char tail line) and flags a session that
    stops mid-action (ends on a tool call/output with no concluding reply).
    """
    last_item = next((it for it in reversed(unit) if _summarize(it)), None)
    last_asst = next((it.content for it in reversed(unit)
                      if it.type == "message" and it.role == "assistant"), None)

    # "search-only / never-answers" fingerprint: many tool calls but no
    # substantive assistant message. 200 chars ≈ a real synthesized answer vs a
    # "let me read X" transition. ponytail: char-count proxy, swap for a real
    # answer-detector only if this misfires.
    asst_msgs = [it.content for it in unit
                 if it.type == "message" and it.role == "assistant"]
    longest_asst = max((len(c) for c in asst_msgs), default=0)
    tool_calls = sum(1 for it in unit if it.type == "function_call")

    lines = []
    if last_item is None:
        return "Last item: (empty session)"
    lines.append(f"Final transcript item is a {last_item.type}"
                 + (f"/{last_item.role}" if last_item.type == "message" else "") + ".")
    if last_item.type in ("function_call", "function_call_output"):
        lines.append("⚠ Session ends on tool activity with no concluding assistant message — "
                     "the agent was still working.")
    if tool_calls >= 5 and longest_asst < 200:
        lines.append(
            f"⚠ Search-only pattern: {tool_calls} tool calls but the longest "
            f"assistant message is only {longest_asst} chars — the agent gathered "
            f"information but may never have synthesized an answer for the user.")
    if last_asst:
        # ponytail: 800 chars is enough to see "done" vs "next I'll…"; stays well under payload budget
        text = last_asst[:800] + ("…" if len(last_asst) > 800 else "")
        lines.append(f"Last assistant message (verbatim):\n{text}")
    else:
        lines.append("No assistant message present.")
    return "\n".join(lines)


def build(unit: list, ctx: list) -> list[dict]:
    # ponytail: session-level = unit is the whole trajectory
    # Head+tail strategy: beginning has the task, end has the outcome
    summaries = [_summarize(it) for it in unit if _summarize(it)]

    if len(summaries) > 30:
        head = summaries[:10]
        tail = summaries[-15:]
        body = "\n".join(head) + f"\n\n[... {len(summaries) - 25} items omitted ...]\n\n" + "\n".join(tail)
    else:
        body = "\n".join(summaries)

    ending = _ending_signal(unit)
    prompt = (f"Full session transcript:\n{body}\n\n"
              f"How the session ends:\n{ending}\n\n"
              f"Classify the resolution status of this session.")
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
        raise UnparseableResponse(response)
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
