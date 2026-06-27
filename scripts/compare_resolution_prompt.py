"""Compare old vs current resolution prompt inputs on synthetic sessions.

This does not call an LLM. It checks whether the annotator prompt exposes the
signals a judge needs: final reasoning, recent test output, and unfinished ends.
"""

from trajlens.annotate.llm import resolution
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem, ReasoningItem


def _old_summarize(it, max_chars: int = 150) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("..." if len(it.content) > max_chars else "")
        return f"[{it.role}] {c}"
    if it.type == "reasoning":
        return f"[reasoning] {it.content[:80]}..."
    if it.type == "function_call":
        return f"[call] {it.name}({it.arguments[:80]})"
    if it.type == "function_call_output":
        return f"[output] {it.output[:100]}"
    return ""


def _old_ending_signal(unit: list) -> str:
    last_item = next((it for it in reversed(unit) if _old_summarize(it)), None)
    last_asst = next((it.content for it in reversed(unit)
                      if it.type == "message" and it.role == "assistant"), None)
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
        lines.append("Session ends on tool activity with no concluding assistant message - "
                     "the agent was still working.")
    if tool_calls >= 5 and longest_asst < 200:
        lines.append(
            f"Search-only pattern: {tool_calls} tool calls but the longest "
            f"assistant message is only {longest_asst} chars - the agent gathered "
            f"information but may never have synthesized an answer for the user.")
    if last_asst:
        text = last_asst[:800] + ("..." if len(last_asst) > 800 else "")
        lines.append(f"Last assistant message (verbatim):\n{text}")
    else:
        lines.append("No assistant message present.")
    return "\n".join(lines)


def old_build(unit: list) -> str:
    summaries = [_old_summarize(it) for it in unit if _old_summarize(it)]
    if len(summaries) > 30:
        head = summaries[:10]
        tail = summaries[-15:]
        body = "\n".join(head) + f"\n\n[... {len(summaries) - 25} items omitted ...]\n\n" + "\n".join(tail)
    else:
        body = "\n".join(summaries)
    ending = _old_ending_signal(unit)
    return (f"Full session transcript:\n{body}\n\n"
            f"How the session ends:\n{ending}\n\n"
            f"Classify the resolution status of this session.")


def current_build(unit: list) -> str:
    return resolution.build(unit, unit)[-1]["content"]


def synthetic_cases() -> dict[str, list]:
    cases = {}

    cases["final_reasoning_has_completion_visible_code"] = [
        MessageItem(role="user", content="Add a parser and show final code."),
        FunctionCallItem(name="edit", arguments='{"p":"parser.py"}', call_id="edit"),
        FunctionCallOutputItem(call_id="edit", output="ok"),
        ReasoningItem(content=(
            "I reviewed the final diff, checked the parser paths, and compared the "
            "edge cases against the requested behavior. The parser is implemented "
            "and the targeted tests pass."
        )),
        MessageItem(role="assistant", content="```python\nclass Parser:\n    pass\n```"),
    ]

    long_recent = []
    for i in range(12):
        long_recent.append(MessageItem(role="user" if i % 2 == 0 else "assistant",
                                       content=f"setup item {i}"))
    for i in range(24):
        long_recent.append(MessageItem(role="assistant", content=f"middle item {i}"))
    long_recent.extend([
        FunctionCallItem(name="pytest", arguments='{"cmd":"uv run pytest tests/"}', call_id="pytest"),
        FunctionCallOutputItem(call_id="pytest", output="128 passed in 4.2s"),
        MessageItem(role="assistant", content="Done, tests pass."),
    ])
    cases["long_session_recent_tests"] = long_recent

    cases["unfinished_tool_end"] = [
        MessageItem(role="user", content="Fix the API bug."),
        MessageItem(role="assistant", content="I will inspect the failing route."),
        FunctionCallItem(name="Read", arguments='{"file":"routes.py"}', call_id="read"),
        FunctionCallOutputItem(call_id="read", output="def route(): ..."),
    ]

    cases["answered_research_after_tools"] = [
        MessageItem(role="user", content="How does batching work?"),
        *[
            item
            for i in range(6)
            for item in (
                FunctionCallItem(name="Read", arguments=f'{{"file":"f{i}.py"}}', call_id=f"r{i}"),
                FunctionCallOutputItem(call_id=f"r{i}", output="code"),
            )
        ],
        MessageItem(role="assistant", content="Batching works by collecting pending jobs, grouping by annotator, and flushing results as each LLM call completes."),
    ]

    return cases


def contains(prompt: str, needle: str) -> str:
    return "yes" if needle in prompt else "no"


def main() -> None:
    checks = {
        "final_reasoning_has_completion_visible_code": [
            "targeted tests pass",
            "class Parser",
        ],
        "long_session_recent_tests": [
            "uv run pytest tests/",
            "128 passed",
            "Done, tests pass.",
        ],
        "unfinished_tool_end": [
            "still working",
        ],
        "answered_research_after_tools": [
            "Batching works by collecting",
        ],
    }

    for name, items in synthetic_cases().items():
        old = old_build(items)
        new = current_build(items)
        print(f"\n{name}")
        print(f"  bytes: old={len(old.encode())} new={len(new.encode())} delta={len(new.encode()) - len(old.encode())}")
        for needle in checks[name]:
            print(f"  contains {needle!r}: old={contains(old, needle)} new={contains(new, needle)}")


if __name__ == "__main__":
    main()
