import json

from trajlens.core import identity
from trajlens.core.model import (
    Trajectory, MessageItem, ReasoningItem, FunctionCallItem,
    FunctionCallOutputItem, Provenance,
)


def sniff(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("messages"), list)


def _as_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def parse(raw: dict) -> Trajectory:
    messages = raw["messages"]
    tools = raw.get("tools", []) or []
    items = []

    def p(origin):
        return Provenance(origin=origin)

    for mi, m in enumerate(messages):
        role = m.get("role")
        if role in ("system", "user", "developer"):
            items.append(MessageItem(role=role, content=_as_text(m.get("content")),
                                      provenance=p(f"messages[{mi}]")))
        elif role == "assistant":
            rc = m.get("reasoning_content")
            if rc:
                items.append(ReasoningItem(content=rc,
                                           provenance=p(f"messages[{mi}].reasoning_content")))
            for ci, tc in enumerate(m.get("tool_calls") or []):
                fn = tc.get("function", {})
                items.append(FunctionCallItem(
                    name=fn.get("name", ""), arguments=fn.get("arguments", "") or "",
                    call_id=tc.get("id") or f"m{mi}_c{ci}",
                    provenance=p(f"messages[{mi}].tool_calls[{ci}]")))
            content = m.get("content")
            if content:
                items.append(MessageItem(role="assistant", content=_as_text(content),
                                         provenance=p(f"messages[{mi}].content")))
        elif role == "tool":
            items.append(FunctionCallOutputItem(
                call_id=m.get("tool_call_id") or "", output=_as_text(m.get("content")),
                provenance=p(f"messages[{mi}]")))

    ch = identity.content_hash(items, tools)
    for it in items:
        if it.provenance:
            it.provenance.content_hash = ch
    return Trajectory(content_hash=ch, items=items, tools=tools,
                      meta=raw.get("meta_info", {}) or {})
