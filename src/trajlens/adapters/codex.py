"""Adapter for OpenAI Codex CLI session JSONL.

Format: one JSON object per line, each with {type, payload, timestamp}.
Line types: session_meta, turn_context, response_item, event_msg.
response_item.payload is already in Responses API shape:
  {type: "message"|"reasoning"|"function_call"|"function_call_output", ...}
"""
import json

from trajlens.core import identity
from trajlens.core.model import (
    Trajectory, MessageItem, ReasoningItem, FunctionCallItem,
    FunctionCallOutputItem, Provenance,
)


def sniff(raw) -> bool:
    if not isinstance(raw, list):
        return False
    if len(raw) < 2:
        return False
    first = raw[0] if isinstance(raw[0], dict) else {}
    return first.get("type") == "session_meta" and "payload" in first


def parse(raw: list[dict]) -> Trajectory:
    items = []
    meta = {}

    for li, line in enumerate(raw):
        lt = line.get("type")
        p = line.get("payload", {})

        if lt == "session_meta":
            meta = {k: p[k] for k in ("id", "model_provider", "cli_version", "cwd") if k in p}
            continue

        if lt == "turn_context":
            meta["model"] = p.get("model")
            continue

        if lt == "event_msg":
            pt = p.get("type")
            if pt == "user_message":
                text = p.get("content") or p.get("message", "")
                if isinstance(text, dict):
                    text = text.get("content", "")
                items.append(MessageItem(
                    role="user", content=str(text),
                    provenance=Provenance(origin=f"line[{li}]")))
            continue

        if lt == "response_item":
            pt = p.get("type")
            prov = Provenance(origin=f"line[{li}]")

            if pt == "message":
                # system/developer instructions or assistant text blocks
                role = p.get("role", "assistant")
                blocks = p.get("content") or []
                if isinstance(blocks, str):
                    items.append(MessageItem(role=role, content=blocks, provenance=prov))
                    continue
                text_parts = []
                for b in blocks:
                    if isinstance(b, dict):
                        bt = b.get("type", "")
                        if bt in ("input_text", "output_text", "text"):
                            text_parts.append(b.get("text", ""))
                if text_parts:
                    # ponytail: collapse all text blocks into one message item
                    items.append(MessageItem(
                        role=role, content="\n".join(text_parts), provenance=prov))

            elif pt == "reasoning":
                text = ""
                for s in (p.get("summary") or []):
                    if isinstance(s, dict):
                        text += s.get("text", "")
                if text:
                    items.append(ReasoningItem(content=text, provenance=prov))

            elif pt == "function_call":
                items.append(FunctionCallItem(
                    name=p.get("name", ""),
                    arguments=p.get("arguments", "") or "",
                    call_id=p.get("call_id", f"codex_{li}"),
                    provenance=prov))

            elif pt == "function_call_output":
                items.append(FunctionCallOutputItem(
                    call_id=p.get("call_id", ""),
                    output=str(p.get("output", "")),
                    provenance=prov))

    tools = []  # codex doesn't embed tool schemas in session logs
    ch = identity.content_hash(items, tools)
    for it in items:
        if it.provenance:
            it.provenance.content_hash = ch
    return Trajectory(content_hash=ch, items=items, tools=tools, meta=meta)
