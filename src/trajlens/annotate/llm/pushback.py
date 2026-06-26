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

- correction — The user steers or corrects the agent because the agent FELL SHORT of what was asked: correcting a misunderstanding, pointing out errors, providing context the agent should have had, or fixing work that missed the existing target.
  KEY SIGNAL: the agent is at fault — it misread the request, made a mistake, or did the wrong thing given what the user had already specified. The user is restoring the agent to a target that was already in play.
  Examples: "I said X not Y", "you changed the wrong file", "actually the API uses POST not GET", "the scroll lock should stay where the user left it, not reset to 0,0" (implying current behavior is wrong)
  NOT correction — a requirement change. If the user simply wants something DIFFERENT now — a new value, new copy, new feature, a change of mind — and the agent had correctly done what was originally asked, that is non_pushback, not correction. The agent didn't fail; the spec moved. Examples: "change the text to 你好世界", "actually make the button blue instead", "let's add pagination too", "on second thought skip the tests". These give a new target; they don't say the agent missed the old one.

- rejection — The user explicitly rejects, reverts, or refuses the agent's output WITHOUT providing a specific correction.
  Examples: "undo that", "revert the last change", "no", "that's wrong", "put it back the way it was"

- failure_report — The user reports that something is wrong, broken, or not behaving as expected — whether or not they explicitly say "it doesn't work." This includes describing symptoms, pasting error messages, or showing unexpected output that implies the agent's work has a problem.
  Examples: "this still doesn't work", "it's still crashing", "same error, try again", "the tests are failing", "每个部分都出现了两次" (describing a duplicate-rendering bug), "buffer-list-update-hook fires extremely often" (reporting a side effect of agent's change)

- non_pushback — The prompt moves the session forward normally: a new task, a follow-up instruction, building on agent output, asking a question, continuing, or routine iteration. This is the DEFAULT when the prompt does not clearly react to a problem with the agent's prior action.
  Examples: "now add a login page", "good, also add unit tests", "continue", "change the button color to blue", "$commit", "cleanup these commits"
  SPECIAL: system-generated interruptions like "[Request interrupted by user for tool use]" or "[Request interrupted by user]" are always non_pushback — they are automatic cancel signals, not user-authored pushback.

Disambiguation:
- correction vs non_pushback (THE KEY TEST — agent fault): Ask "did the agent fail to do what was asked, or did the user change what they want?" A correction means the agent missed an EXISTING target (wrong file, misread request, broke something). A requirement change means the user moved the target — they want something new or different now, and the agent had correctly done the original ask. Requirement changes are non_pushback even though they react to agent output and adjust course. Only the agent-fault case is correction. If there is NO preceding agent action, choose non_pushback.
- correction vs rejection: correction provides a specific fix or new direction; rejection just says "no"/"undo" without explaining what to do instead.
- failure_report vs rejection: failure_report = "it doesn't work" (broken); rejection = "I don't want that" (unwanted even if functional).
- Repeating a previous instruction verbatim or with minor edits is non_pushback (the user may be retrying or continuing), UNLESS the repetition explicitly references agent failure ("I already told you to...").
- Preemptive instructions ≠ corrections: "Do NOT do X" or "Make sure to Y" in a new task description is a guardrail for future behavior, NOT a reaction to past mistakes. Only classify as correction if the agent ALREADY did the unwanted action and the user is telling it to stop. Example: user gives a task saying "Do NOT edit the plan file" — if the agent hasn't touched the plan file, this is non_pushback even though the language sounds corrective. The user is setting boundaries on a new task, not reacting to a mistake.
- No prior agent action → always non_pushback: If the context shows no preceding assistant response or tool call, the user prompt cannot be pushback — it is starting a new task.

Key principle — implicit pushback: After an agent action, if the user describes a problem, unexpected behavior, or undesirable state WITHOUT explicitly blaming the agent, it is STILL pushback (failure_report or correction). The user doesn't need to say "you broke it" — describing the broken state is enough. Only default to non_pushback when the user's message is clearly about a NEW unrelated topic or there is no prior agent action.

Think step by step:
1. What did the agent just do? (Look at the preceding context.)
2. Is the user's message ABOUT what the agent did, or about something new/unrelated?
3. If about what the agent did: did the AGENT FAIL (missed an existing target, made a mistake)? Or did the USER CHANGE the requirement (wants something new/different now, agent had done the original ask correctly)?
   - Agent failed → failure_report (broken/error) | correction (specific fix) | rejection (just "no"/"undo")
   - User changed the requirement → non_pushback

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
    raw = next((it.content for it in unit if it.type == "message" and it.role == "user"), "")
    # ponytail: cap head-only; pushback signal is always upfront
    user_text = raw[:1500]
    unit_ids = {id(it) for it in unit}
    before = [it for it in ctx if id(it) not in unit_ids]

    # recent window for detailed context (last 5 items), keeps prompt compact
    recent = [_summarize(it, max_chars=150) for it in before[-5:]]
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
