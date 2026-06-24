"""error_recovery: detect tool errors in a step and whether the agent recovered."""
import json
import re

from trajlens.core.tool_aliases import canonical

# ponytail: strong signals — structural markers that reliably indicate tool-level errors,
# not just the word "error" appearing in source code the tool returned.
_STRONG_ERROR = re.compile(
    r"(?:^|\n)Traceback \(most recent call last\)"   # Python traceback at line start
    r"|(?:^|\n)(?:Error|ERROR):"                      # "Error:" at line start (tooling convention)
    r"|[Cc]ommand not found"
    r"|[Pp]ermission denied"
    r"|FAILED [\w/]+"                                 # pytest "FAILED tests/foo.py::bar"
    r"|(?:ModuleNotFoundError|ImportError|SyntaxError|FileNotFoundError)"
    r"|returned non-zero"
    r"|(?:^|\n)fatal:"                                # git fatal
    r"|(?:^|\n)panic:",                               # Go panic
    re.MULTILINE,
)

_EXIT_CODE_RE = re.compile(r"(?:exit code|exited with) (\d+)")
# ponytail: 130=SIGINT(ctrl-c), 137=SIGKILL, 141=SIGPIPE — normal in pipelines, not real errors
_BENIGN_EXIT_CODES = {130, 137, 141}

_PATH_KEYS = {"file_path", "path", "file", "filename"}


def _extract_path(args_json: str) -> str | None:
    try:
        args = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for k in _PATH_KEYS:
        if k in args and isinstance(args[k], str):
            return args[k]
    return None


def _has_error(output: str) -> bool:
    if not output:
        return False
    # ponytail: exit code check first — most reliable signal
    m = _EXIT_CODE_RE.search(output)
    if m and m.group(1) != "0" and int(m.group(1)) not in _BENIGN_EXIT_CODES:
        return True
    return bool(_STRONG_ERROR.search(output))


def _step_tool_signature(items) -> set[tuple[str, str | None]]:
    """(tool_name, file_path) pairs in a step — used to detect strategy change."""
    sig = set()
    for it in items:
        if it.type == "function_call":
            sig.add((canonical(it.name), _extract_path(it.arguments)))
    return sig


def annotate(unit, ctx):
    """Returns {"has_error": bool, "recovered": bool|null, "error_summary": str|null}.

    Scans current step for function_call_output with error patterns.
    If errors found, checks whether the next step in the same run changed strategy.
    """
    # Collect errors in current step
    errors = []
    for it in unit:
        if it.type == "function_call_output" and _has_error(it.output):
            errors.append(it.output[:200])

    if not errors:
        return {"has_error": False, "recovered": None, "error_summary": None}

    current_run = unit[0].run_id if unit else None
    current_step = unit[0].step_id if unit else None

    # Find next step in same run from ctx
    next_step_items = []
    if current_run is not None and current_step is not None:
        for it in ctx:
            if it.run_id == current_run and it.step_id is not None and it.step_id == current_step + 1:
                next_step_items.append(it)

    if not next_step_items:
        return {"has_error": True, "recovered": None, "error_summary": errors[0]}

    # Compare tool signatures: different tools or different files = strategy change = recovery attempt
    current_sig = _step_tool_signature(unit)
    next_sig = _step_tool_signature(next_step_items)
    recovered = current_sig != next_sig

    return {"has_error": True, "recovered": recovered, "error_summary": errors[0]}
