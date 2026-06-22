import json

from tests.conftest import FIXTURES
from trajlens.adapters import detect_and_parse


def _load():
    return json.loads((FIXTURES / "panguml2_weather.json").read_text())


def test_parses_into_typed_items():
    t = detect_and_parse(_load())
    types = [it.type for it in t.items]
    assert types == [
        "message",            # system
        "message",            # user
        "reasoning",          # assistant.reasoning_content
        "function_call",      # assistant.tool_calls[0]
        "function_call_output",  # tool
        "message",            # final assistant
    ]


def test_provenance_and_hash_set():
    t = detect_and_parse(_load())
    assert len(t.content_hash) == 64
    fc = next(it for it in t.items if it.type == "function_call")
    assert fc.provenance.origin == "messages[2].tool_calls[0]"
    assert fc.provenance.content_hash == t.content_hash
    assert t.meta["teacher"] == "glm-5-thinking"


def test_tool_output_keeps_call_pairing():
    t = detect_and_parse(_load())
    call = next(it for it in t.items if it.type == "function_call")
    out = next(it for it in t.items if it.type == "function_call_output")
    assert call.call_id == out.call_id == "call_bj"
