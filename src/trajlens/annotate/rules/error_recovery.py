"""error_recovery: detect tool errors in a step and whether the agent recovered."""
import json
import re

from trajlens.core.tool_aliases import READ_TOOLS, canonical

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
_SUMMARY_LINE = re.compile(
    r"^(?:FAILED [\w/].*|(?:Error|ERROR):.*|.*(?:ModuleNotFoundError|ImportError|SyntaxError|FileNotFoundError).*|.*(?:exit code|exited with) \d+.*|fatal:.*|panic:.*)$",
    re.MULTILINE,
)

_EXIT_CODE_RE = re.compile(r"(?:exit code|exited with) (\d+)")
# ponytail: 130=SIGINT(ctrl-c), 137=SIGKILL, 141=SIGPIPE — normal in pipelines, not real errors
_BENIGN_EXIT_CODES = {130, 137, 141}
_GREP_RE = re.compile(r"(?:^|[;&|]\s*)grep(?:\s|$)")

_PATH_KEYS = {"file_path", "path", "file", "filename"}
_ACTION_KEYS = {"command", "cmd", "code"}


def _extract_path(args_json: str) -> str | None:
    try:
        args = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for k in _PATH_KEYS:
        if k in args and isinstance(args[k], str):
            return args[k]
    return None


def _extract_action(args_json: str) -> str | None:
    try:
        args = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for k in _ACTION_KEYS:
        if k in args and isinstance(args[k], str):
            return " ".join(args[k].split())
    return None


def _has_error(output: str) -> bool:
    if not output:
        return False
    # ponytail: exit code check first — most reliable signal
    m = _EXIT_CODE_RE.search(output)
    if m and m.group(1) != "0" and int(m.group(1)) not in _BENIGN_EXIT_CODES:
        return True
    return bool(_STRONG_ERROR.search(output))


def _is_benign_search_miss(command: str | None, output: str) -> bool:
    if not command or not _GREP_RE.search(command):
        return False
    m = _EXIT_CODE_RE.search(output)
    return bool(m and m.group(1) == "1" and not _STRONG_ERROR.search(output))


def _has_tool_error(output: str, args_json: str | None) -> bool:
    if not output:
        return False
    command = _extract_action(args_json or "")
    if _is_benign_search_miss(command, output):
        return False
    return _has_error(output)


def _is_read_only_tool(tool_name: str | None) -> bool:
    return bool(tool_name and canonical(tool_name) in READ_TOOLS)


def _error_summary(output: str) -> str:
    if not output:
        return ""
    tb = re.search(r"Traceback \(most recent call last\).*?(?=\n\[|$)", output, re.DOTALL)
    if tb:
        return tb.group(0)[:200]
    m = _SUMMARY_LINE.search(output)
    if m:
        return m.group(0)[:200]
    return output[:200]


def _step_tool_signature(items) -> set[tuple[str, str | None, str | None]]:
    """(tool_name, file_path, command/code) tuples — used to detect strategy change."""
    sig = set()
    for it in items:
        if it.type == "function_call":
            sig.add((canonical(it.name), _extract_path(it.arguments), _extract_action(it.arguments)))
    return sig


def annotate(unit, ctx):
    """Returns {"has_error": bool, "recovered": bool|null, "error_summary": str|null}.

    Scans current step for function_call_output with error patterns.
    If errors found, checks whether the next step in the same run changed strategy.
    """
    # Collect errors in current step
    errors = []
    calls_by_id = {it.call_id: it for it in unit if it.type == "function_call"}
    for it in unit:
        call = calls_by_id.get(it.call_id) if it.type == "function_call_output" else None
        if call and _is_read_only_tool(call.name):
            continue
        args_json = call.arguments if call else None
        if it.type == "function_call_output" and _has_tool_error(it.output, args_json):
            errors.append(_error_summary(it.output))

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
