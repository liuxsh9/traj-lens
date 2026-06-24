"""Tests for tool_aliases canonical mapping."""
from trajlens.core.tool_aliases import canonical, BASH_TOOLS, EDIT_TOOLS, READ_TOOLS


def test_bash_variants():
    for name in ("bash", "Bash", "execute_bash", "terminal", "run_command", "shell"):
        assert canonical(name) in BASH_TOOLS, f"{name} should map to bash"


def test_edit_variants():
    for name in ("edit", "Edit", "str_replace_editor", "replace_all", "write", "Write",
                  "write_to_file", "create_file", "apply_diff", "insert_content"):
        assert canonical(name) in EDIT_TOOLS, f"{name} should map to edit/write"


def test_read_variants():
    for name in ("read", "Read", "read_file", "cat", "view", "glob", "Glob", "grep", "find"):
        assert canonical(name) in READ_TOOLS, f"{name} should map to read/search"


def test_unknown_passes_through_lowercased():
    assert canonical("PythonInterpreter") == "pythoninterpreter"
    assert canonical("custom_tool") == "custom_tool"


def test_case_insensitive():
    assert canonical("Execute_Bash") == "bash"
    assert canonical("STR_REPLACE_EDITOR") == "edit"
