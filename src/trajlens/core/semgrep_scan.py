"""Semgrep security scan over code extracted from tool calls (slice-5, §1).

Scans the file-content fragments that code_changes pulls out of write/edit tool
calls — no artifacts table, no checkout, just the bytes the agent wrote. Semgrep
is an *optional external CLI*: present -> scan; absent -> graceful no-op with
available=False so the UI can say "install semgrep". We never make it a hard
project dependency (it drags a large transitive tree).

Run on demand (it shells out + `--config auto` fetches rules over the network),
not on every detail fetch.
"""

import json
import os
import functools
import shutil
import subprocess
import tempfile

from trajlens.core.code_changes import extract_changes

# how the temp filename encodes the originating item index: "<idx>__<basename>"
_SEP = "__"
_SCANNABLE_OPS = {"create", "edit"}


def semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


@functools.lru_cache(maxsize=1)
def ruleset_version() -> str:
    """Cache/staleness key. semgrep's own version is a good proxy — the bundled
    `--config auto` rules move with releases, so a version bump invalidates caches."""
    try:
        out = subprocess.run(["semgrep", "--version"], capture_output=True,
                             text=True, timeout=10)
        return "semgrep-" + (out.stdout.strip() or "unknown")
    except Exception:
        return "semgrep-unknown"


def _materialize(changes, tmpdir: str) -> int:
    """Write each scannable change's `new` content to <tmpdir>/<idx>__<basename>.
    Returns the count written. Filename carries item_idx so findings map back.
    """
    written = 0
    for c in changes:
        if c.op not in _SCANNABLE_OPS or not c.new or not c.path:
            continue
        base = os.path.basename(c.path) or "file"
        with open(os.path.join(tmpdir, f"{c.item_idx}{_SEP}{base}"), "w") as f:
            f.write(c.new)
        written += 1
    return written


def _parse_findings(stdout: str) -> list[dict]:
    """Map semgrep JSON output back to item-indexed findings."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for r in data.get("results", []):
        name = os.path.basename(r.get("path", ""))
        idx_str = name.split(_SEP, 1)[0]
        try:
            item_idx = int(idx_str)
        except ValueError:
            continue
        extra = r.get("extra", {})
        out.append({
            "item_idx": item_idx,
            "check_id": r.get("check_id", ""),
            "severity": extra.get("severity", "INFO"),
            "message": extra.get("message", ""),
            "line": (r.get("start") or {}).get("line"),
        })
    return out


def scan_changes(items, timeout: int = 120) -> dict:
    """Extract code changes from items, scan with semgrep if available.

    Returns {available: bool, scanned: int, findings: [...], error?: str}.
    """
    if not semgrep_available():
        return {"available": False, "scanned": 0, "findings": []}

    rv = ruleset_version()
    changes = extract_changes(items)
    with tempfile.TemporaryDirectory() as tmp:
        n = _materialize(changes, tmp)
        if n == 0:
            return {"available": True, "scanned": 0, "findings": [], "ruleset_version": rv}
        try:
            proc = subprocess.run(
                ["semgrep", "scan", "--config", "auto", "--json", "--quiet", tmp],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"available": True, "scanned": n, "findings": [], "error": "timeout",
                    "ruleset_version": rv}
        findings = _parse_findings(proc.stdout)
        return {"available": True, "scanned": n, "findings": findings, "ruleset_version": rv}


if __name__ == "__main__":
    # self-check: materialize + parse round-trip without needing semgrep.
    from trajlens.core.model import FunctionCallItem

    items = [
        FunctionCallItem(name="write_file", call_id="1",
                         arguments=json.dumps({"filePath": "/app/x.py",
                                               "content": "x = 1\nprint(x)\n"})),
        FunctionCallItem(name="read", call_id="2",
                         arguments=json.dumps({"file_path": "/app/y.py"})),  # not scannable
    ]
    chs = extract_changes(items)
    with tempfile.TemporaryDirectory() as tmp:
        assert _materialize(chs, tmp) == 1
        files = os.listdir(tmp)
        assert files == ["0__x.py"], files  # item_idx 0 encoded in name

    fake = json.dumps({"results": [{
        "path": "/tmp/zz/0__x.py", "check_id": "rule.id",
        "start": {"line": 2},
        "extra": {"severity": "ERROR", "message": "example finding"},
    }]})
    f = _parse_findings(fake)
    assert f == [{"item_idx": 0, "check_id": "rule.id",
                  "severity": "ERROR", "message": "example finding", "line": 2}], f
    print("ok: available=%s, parse+materialize round-trip passed" % semgrep_available())
