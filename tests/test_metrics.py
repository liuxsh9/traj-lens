"""Tests for metrics computation, staleness, and success scoring."""
import json

from trajlens.core.model import Trajectory
from trajlens.core.identity import content_hash
from trajlens.store import db as dbmod, repo

import trajlens.metrics.builtins  # noqa: F401 — register built-ins
from trajlens.metrics import compute_metrics, REGISTRY
from trajlens.annotate.runner import _invalidate_dependent_metrics, _recompute_metrics


def _make_traj(prompt: str = "fix the bug"):
    """Minimal trajectory with 2 user turns, 3 tool calls, multiple steps."""
    items_raw = [
        {"type": "message", "role": "user", "content": prompt},
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


def _put_in_dataset(conn, traj, dataset_name: str):
    ds = repo.create_dataset(conn, name=dataset_name)
    batch = repo.create_batch(conn, dataset_id=ds["id"], format="test", name=f"{dataset_name}.jsonl")
    repo.put_trajectory(conn, traj, batch_id=batch["id"])
    repo.update_batch_count(conn, batch["id"], 1)
    return ds


# ── Registry ──────────────────────────────────────────────────────────

def test_registry_has_builtins():
    assert "turn_count" in REGISTRY
    assert "step_count" in REGISTRY
    assert "tool_count" in REGISTRY
    assert "pushback_count" in REGISTRY
    assert "overall_score" in REGISTRY


def test_registry_depends_on():
    _, _, deps = REGISTRY["pushback_count"]
    assert "pushback" in deps
    _, _, deps = REGISTRY["overall_score"]
    assert "resolution" in deps and "pushback" in deps
    assert "change_acceptance" in deps and "error_recovery" in deps


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
    assert results["overall_score"] is None  # no resolution annotation


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
    assert rows[0]["metrics"]["loop_count"] == 0
    assert rows[0]["metrics"]["recovery_count"] == 0
    assert "annotations" in rows[0]


# ── Pushback count ────────────────────────────────────────────────────

def test_pushback_count_with_annotations(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], None)

    results = compute_metrics(conn, traj.content_hash)
    assert results["pushback_count"] == 1


# ── Overall score ─────────────────────────────────────────────────────
# base = resolution {resolved:90, partially:45, unresolved:0}; missing accept/
# error/loop dims don't contribute, so with only resolution+pushback the score
# is base − pushback×5.

def test_overall_score_resolved_no_pushback(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "none"], "resolved")

    results = compute_metrics(conn, traj.content_hash)
    assert results["overall_score"] == 90  # base only; no accept → no +10


def test_overall_score_resolved_with_pushback(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], "resolved")

    results = compute_metrics(conn, traj.content_hash)
    assert results["overall_score"] == 85  # 90 − 5 (1 pushback)


def test_overall_score_unresolved(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "correction"], "unresolved")

    results = compute_metrics(conn, traj.content_hash)
    assert results["overall_score"] == 0


def test_overall_score_indeterminate_returns_none(tmp_path):
    conn = _db(tmp_path)
    traj = _make_traj()
    repo.put_trajectory(conn, traj)
    _add_annotations(conn, traj, ["none", "none"], "indeterminate")

    results = compute_metrics(conn, traj.content_hash)
    assert results["overall_score"] is None


def test_overall_score_dimensions():
    """accept/error/loop contributions, computed directly on synthetic anns."""
    from trajlens.metrics import REGISTRY
    fn = REGISTRY["overall_score"][0]

    def _anns(resolution="resolved", accept=None, errors=(), loop=False, intr=False, pb=0):
        out = [{"annotator_id": "resolution", "value": {"resolution": resolution}, "target_idx": None}]
        if accept is not None:
            out.append({"annotator_id": "change_acceptance",
                        "value": {"likelihood": accept, "no_edits": False}, "target_idx": None})
        for i, (has, rec) in enumerate(errors):
            out.append({"annotator_id": "error_recovery",
                        "value": {"has_error": has, "recovered": rec}, "target_idx": None})
        if loop:
            out.append({"annotator_id": "loop_detect", "value": {"detected": True}, "target_idx": None})
        if intr:
            out.append({"annotator_id": "hard_interruption", "value": {"interrupted": True}, "target_idx": None})
        for i in range(pb):
            out.append({"annotator_id": "pushback",
                        "value": {"category": "correction"}, "target_idx": i + 1})
        return out

    # resolved + accept high = 90 + 10 = 100 (only path to full marks)
    assert fn(None, None, _anns(accept="high")) == 100.0
    # resolved + accept low = 90 − 15 = 75
    assert fn(None, None, _anns(accept="low")) == 75.0
    # accept medium / no edits = base only
    assert fn(None, None, _anns(accept="medium")) == 90.0
    assert fn(None, None, _anns()) == 90.0
    # one unrecovered error → 90 − 10 = 80
    assert fn(None, None, _anns(errors=[(True, False)])) == 80.0
    # one recovered error → no penalty (rate 0)
    assert fn(None, None, _anns(errors=[(True, True)])) == 90.0
    # fractional penalties are rounded to the nearest integer after scoring
    fractional = fn(None, None, _anns(errors=[(True, False), (True, False), (True, True)]))
    assert fractional == 83
    assert isinstance(fractional, int)
    # loop_detect → 90 − 10 = 80
    assert fn(None, None, _anns(loop=True)) == 80.0
    # hard_interruption remains its own 15-point penalty.
    assert fn(None, None, _anns(intr=True)) == 75.0
    # stacked: resolved + accept low + loop + 1 error unrecovered = 90-15-10-10 = 55
    assert fn(None, None, _anns(accept="low", loop=True, errors=[(True, False)])) == 55.0
    # clamps at 0
    assert fn(None, None, _anns(resolution="unresolved", loop=True)) == 0.0
    # unverified base = 70 (between partial=45 and resolved=90)
    assert fn(None, None, _anns(resolution="unverified")) == 70.0
    # pushback cap is HALF THIS SESSION's base, not a fixed 45:
    #  resolved (base 90): 10 pushbacks ×5 = 50, capped at 45 → 90−45 = 45
    assert fn(None, None, _anns(resolution="resolved", pb=10)) == 45.0
    #  unverified (base 70): 10 pushbacks ×5 = 50, capped at 35 → 70−35 = 35 (not 25)
    assert fn(None, None, _anns(resolution="unverified", pb=10)) == 35.0


def test_recovery_count_from_annotations():
    from trajlens.metrics import REGISTRY

    anns = [
        {"annotator_id": "error_recovery", "value": {"has_error": True, "recovered": True}, "target_idx": 0},
        {"annotator_id": "error_recovery", "value": {"has_error": True, "recovered": False}, "target_idx": 1},
        {"annotator_id": "error_recovery", "value": {"has_error": False, "recovered": False}, "target_idx": 2},
    ]

    assert REGISTRY["recovery_count"][0](None, None, anns) == 1


def test_loop_count_uses_episode_count_from_code_changes():
    from trajlens.core.grouping import assign_groups
    from trajlens.core.loop_episodes import build_loop_episodes
    from trajlens.core.model import FunctionCallItem

    items = assign_groups([
        FunctionCallItem(name="edit", call_id="a", arguments=json.dumps({"file_path": "a.py", "new_string": "1"})),
        FunctionCallItem(name="edit", call_id="b", arguments=json.dumps({"file_path": "a.py", "new_string": "2"})),
        FunctionCallItem(name="edit", call_id="c", arguments=json.dumps({"file_path": "a.py", "new_string": "3"})),
        FunctionCallItem(name="edit", call_id="d", arguments=json.dumps({"file_path": "a.py", "new_string": "4"})),
        FunctionCallItem(name="edit", call_id="e", arguments=json.dumps({"file_path": "a.py", "new_string": "5"})),
        FunctionCallItem(name="edit", call_id="f", arguments=json.dumps({"file_path": "a.py", "new_string": "6"})),
    ])
    traj = Trajectory(content_hash=content_hash(items), items=items)

    episodes = build_loop_episodes(traj.items)

    assert len(episodes) == 1
    assert REGISTRY["loop_count"][0](traj, None, []) == 1


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


def test_dependency_invalidation_is_scoped_to_recomputed_dataset(tmp_path):
    """Re-running annotators for one dataset must not blank another dataset's score."""
    conn = _db(tmp_path)
    traj_a = _make_traj()
    ds_a = _put_in_dataset(conn, traj_a, "A")
    _add_annotations(conn, traj_a, ["none", "none"], "resolved")

    traj_b = _make_traj("fix the other bug")
    ds_b = _put_in_dataset(conn, traj_b, "B")
    _add_annotations(conn, traj_b, ["none", "correction"], "partially_resolved")

    compute_metrics(conn, traj_a.content_hash)
    compute_metrics(conn, traj_b.content_hash)
    assert repo.get_dataset_stats(conn, ds_a["id"])["metrics"]["overall_score"]["avg"] == 90

    _invalidate_dependent_metrics(conn, "resolution", [traj_b.content_hash])
    _recompute_metrics(conn, [traj_b.content_hash])

    assert repo.get_dataset_stats(conn, ds_a["id"])["metrics"]["overall_score"]["avg"] == 90
    assert repo.get_dataset_stats(conn, ds_b["id"])["metrics"]["overall_score"]["avg"] == 40
