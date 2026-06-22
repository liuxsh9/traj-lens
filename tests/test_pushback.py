"""Unit tests for the pushback LLM annotator (build / parse / schema)."""
import json

import pytest

from trajlens.annotate.llm import pushback
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem


# ── build ──────────────────────────────────────────────────────────────

def test_build_produces_system_and_user_roles():
    unit = [MessageItem(role="user", content="That's wrong, fix it")]
    msgs = pushback.build(unit, unit)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == pushback.SYSTEM_PROMPT
    assert "That's wrong, fix it" in msgs[1]["content"]


def test_build_includes_context_summary():
    user = MessageItem(role="user", content="no, that's wrong")
    ctx = [
        MessageItem(role="assistant", content="I'll update the file"),
        FunctionCallItem(name="edit", arguments='{"path": "a.py"}', call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="done"),
        user,
    ]
    msgs = pushback.build([user], ctx)
    body = msgs[1]["content"]
    assert "Preceding conversation context:" in body
    assert "I'll update the file" in body
    assert "edit" in body
    assert body.count("no, that's wrong") == 1


def test_build_with_no_context():
    unit = [MessageItem(role="user", content="add a test")]
    msgs = pushback.build(unit, unit)
    assert "(no prior context)" in msgs[1]["content"]


# ── parse (now uses "label" field from SWE-chat format) ───────────────

def test_parse_label_format():
    resp = '{"label": "correction", "reason": "user said fix it"}'
    out = pushback.parse(resp)
    assert out["category"] == "correction"


def test_parse_non_pushback_maps_to_none():
    resp = '{"label": "non_pushback", "reason": "normal instruction"}'
    out = pushback.parse(resp)
    assert out["category"] == "none"


def test_parse_legacy_category_format():
    resp = '{"category": "rejection", "confidence": 0.8, "reason": "stop"}'
    out = pushback.parse(resp)
    assert out["category"] == "rejection"


def test_parse_markdown_fenced_json():
    resp = '```json\n{"label": "failure_report", "reason": "error"}\n```'
    out = pushback.parse(resp)
    assert out["category"] == "failure_report"


def test_parse_json_embedded_in_prose():
    resp = 'Here is my answer: {"label": "correction", "reason": "wrong"} hope it helps'
    out = pushback.parse(resp)
    assert out["category"] == "correction"


def test_parse_malformed_returns_default():
    out = pushback.parse("I cannot classify this message.")
    assert out["category"] == "none"
    assert out["confidence"] == 0.0


def test_parse_unknown_label_falls_back_to_none():
    out = pushback.parse('{"label": "angry", "reason": "x"}')
    assert out["category"] == "none"


# ── schema ─────────────────────────────────────────────────────────────

def test_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(pushback.SCHEMA)


def test_schema_round_trips_through_json():
    assert json.loads(json.dumps(pushback.SCHEMA)) == pushback.SCHEMA
