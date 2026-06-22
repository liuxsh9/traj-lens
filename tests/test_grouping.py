from trajlens.core.grouping import assign_groups
from trajlens.core.model import (
    MessageItem, ReasoningItem, FunctionCallItem, FunctionCallOutputItem,
)


def _long_run():
    # 1 user prompt, then an autonomous run of 2 think-act-observe steps
    return [
        MessageItem(role="user", content="fix it"),
        ReasoningItem(content="step A think"),
        FunctionCallItem(name="Read", arguments="{}", call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="..."),
        ReasoningItem(content="step B think"),
        FunctionCallItem(name="Edit", arguments="{}", call_id="c2"),
        FunctionCallOutputItem(call_id="c2", output="..."),
        MessageItem(role="assistant", content="done"),
    ]


def test_single_prompt_long_run_not_two_groups():
    g = assign_groups(_long_run())
    assert g[0].run_id is None and g[0].step_id is None          # user turn
    assert all(it.run_id == 0 for it in g[1:])                   # one assistant run
    steps = {it.step_id for it in g[1:]}
    assert steps == {0, 1}                                       # two steps, not one blob


def test_reasoning_starts_new_step():
    g = assign_groups(_long_run())
    # step 0 = think A + Read + output ; step 1 = think B + Edit + output + msg
    assert [it.step_id for it in g[1:]] == [0, 0, 0, 1, 1, 1, 1]


def test_tool_loop_without_reasoning_splits_on_second_act():
    items = [
        MessageItem(role="user", content="loop"),
        FunctionCallItem(name="Bash", arguments="{}", call_id="a"),
        FunctionCallOutputItem(call_id="a", output="fail"),
        FunctionCallItem(name="Bash", arguments="{}", call_id="b"),
        FunctionCallOutputItem(call_id="b", output="ok"),
    ]
    g = assign_groups(items)
    assert [it.step_id for it in g[1:]] == [0, 0, 1, 1]


def test_second_user_turn_opens_new_run():
    items = [
        MessageItem(role="user", content="a"),
        FunctionCallItem(name="X", arguments="{}", call_id="1"),
        MessageItem(role="user", content="b"),
        FunctionCallItem(name="Y", arguments="{}", call_id="2"),
    ]
    g = assign_groups(items)
    assert g[1].run_id == 0
    assert g[3].run_id == 1
