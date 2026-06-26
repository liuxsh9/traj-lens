"""Tests for change_acceptance rule annotator."""
import json

from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem
from trajlens.annotate.rules import change_acceptance as ca


def _call(name, args, call_id="c1"):
    return FunctionCallItem(name=name, arguments=json.dumps(args), call_id=call_id,
                            step_id=0, run_id=0)


def _bash(cmd, call_id="c1"):
    return _call("bash", {"command": cmd}, call_id=call_id)


def _output(text, call_id="c1"):
    return FunctionCallOutputItem(call_id=call_id, output=text, step_id=0, run_id=0)


def _user(text):
    return MessageItem(role="user", content=text)


def test_no_edits_is_na():
    unit = [_bash("ls"), _output("a.py b.py"), _bash("cat a.py"), _output("...")]
    out = ca.annotate(unit, [])
    assert out["no_edits"] is True
    assert out["likelihood"] == "none"
    assert out["score"] is None


def test_edit_no_git_is_neutral_medium():
    # edits but no commit/push/test — neutral, NOT rejection
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "medium"
    assert out["score"] == 0.4
    assert out["edit_count"] == 1
    assert out["signals"] == []


def test_commit_is_high():
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git commit -am 'fix'"), _output("[main abc] fix")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "high"
    assert "git_commit" in out["signals"]


def test_push_is_strongest():
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git push origin main"), _output("To github.com...")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "high"
    assert out["score"] == 0.9
    assert "git_push" in out["signals"]


def test_add_only_is_medium():
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git add a.py"), _output("")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "medium"
    assert out["score"] == 0.5


def test_tests_passed_is_weak_positive():
    # ran tests, no error in output, no commit -> medium 0.45 (above bare 0.4)
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("pytest -q"), _output("12 passed in 1.2s")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "medium"
    assert out["score"] == 0.45
    assert "tests_passed" in out["signals"]


def test_failing_tests_not_counted():
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("pytest -q"), _output("FAILED test_a.py::test_x - AssertionError")]
    out = ca.annotate(unit, [])
    assert "tests_passed" not in out["signals"]
    assert out["score"] == 0.4  # back to bare neutral


def test_user_reject_vetoes_commit():
    # even with a commit, an explicit user rejection caps at low
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git commit -am wip"), _output("[main abc] wip"),
            _user("undo that, it's wrong")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "low"
    assert out["score"] <= 0.2
    assert "user_reject" in out["signals"]


def test_git_revert_vetoes():
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git push"), _output("done"),
            _bash("git reset --hard HEAD~1"), _output("HEAD is now at...")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "low"
    assert "git_revert" in out["signals"]


def test_branch_ops_not_vetoed():
    # `git checkout -b` (new branch) and bare stash are NOT rejection signals
    unit = [_call("edit", {"file_path": "a.py"}), _output("ok"),
            _bash("git checkout -b feature"), _output("Switched to a new branch"),
            _bash("git commit -am wip"), _output("[feature abc] wip")]
    out = ca.annotate(unit, [])
    assert out["likelihood"] == "high"  # commit stands, checkout -b didn't veto
    assert "git_revert" not in out["signals"]


def test_shell_edit_via_apply_patch():
    # codex routes edits through shell — apply_patch counts as an edit
    unit = [_call("shell_command", {"command": "apply_patch <<'EOF'\n*** Begin Patch"}),
            _output("ok")]
    out = ca.annotate(unit, [])
    assert out["edit_count"] == 1
    assert not out.get("no_edits")  # edits present -> scored branch, no no_edits key


def test_sed_read_not_counted_as_edit():
    # `sed -n ...p` is read-only — must NOT register as an edit
    unit = [_bash("sed -n '1,20p' a.py"), _output("...lines...")]
    out = ca.annotate(unit, [])
    assert out["no_edits"] is True
