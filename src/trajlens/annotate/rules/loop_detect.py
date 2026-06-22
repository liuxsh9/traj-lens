"""loop_detect: flag steps where the same file is edited ≥3 times in preceding context."""
import json

EDIT_TOOLS = {"edit", "write", "Edit", "Write", "str_replace_editor",
              "create_file", "write_to_file", "insert_content", "apply_diff"}
PATH_KEYS = {"file_path", "path", "file", "filename"}


def annotate(unit, ctx):
    """Returns {"detected": bool, "files": {path: count}} for files edited ≥3 times."""
    counts: dict[str, int] = {}
    for it in ctx:
        if it.type != "function_call":
            continue
        if it.name not in EDIT_TOOLS:
            continue
        try:
            args = json.loads(it.arguments)
        except (json.JSONDecodeError, TypeError):
            continue
        for k in PATH_KEYS:
            if k in args and isinstance(args[k], str):
                counts[args[k]] = counts.get(args[k], 0) + 1
                break
    flagged = {p: c for p, c in counts.items() if c >= 3}
    return {"detected": bool(flagged), "files": flagged}
