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
    assert "[Context]" in body
    assert "I'll update the file" in body
    assert "edit" in body
    # the unit's own user message must not be duplicated into the context block
    assert body.count("no, that's wrong") == 1


def test_build_with_no_context():
    unit = [MessageItem(role="user", content="add a test")]
    msgs = pushback.build(unit, unit)
    assert "(no prior context)" in msgs[1]["content"]


def test_build_missing_user_message():
    unit = [FunctionCallItem(name="edit", arguments="{}", call_id="c1")]
    msgs = pushback.build(unit, unit)
    assert msgs[1]["content"].endswith("[User message]\n")


# ── parse ──────────────────────────────────────────────────────────────

def test_parse_clean_json():
    resp = '{"category": "correction", "confidence": 0.9, "reason": "user said fix it"}'
    out = pushback.parse(resp)
    assert out == {"category": "correction", "confidence": 0.9, "reason": "user said fix it"}


def test_parse_markdown_fenced_json():
    resp = '```json\n{"category": "rejection", "confidence": 0.8, "reason": "stop"}\n```'
    out = pushback.parse(resp)
    assert out["category"] == "rejection"
    assert out["confidence"] == 0.8


def test_parse_json_embedded_in_prose():
    resp = 'Here is my answer: {"category": "failure_report", "confidence": 0.7, "reason": "error"} hope it helps'
    out = pushback.parse(resp)
    assert out["category"] == "failure_report"


def test_parse_malformed_returns_default():
    out = pushback.parse("I cannot classify this message.")
    assert out["category"] == "none"
    assert out["confidence"] == 0.0


def test_parse_fills_missing_keys():
    out = pushback.parse('{"category": "correction"}')
    assert out["category"] == "correction"
    assert out["confidence"] == 0.0
    assert out["reason"] == ""


def test_parse_invalid_category_falls_back_to_none():
    out = pushback.parse('{"category": "angry", "confidence": 0.5, "reason": "x"}')
    assert out["category"] == "none"


# ── schema ─────────────────────────────────────────────────────────────

def test_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(pushback.SCHEMA)


def test_schema_round_trips_through_json():
    assert json.loads(json.dumps(pushback.SCHEMA)) == pushback.SCHEMA


def test_schema_enum_matches_parse_categories():
    enum = set(pushback.SCHEMA["properties"]["category"]["enum"])
    assert enum == {"correction", "rejection", "failure_report", "none"}
