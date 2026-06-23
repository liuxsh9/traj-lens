"""Tests for metrics computation, staleness, and success scoring."""
import json

from trajlens.core.model import Trajectory
from trajlens.core.identity import content_hash
from trajlens.store import db as dbmod, repo

import trajlens.metrics.builtins  # noqa: F401 — register built-ins
from trajlens.metrics import compute_metrics, REGISTRY


def _make_traj():
    """Minimal trajectory with 2 user turns, 3 tool calls, multiple steps."""
    items_raw = [
        {"type": "message", "role": "user", "content": "fix the bug"},
        {"type": "reasoning", "content": "thinking..."},
        {"type": "function_call", "name": "read", "arguments": "{}", "call_id": "c1"},
        {"type": "function_call_output", "call_id": "c1", "output": "file contents"},
        {"type": "function_call", "name": "edit", "arguments": "{}", "call_id": "c2"},
        {"type": "function_call_output", "call_id": "c2", "output": "ok"},
        {"type": "message", "role": "assistant", "content": "done"},
        {"type": "message", "role": "user", "content": "no, that's wrong"},
        {"type": "function_call", "name": "edit", "arguments": "{}", "call_id": "c3"},
        {"type": "function_call_output", "call_id": "c3", "output": "ok"},
        {"type": "message", "role": "assistant", "content": "fixed"},
    ]
    from trajlens.core.model import parse_item
    from trajlens.core.grouping import assign_groups
    items = [parse_item(it) for it in items_raw]
    items = assign_groups(items)
    ch = content_hash(items)
    return Trajectory(content_hash=ch, items=items)


def _db(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    return conn


def _add_annotations(conn, traj, pushback_labels, resolution_label):
    """Helper: register annotators and add pushback + resolution annotations."""
    from trajlens.annotate import enumerate_targets, Target

    repo.register_annotator(conn, id="pushback", version="v1", config_hash="v1")
    targets = enumerate_targets(traj, Target.USER_TURN)
    for i, label in enumerate(pushback_labels):
        th, _, _ = targets[i]
        # ponytail: target_idx starts at 1 — idx=0 is the initial task, never pushback
        repo.link_annotation_target(conn, target_hash=th, content_hash=traj.content_hash,
                                    target_type="user_turn", target_idx=i + 1)
        conn.commit()
        repo.put_annotation(conn, target_hash=th, annotator_id="pushback",
                            annotator_version="v1",
                            value={"category": label, "reason": "test"},
                            inputs_hash=f"pb{i}")

    if resolution_label:
        repo.register_annotator(conn, id="resolution", version="r1", config_hash="r1")
        sess_targets = enumerate_targets(traj, Target.SESSION)
        sth, _, _ = sess_targets[0]
        repo.link_annotation_target(conn, target_hash=sth, content_hash=traj.content_hash,
                                    target_type="session", target_idx=0)
        conn.commit()
        repo.put_annotation(conn, target_hash=sth, annotator_id="resolution",
                            annotator_version="r1",
                            value={"resolution": resolution_label, "reason": "test"},
                            inputs_hash="res0")


# ── Registry ──────────────────────────────────────────────────────────

def test_registry_has_builtins():
    assert "turn_count" in REGISTRY
    assert "step_count" in REGISTRY
    assert "tool_count" in REGISTRY
    assert "pushback_count" in REGISTRY
    assert "success_score" in REGISTRY


def test_registry_depends_on():
    _, _, deps = REGISTRY["pushback_count"]
    assert "pushback" in deps
    _, _, deps = REGISTRY["success_score"]
    assert "resolution" in deps and "pushback" in deps


# ── Basic metrics ─────────────────────────────────────────────────────

def test_compute_basic_metrics(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)

    results = compute_metrics(conn, traj.content_hash)

    assert results["turn_count"] == 2
    assert results["tool_count"] == 3
    assert results["step_count"] >= 1
    assert results["pushback_count"] == 0
    assert results["success_score"] is None  # no resolution annotation


def test_metrics_cached(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)

    r1 = compute_metrics(conn, traj.content_hash)
    r2 = compute_metrics(conn, traj.content_hash)
    assert r1 == r2

    stored = repo.get_metrics_for_trajectory(conn, traj.content_hash)
    assert stored["turn_count"] == 2


def test_list_with_metrics(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    compute_metrics(conn, traj.content_hash)

    rows = repo.list_trajectories_with_metrics(conn)
    assert len(rows) == 1
    assert rows[0]["metrics"]["turn_count"] == 2
    assert "annotations" in rows[0]


# ── Pushback count ────────────────────────────────────────────────────

def test_pushback_count_with_annotations(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], None)

    results = compute_metrics(conn, traj.content_hash)
    assert results["pushback_count"] == 1


# ── Success score ─────────────────────────────────────────────────────

def test_success_score_resolved_no_pushback(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "none"], "resolved")

    results = compute_metrics(conn, traj.content_hash)
    assert results["success_score"] == 100


def test_success_score_resolved_with_pushback(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], "resolved")

    results = compute_metrics(conn, traj.content_hash)
    # 100 base - 5 penalty for 1 pushback = 95
    assert results["success_score"] == 95


def test_success_score_unresolved(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], "unresolved")

    results = compute_metrics(conn, traj.content_hash)
    assert results["success_score"] == 0


def test_success_score_indeterminate_returns_none(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "none"], "indeterminate")

    results = compute_metrics(conn, traj.content_hash)
    assert results["success_score"] is None


# ── Staleness ─────────────────────────────────────────────────────────

def test_staleness_recomputes_on_annotator_version_change(tmp_path):
    """When pushback annotator version changes, pushback_count should recompute."""
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], "resolved")

    r1 = compute_metrics(conn, traj.content_hash)
    assert r1["pushback_count"] == 1

    # Simulate annotator version bump (new prompt → new version)
    repo.register_annotator(conn, id="pushback", version="v2", config_hash="v2")

    # Re-add annotations under v2 with different labels
    from trajlens.annotate import enumerate_targets, Target
    targets = enumerate_targets(traj, Target.USER_TURN)
    for i, label in enumerate(["correction", "correction"]):
        th, _, _ = targets[i]
        repo.put_annotation(conn, target_hash=th, annotator_id="pushback",
                            annotator_version="v2",
                            value={"category": label, "reason": "v2"},
                            inputs_hash=f"pb{i}v2")

    # compute_metrics should detect version mismatch and recompute
    r2 = compute_metrics(conn, traj.content_hash)
    assert r2["pushback_count"] == 2  # both are now corrections
