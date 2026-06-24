"""hard_interruption: detect sessions that ended abnormally."""
import re

_ERROR_PATTERNS = re.compile(
    r"(?i)(?:traceback|error|exception|FAILED|fatal|panic)",
)


def annotate(unit, ctx):
    """Returns {"interrupted": bool, "reason": str|null}.

    Checks the tail of the session for abnormal termination patterns.
    """
    if not ctx:
        return {"interrupted": False, "reason": None}

    last = ctx[-1]

    # Dangling tool call with no output
    if last.type == "function_call":
        return {"interrupted": True, "reason": "dangling_tool_call"}

    # Session ends on a tool error
    if last.type == "function_call_output" and _ERROR_PATTERNS.search(last.output or ""):
        return {"interrupted": True, "reason": "ends_on_error"}

    # Only user messages, no assistant response at all
    has_assistant = any(
        it.type == "message" and it.role == "assistant"
        or it.type in ("function_call", "reasoning")
        for it in ctx
    )
    if not has_assistant:
        return {"interrupted": True, "reason": "no_assistant_response"}

    return {"interrupted": False, "reason": None}
