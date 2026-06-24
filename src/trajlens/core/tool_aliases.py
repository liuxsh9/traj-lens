"""Canonical tool name aliases — maps variant names to a single canonical form.

Data stays untouched (Item.name preserves the original). Rules, metrics, filters,
and viewer use `canonical(name)` to compare tool behavior regardless of source format.
"""

# ponytail: one flat dict, add entries as new adapters surface variants.
# Keys are lowercase; canonical() lowercases before lookup.
_ALIASES: dict[str, str] = {
    # ── shell execution ──
    "execute_bash": "bash",
    "terminal": "bash",
    "run_command": "bash",
    "shell": "bash",
    # ── file read ──
    "read_file": "read",
    "cat": "read",
    "view": "read",
    "glob": "glob",
    # ── file write / create ──
    "write_to_file": "write",
    "create_file": "write",
    "write_file": "write",
    # ── file edit ──
    "str_replace_editor": "edit",
    "replace_all": "edit",
    "apply_diff": "edit",
    "insert_content": "edit",
    # ── search ──
    "grep": "search",
    "ripgrep": "search",
    "find": "search",
    "query": "search",
}

# Canonical tool categories — for grouping in stats/visualization
BASH_TOOLS = frozenset({"bash"})
READ_TOOLS = frozenset({"read", "glob", "search"})
EDIT_TOOLS = frozenset({"edit", "write"})


def canonical(name: str) -> str:
    """Map a tool name to its canonical form. Unknown names pass through lowercased."""
    return _ALIASES.get(name.lower(), name.lower())
