"""Built-in session-level metrics.

Each metric fn is `(traj, conn, anns)`: `anns` is this trajectory's full
annotation list, fetched once by compute_metrics and shared across metrics —
so the three annotation-reading metrics below don't each re-query the DB.
"""
import json

from trajlens.core.model import Trajectory
from trajlens.core.loop_episodes import build_loop_episodes
from trajlens.metrics import register

_VERSION = "2"
_LOOP_COUNT_VERSION = "3"
_OVERALL_SCORE_VERSION = "6"


@register("turn_count", _VERSION)
def turn_count(traj: Trajectory, conn, anns) -> int:
    return sum(1 for it in traj.items if it.type == "message" and it.role == "user")


@register("step_count", _VERSION)
def step_count(traj: Trajectory, conn, anns) -> int:
    steps = {(it.run_id, it.step_id) for it in traj.items
             if it.step_id is not None}
    return len(steps)


@register("tool_count", _VERSION)
def tool_count(traj: Trajectory, conn, anns) -> int:
    return sum(1 for it in traj.items if it.type == "function_call")


@register("pushback_count", _VERSION, depends_on=["pushback"])
def pushback_count(traj: Trajectory, conn, anns) -> int:
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
def tool_intensity(traj: Trajectory, conn, anns) -> dict:
    calls = 0
    unique_tools: set[str] = set()
    for it in traj.items:
        if it.type == "function_call":
            calls += 1
            unique_tools.add(it.name)

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


@register("recovery_count", _VERSION, depends_on=["error_recovery"])
def recovery_count(traj: Trajectory, conn, anns) -> int:
    count = 0
    for a in anns:
        if a["annotator_id"] != "error_recovery":
            continue
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        if v.get("has_error") and v.get("recovered") is True:
            count += 1
    return count


@register("loop_count", _LOOP_COUNT_VERSION)
def loop_count(traj: Trajectory, conn, anns) -> int:
    return len(build_loop_episodes(traj.items))


@register("acceptance_likelihood", _VERSION, depends_on=["change_acceptance"])
def acceptance_likelihood(traj: Trajectory, conn, anns) -> float | None:
    """0–100 likelihood that the session's code changes were accepted.

    Mirrors the change_acceptance annotator's `score` (0–1) onto the metrics
    table so list/filter/sort/export pick it up. None when no code was edited
    (the dimension is N/A, not a low score).
    """
    for a in anns:
        if a["annotator_id"] != "change_acceptance":
            continue
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        if v.get("no_edits") or v.get("score") is None:
            return None
        return round(v["score"] * 100, 1)
    return None


@register("overall_score", _OVERALL_SCORE_VERSION,
          depends_on=["resolution", "pushback", "change_acceptance",
                      "error_recovery", "loop_detect", "hard_interruption"])
def overall_score(traj: Trajectory, conn, anns) -> int | None:
    """Composite session-quality score over five dimensions.

    base = resolution {resolved:90, unverified:70, partially:45, unresolved:0} —
    leaves 10pt of headroom so only a resolved-AND-accepted session reaches 100.
      + accept high  : +10   (changes committed/pushed)
      − accept low   : −15   (changes reverted / user rejected)
      − pushback     : −5 each, capped at base×0.5
      − error unrecovered rate × 10  (sessions with no errors are not penalised)
      − loop_detect: −10
      − hard-interruption: −15
    Missing dimensions (no edits, no errors) simply don't contribute — they never
    penalise. None when resolution is indeterminate (can't anchor a base).
    """
    resolution = None
    pb_count = 0
    accept = None                 # high|medium|low|None(no edits)
    err_steps = err_recovered = 0
    loop = interrupted = False

    for a in anns:
        v = json.loads(a["value"]) if isinstance(a["value"], str) else a["value"]
        aid = a["annotator_id"]
        if aid == "resolution":
            resolution = v.get("resolution")
        elif aid == "pushback" and a.get("target_idx") != 0 and v.get("category", "none") != "none":
            pb_count += 1
        elif aid == "change_acceptance" and not v.get("no_edits"):
            accept = v.get("likelihood")
        elif aid == "error_recovery" and v.get("has_error"):
            err_steps += 1
            if v.get("recovered") is True:
                err_recovered += 1
        elif aid == "loop_detect" and v.get("detected"):
            loop = True
        elif aid == "hard_interruption" and v.get("interrupted"):
            interrupted = True

    if resolution is None or resolution == "indeterminate":
        return None

    base = {"resolved": 90, "unverified": 70, "partially_resolved": 45, "unresolved": 0}.get(resolution, 0)
    score = base
    score += {"high": 10}.get(accept, 0)          # accept bonus (None/medium → 0)
    score -= {"low": 15}.get(accept, 0)           # accept penalty
    score -= min(pb_count * 5, base * 0.5)        # pushback, capped at half THIS session's base
    if err_steps:
        score -= (1 - err_recovered / err_steps) * 10   # unrecovered-error rate
    if loop:
        score -= 10
    if interrupted:
        score -= 15
    return round(max(0.0, min(100.0, score)))
