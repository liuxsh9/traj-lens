"""Tests for error_recovery rule annotator."""
import json

from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem
from trajlens.annotate.rules import error_recovery


def _call(name, args, call_id="c1"):
    return FunctionCallItem(name=name, arguments=json.dumps(args), call_id=call_id,
                            step_id=0, run_id=0)


def _output(text, call_id="c1", step_id=0, run_id=0):
    return FunctionCallOutputItem(call_id=call_id, output=text,
                                  step_id=step_id, run_id=run_id)


def test_no_error():
    unit = [_call("edit", {"file_path": "a.py"}),
            _output("ok")]
    out = error_recovery.annotate(unit, unit)
    assert out == {"has_error": False, "recovered": None, "error_summary": None}


def test_error_detected():
    unit = [_call("bash", {"command": "pytest"}),
            _output("FAILED test_foo.py::test_bar - AssertionError")]
    out = error_recovery.annotate(unit, unit)
    assert out["has_error"] is True
    assert out["recovered"] is None  # no next step in ctx


def test_error_with_recovery():
    step0 = [FunctionCallItem(name="bash", arguments='{"command":"pytest"}',
                              call_id="c1", step_id=0, run_id=0),
             _output("FAILED test_foo.py", step_id=0)]
    step1 = [FunctionCallItem(name="edit", arguments='{"file_path":"foo.py"}',
                              call_id="c2", step_id=1, run_id=0),
             _output("ok", call_id="c2", step_id=1)]
    ctx = step0 + step1
    out = error_recovery.annotate(step0, ctx)
    assert out["has_error"] is True
    assert out["recovered"] is True  # different tool = strategy change


def test_error_without_recovery():
    step0 = [FunctionCallItem(name="bash", arguments='{"command":"pytest"}',
                              call_id="c1", step_id=0, run_id=0),
             _output("FAILED test_foo.py", step_id=0)]
    step1 = [FunctionCallItem(name="bash", arguments='{"command":"pytest"}',
                              call_id="c2", step_id=1, run_id=0),
             _output("FAILED test_foo.py", call_id="c2", step_id=1)]
    ctx = step0 + step1
    out = error_recovery.annotate(step0, ctx)
    assert out["has_error"] is True
    assert out["recovered"] is False  # same tool signature = no strategy change


def test_python_code_change_counts_as_recovery():
    step0 = [FunctionCallItem(name="PythonInterpreter",
                              arguments=json.dumps({"code": "import os; try: open('words_alpha.txt'); except: pass"}),
                              call_id="c1", step_id=0, run_id=0),
             _output("SyntaxError: invalid syntax\n[Command finished with exit code 1]", step_id=0)]
    step1 = [FunctionCallItem(name="PythonInterpreter",
                              arguments=json.dumps({"code": "try:\n    open('words_alpha.txt')\nexcept FileNotFoundError:\n    pass"}),
                              call_id="c2", step_id=1, run_id=0),
             _output("ok", call_id="c2", step_id=1)]

    out = error_recovery.annotate(step0, step0 + step1)

    assert out["has_error"] is True
    assert out["recovered"] is True


def test_bash_command_change_counts_as_recovery():
    step0 = [FunctionCallItem(name="execute_bash",
                              arguments=json.dumps({"command": "python -c 'import barril'"}),
                              call_id="c1", step_id=0, run_id=0),
             _output("ModuleNotFoundError: No module named 'barril'\n[Command finished with exit code 1]", step_id=0)]
    step1 = [FunctionCallItem(name="execute_bash",
                              arguments=json.dumps({"command": 'pip install -e ".[testing]"'}),
                              call_id="c2", step_id=1, run_id=0),
             _output("Successfully installed", call_id="c2", step_id=1)]

    out = error_recovery.annotate(step0, step0 + step1)

    assert out["has_error"] is True
    assert out["recovered"] is True


def test_exit_code_nonzero():
    unit = [_call("bash", {"command": "make"}),
            _output("exit code 1")]
    out = error_recovery.annotate(unit, unit)
    assert out["has_error"] is True


def test_grep_no_match_exit_one_is_not_error():
    unit = [_call("bash", {"command": "grep -rn 'needle' src/"}),
            _output("[The command completed with exit code 1]\n[Command finished with exit code 1]")]

    out = error_recovery.annotate(unit, unit)

    assert out["has_error"] is False


def test_exit_code_zero_not_error():
    unit = [_call("bash", {"command": "make"}),
            _output("exit code 0")]
    out = error_recovery.annotate(unit, unit)
    assert out["has_error"] is False


def test_traceback_detected():
    unit = [_call("bash", {"command": "python x.py"}),
            _output("Traceback (most recent call last):\n  File...")]
    out = error_recovery.annotate(unit, unit)
    assert out["has_error"] is True


def test_error_summary_prefers_pytest_failed_line():
    output = (
        "============================= test session starts ==============================\n"
        "platform linux -- Python 3.12\n"
        "FAILED tests/test_units.py::test_default_category - AssertionError\n"
        "[Command finished with exit code 1]"
    )
    unit = [_call("bash", {"command": "pytest"}), _output(output)]

    out = error_recovery.annotate(unit, unit)

    assert out["has_error"] is True
    assert out["error_summary"].startswith("FAILED tests/test_units.py::test_default_category")
