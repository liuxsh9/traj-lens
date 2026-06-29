"""Annotation middleware — types, enums, protocols, target enumeration, context projection."""
import hashlib
import json
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from trajlens.core.model import Item, Trajectory


# ── Enums ──────────────────────────────────────────────────────────────

class Target(str, Enum):
    SESSION = "session"
    USER_TURN = "user_turn"
    ASSISTANT_TURN = "assistant_turn"
    STEP = "step"
    TOOL_RESULT = "tool_result"


# ── Spec ───────────────────────────────────────────────────────────────

class AnnotatorSpec(BaseModel):
    id: str
    type: Literal["rule", "llm"]
    target: Target
    context: str = "self"          # "self" | "window:5" | "prefix" | "whole"
    version: str = ""              # auto-derived by compute_version
    config: dict = Field(default_factory=dict)


def compute_version(spec: AnnotatorSpec) -> str:
    blob = json.dumps({"type": spec.type, **spec.config}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


# ── Protocols ──────────────────────────────────────────────────────────

class RuleAnnotator(Protocol):
    def annotate(self, unit: list[Item], ctx: list[Item]) -> Any: ...


class LLMAnnotator(Protocol):
    def build(self, unit: list[Item], ctx: list[Item]) -> list[dict]: ...
    def parse(self, response: str) -> Any: ...


# ── Target enumeration ─────────────────────────────────────────────────

def _target_hash(content_hash: str, label: str, idx: int) -> str:
    return hashlib.sha256(f"{content_hash}:{label}:{idx}".encode()).hexdigest()


def enumerate_targets(traj: Trajectory, target: Target) -> list[tuple[str, list[Item], tuple[int, int]]]:
    """Returns (target_hash, unit_items, (start_idx, end_idx)) for each target unit."""
    items = traj.items
    results: list[tuple[str, list[Item], tuple[int, int]]] = []

    if target == Target.SESSION:
        results.append((traj.content_hash, list(items), (0, len(items))))

    elif target == Target.USER_TURN:
        for i, it in enumerate(items):
            if it.type == "message" and it.role == "user":
                results.append((_target_hash(traj.content_hash, "user_turn", i), [it], (i, i + 1)))

    elif target == Target.ASSISTANT_TURN:
        # group by run_id (contiguous items with same non-None run_id)
        current_run: int | None = None
        start = 0
        for i, it in enumerate(items):
            rid = getattr(it, "run_id", None)
            if rid is not None and rid != current_run:
                if current_run is not None:
                    run_items = list(items[start:i])
                    results.append((_target_hash(traj.content_hash, "asst_turn", current_run), run_items, (start, i)))
                current_run = rid
                start = i
            elif rid is None and current_run is not None:
                run_items = list(items[start:i])
                results.append((_target_hash(traj.content_hash, "asst_turn", current_run), run_items, (start, i)))
                current_run = None
        if current_run is not None:
            run_items = list(items[start:len(items)])
            results.append((_target_hash(traj.content_hash, "asst_turn", current_run), run_items, (start, len(items))))

    elif target == Target.STEP:
        current_step: int | None = None
        start = 0
        step_target_idx = 0
        for i, it in enumerate(items):
            sid = getattr(it, "step_id", None)
            if sid is not None and sid != current_step:
                if current_step is not None:
                    step_items = list(items[start:i])
                    results.append((_target_hash(traj.content_hash, "step", step_target_idx), step_items, (start, i)))
                    step_target_idx += 1
                current_step = sid
                start = i
            elif sid is None and current_step is not None:
                step_items = list(items[start:i])
                results.append((_target_hash(traj.content_hash, "step", step_target_idx), step_items, (start, i)))
                step_target_idx += 1
                current_step = None
        if current_step is not None:
            step_items = list(items[start:len(items)])
            results.append((_target_hash(traj.content_hash, "step", step_target_idx), step_items, (start, len(items))))

    elif target == Target.TOOL_RESULT:
        for i, it in enumerate(items):
            if it.type == "function_call_output":
                results.append((_target_hash(traj.content_hash, "tool_result", i), [it], (i, i + 1)))

    return results


# ── Context projection ─────────────────────────────────────────────────

def _parse_context(policy: str) -> tuple[str, int]:
    """Returns (mode, k) where mode is self/window/prefix/whole."""
    if policy.startswith("window:"):
        return "window", int(policy.split(":")[1])
    return policy, 0


def project_context(items: list[Item], unit_range: tuple[int, int], policy: str) -> list[Item]:
    mode, k = _parse_context(policy)
    start, end = unit_range
    if mode == "self":
        return list(items[start:end])
    elif mode == "window":
        lo = max(0, start - k)
        hi = min(len(items), end + k)
        return list(items[lo:hi])
    elif mode == "prefix":
        return list(items[:end])
    elif mode == "whole":
        return list(items)
    return list(items[start:end])


def compute_inputs_hash(unit: list[Item], ctx: list[Item]) -> str:
    blob = json.dumps(
        {"unit": [it.model_dump(exclude={"step_id", "run_id", "provenance"}) for it in unit],
         "ctx_len": len(ctx)},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
