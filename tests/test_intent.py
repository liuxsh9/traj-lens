"""Tests for intent LLM annotator — build() and parse() only (no LLM calls)."""
import pytest

from trajlens.core.model import MessageItem
from trajlens.annotate.llm import UnparseableResponse, intent


def _user(text):
    return MessageItem(role="user", content=text)


def _assistant(text):
    return MessageItem(role="assistant", content=text)


def test_build_basic():
    unit = [_user("add a login page")]
    msgs = intent.build(unit, unit)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "implement" in msgs[0]["content"]
    assert "login page" in msgs[1]["content"]


def test_build_with_context():
    ctx = [_user("setup the project"), _assistant("done"), _user("now add auth")]
    unit = ctx[-1:]
    msgs = intent.build(unit, ctx)
    assert "done" in msgs[1]["content"]  # context summary includes prior assistant


def test_parse_valid_json():
    assert intent.parse('{"intent": "debug", "reason": "reports bug"}') == {
        "intent": "debug", "reason": "reports bug"}


def test_parse_markdown_fences():
    assert intent.parse('```json\n{"intent": "implement", "reason": "new feature"}\n```')["intent"] == "implement"


def test_parse_unknown_intent_falls_back():
    assert intent.parse('{"intent": "unknown_category", "reason": "x"}')["intent"] == "other"


def test_parse_garbage_raises():
    # Unparseable → raise, not a fabricated "other". runner.py then records the
    # error and writes no annotation, so a re-run retries the target.
    with pytest.raises(UnparseableResponse):
        intent.parse("not json at all")


def test_schema_has_all_intents():
    assert set(intent.SCHEMA["properties"]["intent"]["enum"]) == {
        "implement", "debug", "refactor", "explain", "other"}
