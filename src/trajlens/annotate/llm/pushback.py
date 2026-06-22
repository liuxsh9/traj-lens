"""USER_TURN LLM annotator — classifies user pushback (correction/rejection/failure_report/none)."""
import json

from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["correction", "rejection", "failure_report", "non_pushback"]},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}

# Fused from SWE-chat (arXiv:2604.20779) E.2.4 definitions + tightened correction boundary
SYSTEM_PROMPT = """You classify whether a user prompt in a coding agent session is pushback against the agent's preceding action.

Pushback = the user resists, corrects, or redirects the agent IN RESPONSE TO what the agent just did. A prompt that simply gives a new instruction — even a detailed or forceful one — is NOT pushback unless it reacts to the agent's prior behavior.

Categories (choose exactly one):

- correction — The user reacts to the agent's prior action by: correcting a misunderstanding, pointing out errors, providing missing context the agent should have known, or changing direction BECAUSE the agent went the wrong way.
  KEY SIGNAL: the prompt references or implies something the agent did wrong or missed.
  Examples: "I said X not Y", "you changed the wrong file", "actually the API uses POST not GET", "forget that approach, try Y", "on second thought skip the tests" (redirecting after seeing agent's plan), "install docker compose — right now it gives an error" (correcting a missing dependency the agent should have included)

- rejection — The user explicitly rejects, reverts, or refuses the agent's output WITHOUT providing a specific correction.
  Examples: "undo that", "revert the last change", "no", "that's wrong", "put it back the way it was"

- failure_report — The user reports that the agent's output does not work: bugs, errors, test failures, broken behavior.
  Examples: "this still doesn't work", "it's still crashing", "same error, try again", "the tests are failing"

- non_pushback — The prompt moves the session forward normally: a new task, a follow-up instruction, building on agent output, asking a question, continuing, or routine iteration. This is the DEFAULT when the prompt does not clearly react to a problem with the agent's prior action.
  Examples: "now add a login page", "good, also add unit tests", "continue", "change the button color to blue", "$commit", "cleanup these commits"

Disambiguation:
- correction vs non_pushback: If the prompt could be read as a standalone new instruction with no reference to the agent doing something wrong, choose non_pushback. Correction requires the user to be REACTING to the agent's prior action.
- correction vs rejection: correction provides a specific fix or new direction; rejection just says "no"/"undo" without explaining what to do instead.
- failure_report vs rejection: failure_report = "it doesn't work" (broken); rejection = "I don't want that" (unwanted even if functional).
- Repeating a previous instruction verbatim or with minor edits is non_pushback (the user may be retrying or continuing), UNLESS the repetition explicitly references agent failure ("I already told you to...").

When uncertain, lean toward non_pushback — pushback should be clear from the text.

Respond in valid JSON only:
{"label": "<one of: correction, rejection, failure_report, non_pushback>", "reason": "<1-2 sentence explanation>"}"""

_DEFAULT = {"category": "none", "confidence": 0.0, "reason": "unparseable response"}


def _summarize(it: Item, max_chars: int = 200) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"{it.role}: {c}"
    if it.type == "reasoning":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"reasoning: {c}"
    if it.type == "function_call":
        return f"call {it.name}({it.arguments[:100]})"
    if it.type == "function_call_output":
        return f"output: {it.output[:100]}"
    return ""


def _detect_prior_similar(user_text: str, ctx: list) -> str | None:
    """Check if a prior user message is similar (shares >50% words). Cheap heuristic."""
    words = set(user_text.lower().split())
    if len(words) < 3:
        return None
    for it in ctx:
        if it.type == "message" and it.role == "user":
            prior_words = set(it.content.lower().split())
            if len(prior_words) < 3:
                continue
            overlap = len(words & prior_words) / max(len(words), len(prior_words))
            if overlap > 0.5 and it.content != user_text:
                return it.content[:120]
    return None


def build(unit: list, ctx: list) -> list[dict]:
    user_text = next((it.content for it in unit if it.type == "message" and it.role == "user"), "")
    unit_ids = {id(it) for it in unit}
    before = [it for it in ctx if id(it) not in unit_ids]

    # recent window for detailed context (last 5 items), keeps prompt compact
    recent = [_summarize(it) for it in before[-5:]]
    context_summary = "\n".join(recent) if recent else "(no prior context)"

    # scan ALL preceding items for similar user messages (cheap string op, not sent to LLM)
    similar = _detect_prior_similar(user_text, before)
    repetition_note = ""
    if similar:
        repetition_note = f"\n\n[NOTE: A similar earlier user message was: \"{similar}\"]\n"

    prompt = f"Preceding conversation context:\n{context_summary}{repetition_note}\n\nUser prompt to classify:\n{user_text}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


# ponytail: SWE-chat uses "non_pushback"; we normalize to "none" internally for consistency
_LABEL_MAP = {"non_pushback": "none", "correction": "correction",
              "rejection": "rejection", "failure_report": "failure_report"}


def parse(response: str) -> dict:
    data = _loads(response)
    if data is None:
        return dict(_DEFAULT)
    raw_label = data.get("label", data.get("category", "non_pushback"))
    category = _LABEL_MAP.get(raw_label, "none")
    return {
        "category": category,
        "confidence": data.get("confidence", 0.0),
        "reason": data.get("reason", ""),
    }


def _loads(response: str) -> dict | None:
    for candidate in (response, _strip_fences(response), _braces(response)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _braces(s: str) -> str:
    lo, hi = s.find("{"), s.rfind("}")
    return s[lo:hi + 1] if 0 <= lo < hi else ""
