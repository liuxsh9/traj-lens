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
import shutil
import subprocess
import tempfile

from trajlens.core.code_changes import extract_changes

# how the temp filename encodes the originating item index: "<idx>__<basename>"
_SEP = "__"
_SCANNABLE_OPS = {"create", "edit"}


def semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def ruleset_version() -> str:
    """Cache/staleness key. semgrep's own version is a good proxy — the bundled
    `--config auto` rules move with releases, so a version bump invalidates caches.

    Not memoized on purpose: the server is long-lived, so caching the version in
    process would make a mid-session `semgrep upgrade` invisible and freeze stored
    scans as fresh forever. `--version` is ~tens of ms; a scan is seconds."""
    try:
        out = subprocess.run(["semgrep", "--version"], capture_output=True,
                             text=True, timeout=10)
        return "semgrep-" + (out.stdout.strip() or "unknown")
    except Exception:
        return "semgrep-unknown"


def _write(content: str, path: str, idx: int, root: str) -> None:
    base = os.path.basename(path) or "file"
    with open(os.path.join(root, f"{idx}{_SEP}{base}"), "w") as f:
        f.write(content)


def _materialize(changes, base_dir: str, head_dir: str) -> int:
    """Write each scannable change's `new` to head_dir and its `old` (if any) to
    base_dir, filename = <idx>__<basename>. Returns the head count (= fragments
    actually scanned for the post-edit state). A create has no `old`, so its
    baseline is empty and all its findings count as introduced.
    """
    n = 0
    for c in changes:
        if c.op not in _SCANNABLE_OPS or not c.new or not c.path:
            continue
        _write(c.new, c.path, c.item_idx, head_dir)
        if c.old:
            _write(c.old, c.path, c.item_idx, base_dir)
        n += 1
    return n


def _parse_findings(stdout: str) -> list[dict]:
    """Map semgrep JSON back to item-indexed findings, tagged with side (base/head)
    via the parent dir the fragment was written into."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for r in data.get("results", []):
        p = r.get("path", "")
        name = os.path.basename(p)
        side = "base" if f"{os.sep}base{os.sep}" in p else "head"
        idx_str = name.split(_SEP, 1)[0]
        try:
            item_idx = int(idx_str)
        except ValueError:
            continue
        extra = r.get("extra", {})
        out.append({
            "side": side,
            "item_idx": item_idx,
            "check_id": r.get("check_id", ""),
            "severity": extra.get("severity", "INFO"),
            "message": extra.get("message", ""),
            "line": (r.get("start") or {}).get("line"),
        })
    return out


def _diff_findings(parsed: list[dict]) -> list[dict]:
    """Keep head-side findings, tagging each `introduced` = its (item_idx, check_id)
    was NOT present pre-edit. A finding on both sides is pre-existing (the agent
    inherited it), so it's not attributed to this edit.

    ponytail: matches on (item_idx, check_id), not line — old/new line numbers
    drift. Upgrade path if needed: count-aware diff (2 new vs 1 old of same rule).
    """
    base_keys = {(f["item_idx"], f["check_id"]) for f in parsed if f["side"] == "base"}
    out = []
    for f in parsed:
        if f["side"] != "head":
            continue
        g = {k: v for k, v in f.items() if k != "side"}
        g["introduced"] = (f["item_idx"], f["check_id"]) not in base_keys
        out.append(g)
    return out


def scan_changes(items, timeout: int = 120) -> dict:
    """Diff-scan code changes: scan both pre-edit (old) and post-edit (new)
    fragments, attribute each post-edit finding as introduced-by-this-agent or
    pre-existing.

    Returns {available, scanned, findings: [...with introduced bool], introduced_count, ...}.
    """
    if not semgrep_available():
        return {"available": False, "scanned": 0, "findings": [], "introduced_count": 0}

    rv = ruleset_version()
    changes = extract_changes(items)
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = os.path.join(tmp, "base")
        head_dir = os.path.join(tmp, "head")
        os.makedirs(base_dir)
        os.makedirs(head_dir)
        n = _materialize(changes, base_dir, head_dir)
        if n == 0:
            return {"available": True, "scanned": 0, "findings": [],
                    "introduced_count": 0, "ruleset_version": rv}
        try:
            proc = subprocess.run(
                ["semgrep", "scan", "--config", "auto", "--json", "--quiet", tmp],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"available": True, "scanned": n, "findings": [], "error": "timeout",
                    "introduced_count": 0, "ruleset_version": rv}
        findings = _diff_findings(_parse_findings(proc.stdout))
        introduced = sum(1 for f in findings if f["introduced"])
        return {"available": True, "scanned": n, "findings": findings,
                "introduced_count": introduced, "ruleset_version": rv}


if __name__ == "__main__":
    # self-check: diff attribution without needing semgrep installed.
    # rule A is in both old+new of item 14 -> pre-existing (not introduced).
    # rule B is only in new of item 14 -> introduced.
    parsed = [
        {"side": "base", "item_idx": 14, "check_id": "A", "severity": "ERROR", "message": "a", "line": 1},
        {"side": "head", "item_idx": 14, "check_id": "A", "severity": "ERROR", "message": "a", "line": 3},
        {"side": "head", "item_idx": 14, "check_id": "B", "severity": "WARNING", "message": "b", "line": 5},
    ]
    diffed = _diff_findings(parsed)
    assert len(diffed) == 2  # only head-side findings kept
    by = {f["check_id"]: f["introduced"] for f in diffed}
    assert by == {"A": False, "B": True}, by  # A pre-existing, B introduced
    assert all("side" not in f for f in diffed)
    print("ok: available=%s, diff attribution passed" % semgrep_available())
