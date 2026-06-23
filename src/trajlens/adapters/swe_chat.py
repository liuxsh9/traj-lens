"""Adapter for SWE-chat dataset (SALT-NLP/SWE-chat-by-agent).

Format: {session_id, rows: [{turn_number, role, turn_type, content, tool_name,
tool_call_id, tool_input_json, file_path, ...}]}

turn_type values: user_prompt, assistant_response, tool_use, tool_result,
system_injected, file_snapshot, progress, metadata.
"""
import json

from trajlens.core import identity
from trajlens.core.model import (
    Trajectory, MessageItem, ReasoningItem, FunctionCallItem,
    FunctionCallOutputItem, Provenance,
)


def sniff(raw) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get("rows"), list) and "session_id" in raw


def parse(raw: dict) -> Trajectory:
    rows = raw["rows"]
    items = []
    meta = {"source": "swe_chat", "session_id": raw.get("session_id", "")}

    for i, r in enumerate(rows):
        tt = r.get("turn_type", "")
        role = r.get("role", "")
        content = r.get("content") or ""
        prov = Provenance(origin=f"row[{i}]")

        if tt == "user_prompt":
            items.append(MessageItem(role="user", content=content, provenance=prov))

        elif tt == "assistant_response":
            items.append(MessageItem(role="assistant", content=content, provenance=prov))

        elif tt == "system_injected":
            if content:
                items.append(MessageItem(role="system", content=content, provenance=prov))

        elif tt == "tool_use":
            tool_name = r.get("tool_name") or ""
            tool_input = r.get("tool_input_json") or "{}"
            if isinstance(tool_input, dict):
                tool_input = json.dumps(tool_input, ensure_ascii=False)
            # ponytail: some SWE-chat variants embed tool info in content JSON
            _KEY_TO_TOOL = {"command": "bash", "pattern": "glob",
                            "file_path": "read", "filePath": "read"}
            if not tool_name and content.startswith("{"):
                try:
                    cj = json.loads(content)
                    if isinstance(cj, dict) and cj:
                        key = next(iter(cj))
                        tool_name = _KEY_TO_TOOL.get(key, key)
                        tool_input = content
                except (json.JSONDecodeError, StopIteration):
                    pass
            items.append(FunctionCallItem(
                name=tool_name or "unknown",
                arguments=tool_input,
                call_id=r.get("tool_call_id") or f"sc_{i}",
                provenance=prov))

        elif tt == "tool_result":
            items.append(FunctionCallOutputItem(
                call_id=r.get("tool_call_id") or f"sc_{i}",
                output=content,
                provenance=prov))

        # skip metadata, file_snapshot, progress — not conversational

    tools = []
    ch = identity.content_hash(items, tools)
    for it in items:
        if it.provenance:
            it.provenance.content_hash = ch
    return Trajectory(content_hash=ch, items=items, tools=tools, meta=meta)
