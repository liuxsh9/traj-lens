from trajlens.annotate import Target, enumerate_targets
from trajlens.annotate.runner import load_annotator_module, run_annotator
from trajlens.annotate import AnnotatorSpec
from trajlens.core.identity import content_hash
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem, Trajectory
from trajlens.store import db as dbmod
from trajlens.store import repo
import os
import time
import types


def test_step_targets_are_unique_across_runs_with_same_step_id():
    items = [
        MessageItem(role="user", content="first"),
        FunctionCallItem(name="bash", arguments="{}", call_id="c1", run_id=0, step_id=0),
        FunctionCallOutputItem(call_id="c1", output="ok", run_id=0, step_id=0),
        MessageItem(role="user", content="second"),
        FunctionCallItem(name="bash", arguments="{}", call_id="c2", run_id=1, step_id=0),
        FunctionCallOutputItem(call_id="c2", output="ok", run_id=1, step_id=0),
    ]
    traj = Trajectory(content_hash=content_hash(items), items=items)

    targets = enumerate_targets(traj, Target.STEP)
    hashes = [target_hash for target_hash, _unit, _span in targets]

    assert len(targets) == 2
    assert len(set(hashes)) == 2


def test_load_annotator_module_reloads_changed_rule_code(tmp_path, monkeypatch):
    module_dir = tmp_path / "mods"
    module_dir.mkdir()
    module_path = module_dir / "sample_rule.py"
    module_path.write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(module_dir))

    spec = AnnotatorSpec(id="sample", type="rule", target=Target.STEP,
                         config={"module": "sample_rule"})
    assert load_annotator_module(spec).VALUE == 1

    module_path.write_text("VALUE = 2\n")
    now = time.time() + 2
    os.utime(module_path, (now, now))

    assert load_annotator_module(spec).VALUE == 2


def test_force_rerun_removes_stale_step_annotations_from_old_target_identity(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    items = [
        MessageItem(role="user", content="first"),
        FunctionCallItem(name="bash", arguments="{}", call_id="c0", run_id=0, step_id=0),
        FunctionCallOutputItem(call_id="c0", output="ok", run_id=0, step_id=0),
        MessageItem(role="user", content="second"),
        FunctionCallItem(name="bash", arguments="{}", call_id="c1", run_id=1, step_id=0),
        FunctionCallOutputItem(call_id="c1", output="ok", run_id=1, step_id=0),
        FunctionCallItem(name="bash", arguments="{}", call_id="c2", run_id=1, step_id=1),
        FunctionCallOutputItem(call_id="c2", output="ok", run_id=1, step_id=1),
    ]
    traj = Trajectory(content_hash=content_hash(items), items=items)
    repo.put_trajectory(conn, traj, source_path="mixed-targets.json")

    spec = AnnotatorSpec(id="error_recovery", type="rule", target=Target.STEP,
                         context="self", config={"id": "error_recovery",
                                                 "type": "rule",
                                                 "target": "step",
                                                 "revision": 1})
    spec.version = "v1"
    repo.register_annotator(conn, id=spec.id, version=spec.version, config_hash=spec.version)

    # Simulate a pre-fix stale annotation: its target hash is no longer part of
    # the current step target enumeration, but it still joins back to this
    # trajectory and would show as an extra ERR badge.
    old_hash = "old-step-target-hash"
    repo.link_annotation_target(conn, target_hash=old_hash, content_hash=traj.content_hash,
                                target_type="step", target_idx=0)
    conn.commit()
    repo.put_annotation(conn, target_hash=old_hash, annotator_id=spec.id,
                        annotator_version=spec.version,
                        value={"has_error": True, "recovered": False,
                               "error_summary": "stale old target"},
                        inputs_hash="old")

    mod = types.SimpleNamespace(
        annotate=lambda unit, ctx: {"has_error": False, "recovered": None,
                                   "error_summary": None}
    )

    import asyncio
    asyncio.run(run_annotator(conn, spec, mod, content_hashes=[traj.content_hash], force=True))

    anns = repo.get_annotations_for_trajectory(conn, traj.content_hash)

    assert len([a for a in anns if a["annotator_id"] == "error_recovery"]) == 3
    assert all("stale old target" not in a["value"] for a in anns)
