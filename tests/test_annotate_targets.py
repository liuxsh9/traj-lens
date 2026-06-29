from trajlens.annotate import Target, enumerate_targets
from trajlens.annotate.runner import load_annotator_module
from trajlens.annotate import AnnotatorSpec
from trajlens.core.identity import content_hash
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem, Trajectory
import os
import time


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
