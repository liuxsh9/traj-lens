from trajlens.core.identity import content_hash
from trajlens.core.model import (
    MessageItem, FunctionCallItem, FunctionCallOutputItem, Provenance,
)


def _convo(call_id, ts_origin):
    return [
        MessageItem(role="system", content="You are an agent."),
        MessageItem(role="user", content="Read a.py"),
        FunctionCallItem(name="Read", arguments='{"path": "a.py"}', call_id=call_id,
                         provenance=Provenance(origin=ts_origin)),
        FunctionCallOutputItem(call_id=call_id, output="print(1)"),
    ]


def test_volatile_meta_excluded_same_hash():
    # different call_id + different provenance.origin -> SAME content hash
    a = content_hash(_convo("call_aaa", "x"))
    b = content_hash(_convo("call_zzz", "y"))
    assert a == b


def test_argument_whitespace_normalized():
    a = content_hash([FunctionCallItem(name="f", arguments='{"a":1,"b":2}', call_id="1")])
    b = content_hash([FunctionCallItem(name="f", arguments='{"b": 2, "a": 1}', call_id="2")])
    assert a == b


def test_different_content_differs():
    a = content_hash([MessageItem(role="user", content="hi")])
    b = content_hash([MessageItem(role="user", content="bye")])
    assert a != b


def test_tools_included():
    items = [MessageItem(role="user", content="hi")]
    a = content_hash(items, tools=[])
    b = content_hash(items, tools=[{"type": "function", "function": {"name": "f"}}])
    assert a != b
