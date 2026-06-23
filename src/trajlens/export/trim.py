"""Trim validation — four rules from §8.2."""
from dataclasses import dataclass, field


@dataclass
class TrimResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def validate_trim(items: list, start: int = 0, end: int | None = None) -> TrimResult:
    """Validate that items[start:end] is a legal trim range.

    R1 (boundary alignment): always ok at items level.
    R2 (tool pairing): function_call ↔ function_call_output must pair.
    R3 (prefix completeness): start must be 0 (prefix mode only).
    R4 (trainable ending): last item must be assistant message or function_call_output.
    """
    if end is None:
        end = len(items)
    violations: list[str] = []

    if start < 0 or end > len(items) or start >= end:
        return TrimResult(ok=False, violations=["invalid range"])

    # ponytail: R1 always passes for items-level trim; relevant for raw-byte mode
    sliced = items[start:end]

    # R2: tool pairing
    calls = {it.call_id for it in sliced if it.type == "function_call"}
    outputs = {it.call_id for it in sliced if it.type == "function_call_output"}
    unpaired_calls = calls - outputs
    unpaired_outputs = outputs - calls
    if unpaired_calls:
        violations.append(f"R2: unpaired function_call(s): {unpaired_calls}")
    if unpaired_outputs:
        violations.append(f"R2: unpaired function_call_output(s): {unpaired_outputs}")

    # R3: prefix completeness
    if start != 0:
        violations.append("R3: non-prefix trim (start != 0) not supported in default mode")

    # R4: trainable ending
    last = sliced[-1]
    if last.type == "function_call":
        violations.append("R4: cannot end on function_call (incomplete tool loop)")
    elif last.type == "reasoning":
        violations.append("R4: cannot end on reasoning (no trainable target)")

    return TrimResult(ok=len(violations) == 0, violations=violations)
