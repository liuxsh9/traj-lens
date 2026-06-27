"""Tests that LLM annotator build() respects payload size budgets."""
import json

from trajlens.annotate.llm import intent, pushback, resolution, topic
from trajlens.annotate.llm_client import MAX_PAYLOAD_BYTES
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem


def _huge_user(n: int = 50_000) -> MessageItem:
    return MessageItem(role="user", content="x" * n)


def _payload_bytes(messages: list[dict]) -> int:
    return len(json.dumps(messages, ensure_ascii=False).encode())


# ── pushback: head-only truncation on user text ──────────────────────

def test_pushback_caps_long_user_message():
    msgs = pushback.build([_huge_user()], [_huge_user()])
    assert _payload_bytes(msgs) < MAX_PAYLOAD_BYTES


# ── intent: head-only truncation on user text ────────────────────────

def test_intent_caps_long_user_message():
    msgs = intent.build([_huge_user()], [_huge_user()])
    assert _payload_bytes(msgs) < MAX_PAYLOAD_BYTES


# ── resolution: head+tail on long session ────────────────────────────

def test_resolution_caps_large_session():
    items = []
    for i in range(200):
        items.append(MessageItem(role="user" if i % 2 == 0 else "assistant",
                                 content="y" * 2000))
        items.append(FunctionCallItem(name="edit", arguments='{"p":"a.py"}' * 50, call_id=f"c{i}"))
        items.append(FunctionCallOutputItem(call_id=f"c{i}", output="ok " * 500))

    msgs = resolution.build(items, items)
    assert _payload_bytes(msgs) < MAX_PAYLOAD_BYTES


# ── resolution: ending signal catches mid-task sessions ──────────────

def test_resolution_flags_mid_task_ending():
    """A session ending with the agent still working must surface as such in the
    prompt, so the judge doesn't mark in-progress work as resolved."""
    from trajlens.annotate.llm import resolution

    items = [
        MessageItem(role="user", content="add a parser"),
        MessageItem(role="assistant", content="Sounds good. Next, I'll start implementing the tokenizer."),
        FunctionCallItem(name="edit", arguments='{"p":"lex.py"}', call_id="c1"),
    ]
    prompt = resolution.build(items, items)[-1]["content"]
    assert "How the session ends:" in prompt
    # ends on a tool call → mid-action flag present
    assert "still working" in prompt
    # final assistant message shown verbatim so "Next, I'll…" is visible
    assert "Next, I'll start implementing the tokenizer" in prompt


def test_resolution_finish_tool_ending_is_not_marked_still_working():
    from trajlens.annotate.llm import resolution

    items = [
        MessageItem(role="user", content="add a parser"),
        FunctionCallItem(
            name="finish",
            arguments='{"status":"success","summary":"implemented parser; tests passed"}',
            call_id="finish1",
        ),
        FunctionCallOutputItem(call_id="finish1", output="completed successfully"),
    ]

    prompt = resolution.build(items, items)[-1]["content"]

    assert "completion tool" in prompt
    assert "still working" not in prompt
    assert "implemented parser; tests passed" in prompt
    assert "completed successfully" in prompt


def test_resolution_ending_shows_completion():
    from trajlens.annotate.llm import resolution

    items = [
        MessageItem(role="user", content="add a parser"),
        MessageItem(role="assistant", content="Done — all 12 tests pass."),
    ]
    prompt = resolution.build(items, items)[-1]["content"]
    assert "Done — all 12 tests pass." in prompt
    assert "still working" not in prompt


def test_resolution_ending_includes_final_reasoning_with_fixed_budget():
    from trajlens.annotate.llm import resolution
    from trajlens.core.model import ReasoningItem

    reasoning = (
        "I reviewed the final diff, checked the parser paths, and compared the "
        "edge cases against the requested behavior. I finished the implementation "
        "and all tests pass. "
        + "r" * 700
    )
    visible = "```python\n" + ("print('ok')\n" * 120) + "```"
    items = [
        MessageItem(role="user", content="add a parser"),
        ReasoningItem(content=reasoning),
        MessageItem(role="assistant", content=visible),
    ]

    prompt = resolution.build(items, items)[-1]["content"]
    detail = prompt.split("Last assistant reasoning/message detail:\n", 1)[1].split(
        "\n\nClassify the resolution status", 1)[0]
    ending_line = "Last assistant reasoning/message detail:\n" + detail

    assert "I finished the implementation and all tests pass." in prompt
    assert "Last assistant reasoning/message detail:" in prompt
    assert len(ending_line) <= len("Last assistant message (verbatim):\n") + 801


def test_resolution_long_session_prioritizes_recent_evidence():
    """For long sessions, keep total transcript lines fixed but bias them toward
    final turns where tests and wrap-up evidence usually appear."""
    from trajlens.annotate.llm import resolution

    items = []
    for i in range(35):
        items.append(MessageItem(role="user" if i % 2 == 0 else "assistant",
                                 content=f"early/middle item {i}"))
    items.extend([
        FunctionCallItem(name="pytest", arguments='{"cmd":"uv run pytest"}', call_id="test"),
        FunctionCallOutputItem(call_id="test", output="42 passed"),
        MessageItem(role="assistant", content="Implemented the fix and all tests pass."),
    ])

    prompt = resolution.build(items, items)[-1]["content"]
    transcript = prompt.split("Full session transcript:\n", 1)[1].split(
        "\n\nHow the session ends:", 1)[0]
    lines = [line for line in transcript.splitlines() if line and not line.startswith("[...")]

    assert len(lines) == 25
    assert "early/middle item 6" not in transcript
    assert "pytest" in transcript
    assert "42 passed" in transcript
    assert "Implemented the fix and all tests pass." in transcript


def test_resolution_flags_search_only_pattern():
    """Sample 003263a2 shape: a research question answered only with tool calls
    and short 'let me read X' transitions, never a synthesized answer."""
    from trajlens.annotate.llm import resolution

    items = [MessageItem(role="user",
                         content="How does the code create structural information gaps?")]
    for i in range(8):
        items.append(MessageItem(role="assistant", content="Let me read the next file."))
        items.append(FunctionCallItem(name="Read", arguments=f'{{"p":"f{i}.py"}}', call_id=f"c{i}"))
        items.append(FunctionCallOutputItem(call_id=f"c{i}", output="some code"))

    prompt = resolution.build(items, items)[-1]["content"]
    assert "Search-only pattern" in prompt
    assert "8 tool calls" in prompt
    # ends on a tool output → mid-action flag also present
    assert "still working" in prompt


def test_resolution_no_false_search_only_when_answered():
    from trajlens.annotate.llm import resolution

    items = [MessageItem(role="user", content="How does X work?")]
    for i in range(8):
        items.append(FunctionCallItem(name="Read", arguments=f'{{"p":"f{i}.py"}}', call_id=f"c{i}"))
        items.append(FunctionCallOutputItem(call_id=f"c{i}", output="code"))
    items.append(MessageItem(role="assistant", content="X works by " + "detailed explanation " * 20))

    prompt = resolution.build(items, items)[-1]["content"]
    assert "Search-only pattern" not in prompt


# ── topic: first_user + last_asst capped ─────────────────────────────

def test_topic_caps_large_session():
    items = [
        MessageItem(role="user", content="z" * 50_000),
        MessageItem(role="assistant", content="w" * 50_000),
    ]
    msgs = topic.build(items, items)
    assert _payload_bytes(msgs) < MAX_PAYLOAD_BYTES
