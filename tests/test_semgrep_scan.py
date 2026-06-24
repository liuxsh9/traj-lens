import json
import os
import tempfile

from trajlens.core.code_changes import extract_changes
from trajlens.core.model import FunctionCallItem
from trajlens.core import semgrep_scan as ss


def test_materialize_writes_head_and_base():
    items = [
        # create: head only (no old) -> baseline empty
        FunctionCallItem(name="write_file", call_id="1",
                         arguments=json.dumps({"filePath": "/app/x.py", "content": "x = 1\n"})),
        # edit: both old (base) and new (head)
        FunctionCallItem(name="str_replace_editor", call_id="2",
                         arguments=json.dumps({"command": "str_replace", "path": "/app/y.py",
                                               "old_str": "a", "new_str": "b"})),
        FunctionCallItem(name="read", call_id="3",
                         arguments=json.dumps({"file_path": "/app/z.py"})),  # not scannable
    ]
    chs = extract_changes(items)
    with tempfile.TemporaryDirectory() as tmp:
        base, head = os.path.join(tmp, "base"), os.path.join(tmp, "head")
        os.makedirs(base); os.makedirs(head)
        assert ss._materialize(chs, base, head) == 2          # 2 head fragments
        assert sorted(os.listdir(head)) == ["0__x.py", "1__y.py"]
        assert os.listdir(base) == ["1__y.py"]                # only the edit has an old side


def test_parse_findings_tags_side_and_item_idx():
    out = json.dumps({"results": [
        {"path": "/tmp/head/3__app.py", "check_id": "r.id", "start": {"line": 7},
         "extra": {"severity": "ERROR", "message": "boom"}},
        {"path": "/tmp/base/3__app.py", "check_id": "r.id",
         "extra": {"severity": "ERROR", "message": "boom"}},
        {"path": "/tmp/head/notanint__a.py", "check_id": "x", "extra": {}},  # skipped
    ]})
    f = ss._parse_findings(out)
    assert len(f) == 2
    assert f[0]["side"] == "head" and f[1]["side"] == "base"


def test_diff_attributes_introduced():
    parsed = [
        {"side": "base", "item_idx": 1, "check_id": "A", "severity": "E", "message": "m", "line": 1},
        {"side": "head", "item_idx": 1, "check_id": "A", "severity": "E", "message": "m", "line": 3},  # pre-existing
        {"side": "head", "item_idx": 1, "check_id": "B", "severity": "W", "message": "m", "line": 5},  # introduced
    ]
    d = ss._diff_findings(parsed)
    assert {f["check_id"]: f["introduced"] for f in d} == {"A": False, "B": True}
    assert all("side" not in f for f in d)


def test_parse_findings_handles_garbage():
    assert ss._parse_findings("not json") == []


def test_scan_changes_graceful_when_semgrep_absent(monkeypatch):
    monkeypatch.setattr(ss, "semgrep_available", lambda: False)
    res = ss.scan_changes([FunctionCallItem(name="write_file", call_id="1",
                           arguments=json.dumps({"filePath": "/a.py", "content": "x=1"}))])
    assert res == {"available": False, "scanned": 0, "findings": [], "introduced_count": 0}
