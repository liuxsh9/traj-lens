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


# ── topic: first_user + last_asst capped ─────────────────────────────

def test_topic_caps_large_session():
    items = [
        MessageItem(role="user", content="z" * 50_000),
        MessageItem(role="assistant", content="w" * 50_000),
    ]
    msgs = topic.build(items, items)
    assert _payload_bytes(msgs) < MAX_PAYLOAD_BYTES
