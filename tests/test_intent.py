"""Tests for intent LLM annotator — build() and parse() only (no LLM calls)."""
from trajlens.core.model import MessageItem
from trajlens.annotate.llm import intent


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


def test_parse_garbage():
    assert intent.parse("not json at all")["intent"] == "other"


def test_schema_has_all_intents():
    assert set(intent.SCHEMA["properties"]["intent"]["enum"]) == {
        "implement", "debug", "refactor", "explain", "other"}
