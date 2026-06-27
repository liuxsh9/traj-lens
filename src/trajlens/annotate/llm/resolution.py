"""SESSION-level LLM annotator — classifies whether the task was resolved."""
import json

from trajlens.annotate.llm import UnparseableResponse
from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["resolved", "unverified", "partially_resolved", "unresolved", "indeterminate"],
        },
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify whether a coding agent session successfully resolved the user's task.

Analyze the FULL trajectory: initial request, agent actions, tool outputs, and final state.

FIRST classify the task type, because "done" means different things:

- ADVISORY task (question / explanation / how-to / code-review / recommendation): the deliverable IS the answer. The agent finishes by giving a complete, direct answer. The agent CANNOT run anything in the user's environment, so "the user still has to apply it" is the NORMAL, EXPECTED end — it is NOT incomplete work. A coherent, on-point final answer = resolved. Do NOT downgrade an advisory task to partially_resolved merely because the user did not come back to confirm, or because the agent could not execute the suggestion.
- ACTION task (the agent itself must produce/change an artifact: write code, edit files, run commands, build, fix a failing test): "done" has TWO requirements — the artifact must exist, AND it must be verified to work. An ACTION task where the artifact exists but was never run/tested/checked is "unverified", NOT "resolved". The agent merely SAYING "done" / "successfully created X" is a CLAIM, not verification — only actual execution evidence (a run, a passing test, expected output, user confirmation) counts.

Categories (choose exactly one):

- resolved — The task is complete with affirmative end-state evidence.
  • ADVISORY: the agent delivered a complete, direct, on-point answer to what was asked.
  • ACTION: the artifact is produced AND there is POSITIVE verification in the FINAL turns (tests pass, code compiles/runs, the agent ran it and saw expected output, or the user confirms). Absence of errors is NOT enough, and the agent's own "I'm done" claim is NOT enough — without execution evidence, an otherwise-complete ACTION result is "unverified".
- unverified — A complete deliverable whose correctness is NOT confirmed.
  • ACTION: full code / a finished implementation was produced but never run or tested — looks done, could well be right, but no evidence confirms it.
  • ADVISORY: a complete answer that hinges on a factual/correctness claim the agent could not check (recall-based, "I believe this is CF problem X", an unsourced factual assertion). Use when the only thing missing is verification, and the deliverable itself is complete. (If the deliverable is also incomplete, use partially_resolved.)
- partially_resolved — The DELIVERABLE ITSELF is incomplete: partial implementation, the agent stops mid-task (announcing or about to do more work), only some of a multi-part request answered, an ACTION task where the agent only described what to do but never produced the artifact it was asked to produce. NOT for an advisory task that gave a full answer the user merely hasn't applied yet.
- unresolved — The agent failed to address the request: stuck in a loop, gave up, produced code shown to be broken, answered a different question, or the final state does not address the original task. (A complete-but-unconfirmed solution is "unverified", not "unresolved".)
- indeterminate — Not enough information to judge: session was cut short, no clear success/failure signal, the task drifted to an unrelated topic, or the task itself is ambiguous.

Guidelines:
- Focus on the OUTCOME, not the process. A messy path that ends with a complete answer (advisory) or verified working code (action) is "resolved".
- resolved vs unverified turns on EVIDENCE for ACTION tasks: complete code that was actually run/tested = "resolved"; the same code never executed = "unverified". For ADVISORY tasks a complete answer is "resolved" unless it rests on an unchecked correctness claim → then "unverified".
- Do NOT downgrade a finished, coherent solution to "unresolved" just because verification is absent — "unresolved" is actual failure, "unverified" is unconfirmed success.
- Weight the final turns most heavily. Look for the final answer/conclusion and the nearest preceding tool evidence, especially tests/builds/checks that passed or failed.
- Multiple user corrections followed by eventual success = "resolved" (the corrections helped).
- CRITICAL — do not over-credit in-progress work. If the final assistant turn announces or is about to do more work ("next, I'll…", "now let me…", "let me continue…", "I'll start by…"), or the session ends on a pending tool call / tool output with no concluding wrap-up, the task is NOT finished → choose "partially_resolved" (clear progress) or "indeterminate" (cut short), NEVER "resolved".
- "resolved" demands an affirmative end state: a complete answer (advisory) or a verified artifact (action). A complete-but-unverified action solution is "unverified", not "resolved".
- Information gathering is NOT the deliverable. For research/explanation tasks the agent must actually deliver a SYNTHESIZED answer. A session full of Read/Grep/Glob that ends with the agent organizing its findings into a real answer IS resolved (advisory); one that ends WITHOUT ever answering is "partially_resolved" (found info, never answered) or "unresolved" (never answered) — the gap is the missing answer, not the missing user-confirmation.
- A session that only has a single user message with no agent response is "indeterminate".

Pay special attention to the "How the session ends" section below — it is the strongest signal for whether the task actually finished.

Respond in valid JSON only:
{"label": "<one of: resolved, unverified, partially_resolved, unresolved, indeterminate>", "reason": "<1-2 sentence explanation>"}"""


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


_COMPLETION_TOOL_NAMES = {
    "finish", "final", "complete", "completed", "done", "submit", "report_success",
    "task_complete", "attempt_completion",
}
_FINAL_DETAIL_HEADER = "Last assistant reasoning/message detail:\n"
_OLD_FINAL_DETAIL_HEADER = "Last assistant message (verbatim):\n"
# Keep the old ending-detail block's maximum size: old header + 800 chars.
_OLD_FINAL_DETAIL_TOTAL = len(_OLD_FINAL_DETAIL_HEADER) + 800
_FINAL_DETAIL_BUDGET = _OLD_FINAL_DETAIL_TOTAL - len(_FINAL_DETAIL_HEADER)


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[:max_chars - 1] + "…"


def _final_detail(last_reasoning: str | None, last_asst: str | None) -> str:
    """Fit final reasoning + visible answer into the old 800-char ending budget."""
    parts: list[tuple[str, str]] = []
    if last_reasoning:
        parts.append(("Reasoning: ", last_reasoning))
    if last_asst:
        parts.append(("Message: ", last_asst))
    if not parts:
        return "No assistant message present."

    if len(parts) == 1:
        prefix, text = parts[0]
        return prefix + _clip(text, _FINAL_DETAIL_BUDGET - len(prefix))

    reasoning_prefix, reasoning = parts[0]
    message_prefix, message = parts[1]
    sep = "\n"
    fixed = len(reasoning_prefix) + len(message_prefix) + len(sep)
    text_budget = max(0, _FINAL_DETAIL_BUDGET - fixed)
    # Split the fixed budget so reasoning can carry hidden conclusions while the
    # visible final answer still shows whether it is a code block or wrap-up.
    reasoning_budget = min(len(reasoning), max(240, text_budget // 2))
    message_budget = text_budget - reasoning_budget
    return (
        reasoning_prefix + _clip(reasoning, reasoning_budget) + sep
        + message_prefix + _clip(message, message_budget)
    )


def _is_completion_tool_name(name: str) -> bool:
    normalized = name.lower().replace("-", "_")
    return (
        normalized in _COMPLETION_TOOL_NAMES
        or normalized.endswith("_finish")
        or normalized.endswith("_complete")
        or normalized.endswith("_completion")
    )


def _completion_tool_detail(unit: list, last_item: Item) -> str | None:
    if last_item.type == "function_call" and _is_completion_tool_name(last_item.name):
        return f"{last_item.name} arguments: {_clip(last_item.arguments, 700)}"

    if last_item.type != "function_call_output":
        return None

    call = next((it for it in reversed(unit)
                 if it.type == "function_call"
                 and it.call_id == last_item.call_id
                 and _is_completion_tool_name(it.name)), None)
    if call is None:
        return None

    args = _clip(call.arguments, 420)
    output = _clip(last_item.output, 260)
    return f"{call.name} arguments: {args}\n{call.name} output: {output}"


def _ending_signal(unit: list) -> str:
    """Describe how the session ends — the key signal for whether it finished.

    Surfaces the final assistant message in fuller form (it's the completion
    signal, otherwise buried as a 150-char tail line) and flags a session that
    stops mid-action (ends on a tool call/output with no concluding reply).
    """
    last_item = next((it for it in reversed(unit) if _summarize(it)), None)
    last_asst = next((it.content for it in reversed(unit)
                      if it.type == "message" and it.role == "assistant"), None)
    last_reasoning = next((it.content for it in reversed(unit)
                           if it.type == "reasoning"), None)

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
    completion_detail = _completion_tool_detail(unit, last_item)
    if completion_detail:
        lines.append("Final tool activity is a completion tool; judge its payload "
                     "as possible success/failure evidence, not as an interruption.")
        lines.append("Completion tool detail:\n" + completion_detail)
    elif last_item.type in ("function_call", "function_call_output"):
        lines.append("⚠ Session ends on tool activity with no concluding assistant message — "
                     "the agent was still working.")
    if tool_calls >= 5 and longest_asst < 200:
        lines.append(
            f"⚠ Search-only pattern: {tool_calls} tool calls but the longest "
            f"assistant message is only {longest_asst} chars — the agent gathered "
            f"information but may never have synthesized an answer for the user.")
    lines.append(_FINAL_DETAIL_HEADER + _final_detail(last_reasoning, last_asst))
    return "\n".join(lines)


def build(unit: list, ctx: list) -> list[dict]:
    # ponytail: session-level = unit is the whole trajectory
    # Head+tail strategy: beginning has the task, end has the outcome
    summaries = [_summarize(it) for it in unit if _summarize(it)]

    if len(summaries) > 30:
        head = summaries[:6]
        tail = summaries[-19:]
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
    "unverified": "unverified",
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
