import json

from trajlens.adapters import detect_and_parse
from trajlens.core.grouping import assign_groups
from trajlens.core.code_changes import extract_changes
from trajlens.core.model import FunctionCallItem, MessageItem


def test_classifies_edit_create_run_and_skips_reads():
    items = [
        MessageItem(role="user", content="go"),
        FunctionCallItem(name="str_replace_editor", call_id="1",
                         arguments=json.dumps({"command": "view", "path": "/a.py"})),  # read -> skip
        FunctionCallItem(name="str_replace_editor", call_id="2",
                         arguments=json.dumps({"command": "str_replace", "path": "/a.py",
                                               "old_str": "x", "new_str": "y"})),
        FunctionCallItem(name="write_file", call_id="3",
                         arguments=json.dumps({"filePath": "/b.py", "content": "1"})),
        FunctionCallItem(name="execute_bash", call_id="4",
                         arguments=json.dumps({"command": "pytest"})),
        FunctionCallItem(name="read", call_id="5",
                         arguments=json.dumps({"file_path": "/c.py"})),  # read -> skip
    ]
    chs = extract_changes(items)
    assert [(c.op, c.tool) for c in chs] == [("edit", "edit"), ("create", "write"), ("run", "bash")]
    assert chs[0].path == "/a.py" and chs[0].new == "y"
    assert chs[1].old is None  # create has no "before"


def test_bash_rm_classified_as_delete_compound_stays_run():
    items = [
        FunctionCallItem(name="bash", call_id="1",
                         arguments=json.dumps({"command": "rm -rf build/old.py"})),
        FunctionCallItem(name="bash", call_id="2",
                         arguments=json.dumps({"command": "touch new.txt"})),
        FunctionCallItem(name="bash", call_id="3",
                         arguments=json.dumps({"command": "rm a.py && echo ok"})),
    ]
    chs = extract_changes(items)
    assert (chs[0].op, chs[0].path) == ("delete", "build/old.py")
    assert (chs[1].op, chs[1].path) == ("create", "new.txt")
    assert chs[2].op == "run"  # compound -> not reclassified


def test_bad_arguments_dont_crash():
    items = [FunctionCallItem(name="edit", call_id="x", arguments="not json")]
    assert extract_changes(items) == []


def test_codex_shell_command_extracted(tmp_path):
    """Regression: codex uses 'shell_command', which must alias to bash."""
    rows = [json.loads(l) for l in
            open("tests/samples/codex/codex_medium.jsonl") if l.strip()]
    traj, fmt = detect_and_parse(rows)
    assert fmt == "codex"
    chs = extract_changes(assign_groups(traj.items))
    assert len(chs) > 0
    assert all(c.op == "run" and c.tool == "bash" for c in chs)
    assert chs[0].step_id is not None  # grouping carried through
