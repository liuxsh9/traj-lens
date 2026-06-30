"""Loop episode projection shared by metrics and the viewer API."""

from dataclasses import asdict, dataclass
import json

from trajlens.core.code_changes import extract_changes
from trajlens.core.model import Item
from trajlens.core.tool_aliases import canonical, BASH_TOOLS, EDIT_TOOLS, READ_TOOLS

LOOP_GAP_STEPS = 4
PATH_KEYS = ("file_path", "filePath", "path", "file", "filename", "file_name", "file_name1")
NEGATIVE_OUTPUT_MARKERS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "not found",
    "no such",
    "cannot",
    "denied",
    "exit code",
    "timed out",
    "timeout",
)


@dataclass
class LoopEditPoint:
    key: str
    run_id: int
    step_id: int
    item_idx: int


@dataclass
class FeedbackPoint:
    key: str
    run_id: int
    step_id: int
    path: str | None


@dataclass
class LoopEpisode:
    id: str
    path: str
    edit_count: int
    start_key: str
    trigger_key: str
    end_key: str
    start_idx: int
    end_idx: int
    interval_keys: list[str]
    points: list[LoopEditPoint]


def _step_key(run_id: int, step_id: int) -> str:
    return f"{run_id}-{step_id}"


def _step_order(items: list[Item]) -> tuple[list[str], dict[str, int]]:
    keys: list[str] = []
    order: dict[str, int] = {}
    current: str | None = None
    for it in items:
        if it.run_id is None or it.step_id is None:
            current = None
            continue
        key = _step_key(it.run_id, it.step_id)
        if key != current:
            current = key
            if key not in order:
                order[key] = len(keys)
                keys.append(key)
    return keys, order


def _arg_path(args: dict) -> str | None:
    for key in PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _json_args(it: Item) -> dict:
    if getattr(it, "type", None) != "function_call":
        return {}
    try:
        args = json.loads(getattr(it, "arguments", "") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return args if isinstance(args, dict) else {}


def _is_negative_output(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in NEGATIVE_OUTPUT_MARKERS)


def _feedback_points(items: list[Item]) -> list[FeedbackPoint]:
    feedback: list[FeedbackPoint] = []
    call_paths: dict[str, str | None] = {}
    call_tools: dict[str, str] = {}

    for it in items:
        if it.run_id is None or it.step_id is None:
            continue
        key = _step_key(it.run_id, it.step_id)
        if it.type == "function_call":
            tool = canonical(it.name)
            args = _json_args(it)
            path = _arg_path(args)
            call_paths[it.call_id] = path
            call_tools[it.call_id] = tool
            if tool in READ_TOOLS or tool in BASH_TOOLS:
                feedback.append(FeedbackPoint(key, it.run_id, it.step_id, path))
        elif it.type == "function_call_output" and _is_negative_output(it.output):
            tool = call_tools.get(it.call_id)
            path = call_paths.get(it.call_id)
            feedback.append(FeedbackPoint(
                key=key,
                run_id=it.run_id,
                step_id=it.step_id,
                path=path if tool in EDIT_TOOLS else None,
            ))

    return feedback


def build_loop_episodes(items: list[Item], gap_steps: int = LOOP_GAP_STEPS) -> list[LoopEpisode]:
    keys, order = _step_order(items)
    by_path: dict[str, list[LoopEditPoint]] = {}
    seen_steps_by_path: dict[str, set[str]] = {}
    feedback = _feedback_points(items)

    def has_feedback_between(path: str, prev: LoopEditPoint, cur: LoopEditPoint) -> bool:
        if prev.run_id != cur.run_id:
            return False
        prev_idx = order.get(prev.key, 0)
        cur_idx = order.get(cur.key, prev_idx)
        for event in feedback:
            if event.run_id != prev.run_id:
                continue
            event_idx = order.get(event.key, -1)
            if prev_idx <= event_idx < cur_idx and (event.path is None or event.path == path):
                return True
        return False

    for change in extract_changes(items):
        if change.op not in ("create", "edit") or not change.path:
            continue
        if change.run_id is None or change.step_id is None:
            continue
        key = _step_key(change.run_id, change.step_id)
        seen_steps = seen_steps_by_path.setdefault(change.path, set())
        if key in seen_steps:
            continue
        seen_steps.add(key)
        point = LoopEditPoint(
            key=key,
            run_id=change.run_id,
            step_id=change.step_id,
            item_idx=change.item_idx,
        )
        by_path.setdefault(change.path, []).append(point)

    episodes: list[LoopEpisode] = []
    for path, points in by_path.items():
        points.sort(key=lambda p: (order.get(p.key, 10**12), p.item_idx))
        burst: list[LoopEditPoint] = []

        def flush() -> None:
            nonlocal burst
            if len(burst) >= 3:
                start = burst[0]
                trigger = burst[2]
                end = burst[-1]
                start_idx = order.get(start.key, 0)
                end_idx = order.get(end.key, start_idx)
                episodes.append(LoopEpisode(
                    id=f"{path}:{start.key}:{end.key}:{len(episodes)}",
                    path=path,
                    edit_count=len(burst),
                    start_key=start.key,
                    trigger_key=trigger.key,
                    end_key=end.key,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    interval_keys=keys[start_idx:end_idx + 1],
                    points=[*burst],
                ))
            burst = []

        for point in points:
            if burst:
                prev = burst[-1]
                prev_idx = order.get(prev.key, 0)
                cur_idx = order.get(point.key, prev_idx)
                if (
                    point.run_id != prev.run_id
                    or cur_idx - prev_idx > gap_steps
                    or not has_feedback_between(path, prev, point)
                ):
                    flush()
            burst.append(point)
        flush()

    episodes.sort(key=lambda ep: (ep.start_idx, ep.end_idx, ep.path))
    return episodes


def loop_episodes_as_dicts(items: list[Item]) -> list[dict]:
    return [asdict(ep) for ep in build_loop_episodes(items)]
