"""Loop episode projection shared by metrics and the viewer API."""

from dataclasses import asdict, dataclass

from trajlens.core.code_changes import extract_changes
from trajlens.core.model import Item

LOOP_GAP_STEPS = 4


@dataclass
class LoopEditPoint:
    key: str
    run_id: int
    step_id: int
    item_idx: int


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


def build_loop_episodes(items: list[Item], gap_steps: int = LOOP_GAP_STEPS) -> list[LoopEpisode]:
    keys, order = _step_order(items)
    by_path: dict[str, list[LoopEditPoint]] = {}

    for change in extract_changes(items):
        if change.op not in ("create", "edit") or not change.path:
            continue
        if change.run_id is None or change.step_id is None:
            continue
        point = LoopEditPoint(
            key=_step_key(change.run_id, change.step_id),
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
                if point.run_id != prev.run_id or cur_idx - prev_idx > gap_steps:
                    flush()
            burst.append(point)
        flush()

    episodes.sort(key=lambda ep: (ep.start_idx, ep.end_idx, ep.path))
    return episodes


def loop_episodes_as_dicts(items: list[Item]) -> list[dict]:
    return [asdict(ep) for ep in build_loop_episodes(items)]
