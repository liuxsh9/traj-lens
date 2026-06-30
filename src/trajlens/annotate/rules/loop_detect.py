"""loop_detect: flag steps where the same file is edited ≥3 times in preceding context."""
import json

from trajlens.core.tool_aliases import canonical, BASH_TOOLS, EDIT_TOOLS, READ_TOOLS

PATH_KEYS = {"file_path", "path", "file", "filename"}
CHANGE_KEYS = {
    "old_string", "old_str", "oldString",
    "new_string", "new_str", "newString",
    "content", "file_text",
}
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


def _is_real_edit(args: dict) -> bool:
    """True for edit/write calls that actually change file contents."""
    cmd = str(args.get("command") or "").lower()
    if cmd == "view":
        return False
    return any(args.get(k) not in (None, "") for k in CHANGE_KEYS)


def _path(args: dict) -> str | None:
    for k in PATH_KEYS:
        if k in args and isinstance(args[k], str):
            return args[k]
    return None


def _is_negative_output(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in NEGATIVE_OUTPUT_MARKERS)


def annotate(unit, ctx):
    """Returns {"detected": bool, "files": {path: count}} for files edited ≥3 times."""
    counts: dict[str, int] = {}
    seen_steps: dict[str, set[tuple[int, int]]] = {}
    last_edit_step: dict[str, tuple[int, int]] = {}
    feedback_since_edit: dict[str, bool] = {}
    call_paths: dict[str, str | None] = {}
    call_tools: dict[str, str] = {}

    for idx, it in enumerate(ctx):
        if it.type == "function_call_output":
            tool = call_tools.get(it.call_id)
            path = call_paths.get(it.call_id)
            if _is_negative_output(it.output):
                if tool in EDIT_TOOLS and path in last_edit_step:
                    feedback_since_edit[path] = True
                else:
                    for edited_path in last_edit_step:
                        feedback_since_edit[edited_path] = True
            continue
        if it.type != "function_call":
            continue
        tool = canonical(it.name)
        try:
            args = json.loads(it.arguments)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(args, dict):
            continue
        path = _path(args)
        call_paths[it.call_id] = path
        call_tools[it.call_id] = tool
        if tool in READ_TOOLS or tool in BASH_TOOLS:
            for edited_path in last_edit_step:
                if path is None or path == edited_path:
                    feedback_since_edit[edited_path] = True
            continue
        if tool not in EDIT_TOOLS or not _is_real_edit(args) or path is None:
            continue

        grouped = it.run_id is not None and it.step_id is not None
        step_key = (it.run_id, it.step_id) if grouped else (-1, idx)
        if grouped:
            steps = seen_steps.setdefault(path, set())
            if step_key in steps:
                continue
            steps.add(step_key)
        prev = last_edit_step.get(path)
        if prev and (prev[0] != step_key[0] or not feedback_since_edit.get(path, False)):
            counts[path] = 0
        last_edit_step[path] = step_key
        counts[path] = counts.get(path, 0) + 1
        feedback_since_edit[path] = False

    flagged = {p: c for p, c in counts.items() if c >= 3}
    return {"detected": bool(flagged), "files": flagged}
