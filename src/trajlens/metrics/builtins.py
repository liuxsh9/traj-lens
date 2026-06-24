"""Built-in session-level metrics."""
import json

from trajlens.core.model import Trajectory
from trajlens.metrics import register
from trajlens.store import repo

_VERSION = "2"


@register("turn_count", _VERSION)
def turn_count(traj: Trajectory, conn) -> int:
    return sum(1 for it in traj.items if it.type == "message" and it.role == "user")


@register("step_count", _VERSION)
def step_count(traj: Trajectory, conn) -> int:
    steps = {(it.run_id, it.step_id) for it in traj.items
             if it.step_id is not None}
    return len(steps)


@register("tool_count", _VERSION)
def tool_count(traj: Trajectory, conn) -> int:
    return sum(1 for it in traj.items if it.type == "function_call")


@register("pushback_count", _VERSION, depends_on=["pushback"])
def pushback_count(traj: Trajectory, conn) -> int:
    anns = repo.get_annotations_for_trajectory(conn, traj.content_hash)
    count = 0
    for a in anns:
        if a["annotator_id"] != "pushback":
            continue
        # ponytail: first user message (target_idx=0) can't be pushback — it's the initial request
        if a.get("target_idx") == 0:
            continue
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        if v.get("category", "none") != "none":
            count += 1
    return count


@register("tool_intensity", _VERSION, depends_on=["error_recovery"])
def tool_intensity(traj: Trajectory, conn) -> dict:
    calls = 0
    unique_tools: set[str] = set()
    for it in traj.items:
        if it.type == "function_call":
            calls += 1
            unique_tools.add(it.name)

    anns = repo.get_annotations_for_trajectory(conn, traj.content_hash)
    error_steps = 0
    recovered_steps = 0
    for a in anns:
        if a["annotator_id"] != "error_recovery":
            continue
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        if v.get("has_error"):
            error_steps += 1
            if v.get("recovered") is True:
                recovered_steps += 1

    return {
        "calls": calls,
        "unique_tools": len(unique_tools),
        "error_steps": error_steps,
        "recovery_rate": round(recovered_steps / error_steps, 2) if error_steps > 0 else None,
    }


@register("success_score", _VERSION, depends_on=["resolution", "pushback"])
def success_score(traj: Trajectory, conn) -> float | None:
    """Composite score: resolution baseline − pushback penalty.

    resolved=100, partially=50, unresolved=0, indeterminate→None.
    Each pushback costs 5 points, capped at half the baseline.
    """
    # Find resolution annotation
    anns = repo.get_annotations_for_trajectory(conn, traj.content_hash)
    resolution = None
    pb_count = 0
    for a in anns:
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        if a["annotator_id"] == "resolution":
            resolution = v.get("resolution")
        elif a["annotator_id"] == "pushback" and a.get("target_idx") != 0 and v.get("category", "none") != "none":
            pb_count += 1

    if resolution is None or resolution == "indeterminate":
        return None

    base = {"resolved": 100, "partially_resolved": 50, "unresolved": 0}.get(resolution, 0)
    penalty = min(pb_count * 5, base * 0.5)
    return base - penalty
