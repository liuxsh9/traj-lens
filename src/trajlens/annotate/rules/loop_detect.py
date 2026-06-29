"""loop_detect: flag steps where the same file is edited ≥3 times in preceding context."""
import json

from trajlens.core.tool_aliases import canonical, EDIT_TOOLS

PATH_KEYS = {"file_path", "path", "file", "filename"}
CHANGE_KEYS = {
    "old_string", "old_str", "oldString",
    "new_string", "new_str", "newString",
    "content", "file_text",
}


def _is_real_edit(args: dict) -> bool:
    """True for edit/write calls that actually change file contents."""
    cmd = str(args.get("command") or "").lower()
    if cmd == "view":
        return False
    return any(args.get(k) not in (None, "") for k in CHANGE_KEYS)


def annotate(unit, ctx):
    """Returns {"detected": bool, "files": {path: count}} for files edited ≥3 times."""
    counts: dict[str, int] = {}
    for it in ctx:
        if it.type != "function_call":
            continue
        if canonical(it.name) not in EDIT_TOOLS:
            continue
        try:
            args = json.loads(it.arguments)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(args, dict) or not _is_real_edit(args):
            continue
        for k in PATH_KEYS:
            if k in args and isinstance(args[k], str):
                counts[args[k]] = counts.get(args[k], 0) + 1
                break
    flagged = {p: c for p, c in counts.items() if c >= 3}
    return {"detected": bool(flagged), "files": flagged}
