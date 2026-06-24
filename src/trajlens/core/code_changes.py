"""Code-change projection over a trajectory's function_call items (slice-5, §1).

Read-time only — like grouping, never stored, never crosses into the canonical
model. Normalizes the heterogeneous tool-call zoo (str_replace_editor / edit /
replace_all / Bash / shell_command …) into a flat list of CodeChange events that
the viewer timeline (and later Semgrep / preview) consume. Tool identity comes
from core.tool_aliases.canonical(); arg keys vary by source, so we look up each
field through a tolerant alias list.
"""

import json
from dataclasses import dataclass, asdict

from trajlens.core.tool_aliases import canonical, BASH_TOOLS, EDIT_TOOLS

# arg-key aliases — same concept, different spelling across formats
_PATH_KEYS = ("file_path", "filePath", "path", "file_name", "file_name1")
_OLD_KEYS = ("old_string", "old_str", "oldString")
_NEW_KEYS = ("new_string", "new_str", "newString", "content", "file_text")


@dataclass
class CodeChange:
    item_idx: int            # position in the flat item list
    step_id: int | None      # from grouping projection (may be None pre-grouping)
    run_id: int | None
    tool: str                # canonical tool name
    op: str                  # create | edit | delete | run
    path: str | None
    old: str | None          # edit "before" fragment
    new: str | None          # edit "after" fragment, or full content on create
    command: str | None      # shell command, for op=run


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _classify_edit(args: dict):
    """(op, old, new) for an edit/write tool call, or None if it's really a read.

    str_replace_editor overloads one tool name via a `command` subfield:
    view -> read (skip), create -> create, str_replace/insert -> edit.
    """
    cmd = str(args.get("command") or "").lower()
    if cmd == "view":
        return None  # a read masquerading as the editor tool
    old = _first(args, *_OLD_KEYS)
    new = _first(args, *_NEW_KEYS)
    if old is None and new is None:
        return None  # nothing to show (e.g. editor "undo"/"insert" with no body)
    op = "create" if (cmd == "create" or old is None) else "edit"
    return op, old, new


def extract_changes(items) -> list[CodeChange]:
    """Project the items into CodeChange events (file edits/creates + shell runs).

    Read/search/glob/todo/web tool calls produce no change and are skipped.
    """
    out: list[CodeChange] = []
    for idx, it in enumerate(items):
        if getattr(it, "type", None) != "function_call":
            continue
        tool = canonical(it.name)
        try:
            args = json.loads(it.arguments) if it.arguments else {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        if not isinstance(args, dict):
            continue

        if tool in EDIT_TOOLS:
            res = _classify_edit(args)
            if res is None:
                continue
            op, old, new = res
            out.append(CodeChange(idx, it.step_id, it.run_id, tool, op,
                                  _first(args, *_PATH_KEYS), old, new, None))
        elif tool in BASH_TOOLS:
            cmd = _first(args, "command")
            if cmd:
                # ponytail: bash stays op=run; sniffing rm/mv/touch for
                # delete/create classification is the upgrade path if needed.
                out.append(CodeChange(idx, it.step_id, it.run_id, tool, "run",
                                      None, None, None, str(cmd)))
        # else: read/search/glob/todo/web — not a code change, skip
    return out


def changes_as_dicts(items) -> list[dict]:
    """JSON-ready projection for the API layer."""
    return [asdict(c) for c in extract_changes(items)]


if __name__ == "__main__":
    # self-check: the three shapes that matter must classify correctly.
    from trajlens.core.model import FunctionCallItem, MessageItem

    items = [
        MessageItem(role="user", content="go"),
        # openai str_replace_editor: view is a read -> skipped
        FunctionCallItem(name="str_replace_editor", call_id="1",
                         arguments=json.dumps({"command": "view", "path": "/a.py"})),
        # openai str_replace_editor: str_replace -> edit, path/old/new normalized
        FunctionCallItem(name="str_replace_editor", call_id="2",
                         arguments=json.dumps({"command": "str_replace", "path": "/a.py",
                                               "old_str": "x", "new_str": "y"})),
        # swe_chat camelCase create (no old) -> create
        FunctionCallItem(name="write_file", call_id="3",
                         arguments=json.dumps({"filePath": "/b.py", "content": "print(1)"})),
        # bash -> run
        FunctionCallItem(name="execute_bash", call_id="4",
                         arguments=json.dumps({"command": "pytest -q"})),
        # read -> skipped
        FunctionCallItem(name="read", call_id="5",
                         arguments=json.dumps({"file_path": "/c.py"})),
    ]
    chs = extract_changes(items)
    assert len(chs) == 3, [c.op for c in chs]
    assert chs[0].op == "edit" and chs[0].path == "/a.py" and chs[0].new == "y"
    assert chs[1].op == "create" and chs[1].path == "/b.py" and chs[1].old is None
    assert chs[2].op == "run" and chs[2].command == "pytest -q" and chs[2].tool == "bash"
    print("ok:", [(c.op, c.tool, c.path or c.command) for c in chs])
