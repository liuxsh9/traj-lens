"""change_acceptance: estimate the likelihood that code changes in a session were
accepted by the user.

We never observe the user's real accept/reject. This is a heuristic over concrete
session signals: did the agent edit code, and did acceptance-shaped events follow
(git commit/push, passing tests) — vetoed by rejection-shaped events (user asking
to revert/undo, or pushback after an edit).

Session-target, session-wide attribution (decided 2026-06-25): one score per
trajectory, any positive/negative signal anywhere in the session counts. Coarse
but robust — in codex an edit and its commit are both `shell_command`/bash calls
with no tool-name distinction, so per-edit matching would be brittle. See
[[multi-agent-workflow]] only for repo conventions, not relevant here.
"""
import json
import re

from trajlens.core.tool_aliases import canonical, EDIT_TOOLS, BASH_TOOLS
from trajlens.annotate.rules.error_recovery import _has_error

PATH_KEYS = {"file_path", "path", "file", "filename"}

# ── test / build commands ──────────────────────────────────────────────
# "ran the test suite and it didn't error" is a weak accept signal: the agent
# validated its own change. Pass/fail comes from error_recovery._has_error on
# the command's output (reuses the FAILED/traceback/exit-code detector).
_TEST_CMD = re.compile(
    r"\b(?:pytest|tsc|jest|vitest|mypy|ruff|eslint|"
    r"(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build|tsc|lint)|"
    r"go\s+test|cargo\s+(?:test|build)|make\s+(?:test|build|check))\b"
)

# ── edit detection ─────────────────────────────────────────────────────
# Two ways code gets edited across formats:
#   1. native edit/write tools (Claude Code, openai_messages)  -> canonical ∈ EDIT_TOOLS
#   2. edit-shaped shell commands (codex routes everything through bash) -> regex below
_EDIT_SHELL = re.compile(
    r"\bapply_patch\b"                       # codex's patch applier
    r"|\bsed\b\s+-i"                          # in-place sed
    r"|\b(?:tee|cat)\b[^\n|]*>"               # cat >file / tee file (write/truncate)
    r"|>>?\s*[\w./-]+\.\w+",                  # redirect into a path with an extension
)

# ── acceptance signals (positive) ──────────────────────────────────────
_GIT_COMMIT = re.compile(r"\bgit\b[^\n]*\bcommit\b")
_GIT_PUSH = re.compile(r"\bgit\b[^\n]*\bpush\b")
_GIT_ADD = re.compile(r"\bgit\b[^\n]*\badd\b")

# ── rejection signals (negative / veto) ────────────────────────────────
# ponytail: only UNAMBIGUOUS undo-of-work. Excludes `git checkout -b`/`checkout <branch>`
# (branch ops, not reverts) and bare `git stash` (often temporary). `reset --hard`,
# `revert`, `restore`, and `checkout -- <path>` are the real "throw away my edits" signals.
_GIT_REVERT = re.compile(
    r"\bgit\b[^\n]*\brevert\b"
    r"|\bgit\b[^\n]*\breset\b[^\n]*--hard"
    r"|\bgit\b[^\n]*\brestore\b"
    r"|\bgit\b[^\n]*\bcheckout\b\s+--\b"        # git checkout -- <path> = discard file edits
)
# user-language rejection — applied to user messages only
_USER_REJECT = re.compile(
    r"\b(?:revert|undo|roll ?back|that'?s wrong|don'?t do that|not what i|"
    r"bad (?:idea|change)|remove that|never mind|nvm)\b",
    re.IGNORECASE,
)


def _bash_command(it) -> str:
    """Extract the shell command string from a bash function_call's arguments."""
    try:
        args = json.loads(it.arguments)
    except (json.JSONDecodeError, TypeError):
        return ""
    # common keys across formats: command / cmd / script
    for k in ("command", "cmd", "script", "input"):
        v = args.get(k)
        if isinstance(v, str):
            return v
    return ""


def collect_signals(unit) -> dict:
    """Scan the whole session and tally concrete signals. No scoring here —
    just the evidence, so the scoring policy stays a single readable function."""
    edit_count = 0
    git_commit = git_push = git_add = git_revert = False
    edit_shell = False
    user_reject = False
    tests_passed = False

    for i, it in enumerate(unit):
        if it.type == "message" and it.role == "user":
            if _USER_REJECT.search(it.content or ""):
                user_reject = True
            continue
        if it.type != "function_call":
            continue
        c = canonical(it.name)
        if c in EDIT_TOOLS:
            edit_count += 1
            continue
        if c in BASH_TOOLS:
            cmd = _bash_command(it)
            if not cmd:
                continue
            if _EDIT_SHELL.search(cmd):
                edit_shell = True
                edit_count += 1
            if _GIT_COMMIT.search(cmd):
                git_commit = True
            if _GIT_PUSH.search(cmd):
                git_push = True
            if _GIT_ADD.search(cmd):
                git_add = True
            if _GIT_REVERT.search(cmd):
                git_revert = True
            if _TEST_CMD.search(cmd) and not _has_error(_next_output(unit, i)):
                # ponytail: empty output ("Bash completed with no output") also
                # passes _has_error → counts as a clean run, which is correct for
                # `tsc | grep err` that prints nothing on success.
                tests_passed = True

    return {
        "edit_count": edit_count,
        "edit_via_shell": edit_shell,
        "git_commit": git_commit,
        "git_push": git_push,
        "git_add": git_add,
        "git_revert": git_revert,
        "user_reject": user_reject,
        "tests_passed": tests_passed,
    }


def _next_output(unit, i) -> str:
    """Output of the function_call_output following call at index i (within 2 items)."""
    for j in range(i + 1, min(i + 3, len(unit))):
        if unit[j].type == "function_call_output":
            return unit[j].output or ""
    return ""


def score(sig: dict) -> dict:
    """Map collected signals to a likelihood + 0..1 score.

    Positive ladder (changes increasingly committed to disk/remote):
        push      -> strongest (left the machine)
        commit    -> strong
        add-only  -> weak (staged, not committed)
        nothing   -> uncertain (edits with no git activity)

    Strong veto: any rejection signal (user said revert/undo, or a git
    revert/reset/restore) caps the result at "low" regardless of commits —
    user rejection is the ground truth we most want to surface.
    """
    fired = []
    if sig["git_push"]:
        fired.append("git_push")
    if sig["git_commit"]:
        fired.append("git_commit")
    if sig["git_add"]:
        fired.append("git_add")
    if sig["tests_passed"]:
        fired.append("tests_passed")

    # positive ladder
    if sig["git_push"]:
        likelihood, s = "high", 0.9
    elif sig["git_commit"]:
        likelihood, s = "high", 0.8
    elif sig["git_add"]:
        likelihood, s = "medium", 0.5
    elif sig["tests_passed"]:
        # validated the change but didn't commit — agent self-confirmed, user
        # likely accepted manually. Stronger than no signal at all.
        likelihood, s = "medium", 0.45
    else:
        # edits, no git, no validation — neutral. NOT rejection: in Claude Code
        # the user commonly commits by hand off-trajectory, so absence of a git
        # trail is uninformative, not negative.
        likelihood, s = "medium", 0.4

    # strong veto
    if sig["user_reject"] or sig["git_revert"]:
        if sig["user_reject"]:
            fired.append("user_reject")
        if sig["git_revert"]:
            fired.append("git_revert")
        likelihood = "low"
        s = min(s, 0.2)

    return {
        "likelihood": likelihood,
        "score": round(s, 2),
        "edit_count": sig["edit_count"],
        "signals": fired,
    }


def annotate(unit, ctx):
    sig = collect_signals(unit)
    if sig["edit_count"] == 0:
        return {"no_edits": True, "likelihood": "none", "score": None,
                "edit_count": 0, "signals": []}
    return score(sig)


if __name__ == "__main__":
    # self-check: scoring policy on synthetic sig dicts
    def _sig(**kw):
        base = dict(edit_count=1, edit_via_shell=False, git_commit=False,
                    git_push=False, git_add=False, git_revert=False,
                    user_reject=False, tests_passed=False)
        base.update(kw)
        return base

    assert score(_sig(git_push=True))["likelihood"] == "high"
    assert score(_sig(git_commit=True))["likelihood"] == "high"
    assert score(_sig(git_add=True))["likelihood"] == "medium"
    assert score(_sig(tests_passed=True))["likelihood"] == "medium"  # validated, no commit
    assert score(_sig())["likelihood"] == "medium"  # edits, no signal — neutral, not rejection
    assert score(_sig())["score"] == 0.4
    # strong veto: commit + user reject -> capped at low
    v = score(_sig(git_commit=True, user_reject=True))
    assert v["likelihood"] == "low" and v["score"] <= 0.2, v
    assert "user_reject" in v["signals"]
    # git revert also vetoes
    assert score(_sig(git_push=True, git_revert=True))["likelihood"] == "low"

    # edit-shaped shell detection
    class _FC:
        type = "function_call"; name = "shell_command"
        def __init__(self, cmd): self.arguments = json.dumps({"command": cmd})
    s = collect_signals([_FC("apply_patch <<'EOF'\n*** Begin Patch")])
    assert s["edit_count"] == 1 and s["edit_via_shell"], s
    s = collect_signals([_FC("git commit -am wip"), _FC("sed -i 's/a/b/' f.py")])
    assert s["git_commit"] and s["edit_count"] == 1, s
    print("ok")
