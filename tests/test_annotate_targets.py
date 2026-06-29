from trajlens.annotate import Target, enumerate_targets
from trajlens.core.identity import content_hash
from trajlens.core.model import FunctionCallItem, FunctionCallOutputItem, MessageItem, Trajectory


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
