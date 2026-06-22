from trajlens.core.model import (
    Trajectory, MessageItem, FunctionCallItem, parse_item,
)


def test_discriminated_round_trip():
    items = [
        MessageItem(role="user", content="hi"),
        FunctionCallItem(name="Read", arguments='{"path":"a.py"}', call_id="c1"),
    ]
    t = Trajectory(content_hash="h", items=items, tools=[], meta={})
    dumped = t.model_dump()
    assert dumped["items"][0]["type"] == "message"
    assert dumped["items"][1]["type"] == "function_call"


def test_parse_item_rebuilds_subtype():
    it = parse_item({"type": "reasoning", "content": "think"})
    assert it.type == "reasoning"
    assert it.content == "think"
