"""Adapter for Claude Code session JSONL (~/.claude/projects/*/*.jsonl).

Format: one JSON object per line, each with {type, message?, attachment?, ...}.
Conversational types: system, user, assistant, attachment.
Non-conversational (skipped): last-prompt, custom-title, mode, queue-operation.

assistant.message.content[] blocks use Anthropic Messages API shape:
  thinking, text, tool_use (with id/name/input).
Tool results arrive as a subsequent 'user' line whose message.content[]
contains {type:"tool_result", tool_use_id, content}.
"""
import json

from trajlens.core import identity
from trajlens.core.model import (
    Trajectory, MessageItem, ReasoningItem, FunctionCallItem,
    FunctionCallOutputItem, Provenance,
)


def sniff(raw) -> bool:
    if not isinstance(raw, list) or len(raw) < 2:
        return False
    # CC logs: lines with type in {system, user, assistant, attachment, ...} and
    # assistant lines carry message.content (Anthropic Messages API content blocks).
    types = {o.get("type") for o in raw if isinstance(o, dict)}
    if "assistant" not in types:
        return False
    return any(
        isinstance(o.get("message"), dict) and isinstance(o["message"].get("content"), list)
        for o in raw if isinstance(o, dict) and o.get("type") == "assistant"
    )


def _as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def parse(raw: list[dict]) -> Trajectory:
    items = []
    meta = {}
    skip_types = {"last-prompt", "custom-title", "mode", "queue-operation"}

    for li, line in enumerate(raw):
        lt = line.get("type")
        if lt in skip_types:
            continue

        if lt == "attachment":
            # attachments are hooks/metadata, not conversational — skip
            continue

        msg = line.get("message")
        if not isinstance(msg, dict):
            continue

        prov = Provenance(origin=f"line[{li}]")

        if lt == "system":
            text = msg.get("content", "")
            if isinstance(text, list):
                text = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)
            if text:
                items.append(MessageItem(role="system", content=str(text), provenance=prov))

        elif lt == "user":
            content = msg.get("content")
            if isinstance(content, list):
                # may contain tool_result blocks (from tool use) or text blocks
                for bi, block in enumerate(content):
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type", "")
                    if bt == "tool_result":
                        out_content = block.get("content", "")
                        if isinstance(out_content, list):
                            out_content = "\n".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in out_content)
                        items.append(FunctionCallOutputItem(
                            call_id=block.get("tool_use_id", ""),
                            output=_as_str(out_content),
                            provenance=Provenance(origin=f"line[{li}].content[{bi}]")))
                    elif bt == "text":
                        text = block.get("text", "")
                        if text:
                            items.append(MessageItem(
                                role="user", content=text,
                                provenance=Provenance(origin=f"line[{li}].content[{bi}]")))
            elif isinstance(content, str):
                if content:
                    items.append(MessageItem(role="user", content=content, provenance=prov))
            else:
                # message.content is the text directly on the msg object
                role_content = msg.get("content", "")
                if role_content:
                    items.append(MessageItem(role="user", content=str(role_content), provenance=prov))

        elif lt == "assistant":
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for bi, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                bt = block.get("type", "")
                bprov = Provenance(origin=f"line[{li}].content[{bi}]")

                if bt == "thinking":
                    text = block.get("thinking", "")
                    if text:
                        items.append(ReasoningItem(content=text, provenance=bprov))

                elif bt == "text":
                    text = block.get("text", "")
                    if text:
                        items.append(MessageItem(
                            role="assistant", content=text, provenance=bprov))

                elif bt == "tool_use":
                    inp = block.get("input", {})
                    items.append(FunctionCallItem(
                        name=block.get("name", ""),
                        arguments=json.dumps(inp, ensure_ascii=False) if isinstance(inp, dict) else str(inp),
                        call_id=block.get("id", f"cc_{li}_{bi}"),
                        provenance=bprov))

    tools = []
    ch = identity.content_hash(items, tools)
    for it in items:
        if it.provenance:
            it.provenance.content_hash = ch
    meta["source"] = "claude_code"
    return Trajectory(content_hash=ch, items=items, tools=tools, meta=meta)
