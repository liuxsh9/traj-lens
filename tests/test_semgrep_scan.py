import json
import os
import tempfile

from trajlens.core.code_changes import extract_changes
from trajlens.core.model import FunctionCallItem
from trajlens.core import semgrep_scan as ss


def test_materialize_encodes_item_idx_and_skips_non_writes():
    items = [
        FunctionCallItem(name="write_file", call_id="1",
                         arguments=json.dumps({"filePath": "/app/x.py", "content": "x = 1\n"})),
        FunctionCallItem(name="read", call_id="2",
                         arguments=json.dumps({"file_path": "/app/y.py"})),  # not scannable
        FunctionCallItem(name="execute_bash", call_id="3",
                         arguments=json.dumps({"command": "ls"})),  # run, not scannable
    ]
    chs = extract_changes(items)
    with tempfile.TemporaryDirectory() as tmp:
        assert ss._materialize(chs, tmp) == 1
        assert os.listdir(tmp) == ["0__x.py"]  # item_idx 0 baked into filename


def test_parse_findings_maps_back_to_item_idx():
    out = json.dumps({"results": [
        {"path": "/tmp/z/3__app.py", "check_id": "r.id", "start": {"line": 7},
         "extra": {"severity": "ERROR", "message": "boom"}},
        {"path": "/tmp/z/notanint__a.py", "check_id": "x", "extra": {}},  # skipped
    ]})
    f = ss._parse_findings(out)
    assert f == [{"item_idx": 3, "check_id": "r.id", "severity": "ERROR",
                  "message": "boom", "line": 7}]


def test_parse_findings_handles_garbage():
    assert ss._parse_findings("not json") == []


def test_scan_changes_graceful_when_semgrep_absent(monkeypatch):
    monkeypatch.setattr(ss, "semgrep_available", lambda: False)
    res = ss.scan_changes([FunctionCallItem(name="write_file", call_id="1",
                           arguments=json.dumps({"filePath": "/a.py", "content": "x=1"}))])
    assert res == {"available": False, "scanned": 0, "findings": []}
