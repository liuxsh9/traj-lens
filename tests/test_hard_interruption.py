"""Tests for hard_interruption rule annotator."""
from trajlens.core.model import (FunctionCallItem, FunctionCallOutputItem,
                                  MessageItem, ReasoningItem)
from trajlens.annotate.rules import hard_interruption


def test_normal_session():
    ctx = [MessageItem(role="user", content="hi"),
           MessageItem(role="assistant", content="hello")]
    out = hard_interruption.annotate(ctx, ctx)
    assert out == {"interrupted": False, "reason": None}


def test_dangling_tool_call():
    ctx = [MessageItem(role="user", content="do it"),
           FunctionCallItem(name="bash", arguments='{}', call_id="c1")]
    out = hard_interruption.annotate(ctx, ctx)
    assert out["interrupted"] is True
    assert out["reason"] == "dangling_tool_call"


def test_ends_on_error():
    ctx = [MessageItem(role="user", content="run tests"),
           FunctionCallItem(name="bash", arguments='{}', call_id="c1"),
           FunctionCallOutputItem(call_id="c1", output="FAILED: error in test")]
    out = hard_interruption.annotate(ctx, ctx)
    assert out["interrupted"] is True
    assert out["reason"] == "ends_on_error"


def test_no_assistant_response():
    ctx = [MessageItem(role="user", content="hello")]
    out = hard_interruption.annotate(ctx, ctx)
    assert out["interrupted"] is True
    assert out["reason"] == "no_assistant_response"


def test_reasoning_counts_as_assistant():
    ctx = [MessageItem(role="user", content="think about this"),
           ReasoningItem(content="hmm...")]
    out = hard_interruption.annotate(ctx, ctx)
    assert out == {"interrupted": False, "reason": None}


def test_empty_session():
    out = hard_interruption.annotate([], [])
    assert out == {"interrupted": False, "reason": None}
