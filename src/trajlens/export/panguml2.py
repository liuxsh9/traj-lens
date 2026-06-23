"""panguml2 SFT exporter — byte-faithful from raw blob, conversion fallback from items."""
import json
import logging

from trajlens.export import EXPORTERS

log = logging.getLogger("trajlens.export")


def items_to_messages(items: list) -> list[dict]:
    """Reconstruct OpenAI Chat Completions messages from canonical items.

    Groups consecutive assistant-side items (reasoning + function_call + message)
    into a single assistant message with reasoning_content + tool_calls.
    """
    messages: list[dict] = []
    i = 0
    while i < len(items):
        it = items[i]

        if it.type == "message":
            msg: dict = {"role": it.role, "content": it.content}
            if it.role == "assistant":
                # ponytail: look back for reasoning that was already emitted —
                # actually, we accumulate forward: peek ahead for reasoning/tool_calls
                # that belong to this assistant turn.
                # But in items-canonical, reasoning comes BEFORE the assistant message.
                # So we need to look backward and attach.
                pass
            messages.append(msg)
            i += 1

        elif it.type == "reasoning":
            # Collect reasoning + subsequent function_calls into one assistant message
            reasoning = it.content
            tool_calls = []
            i += 1
            while i < len(items) and items[i].type == "function_call":
                fc = items[i]
                tool_calls.append({
                    "id": fc.call_id,
                    "type": "function",
                    "function": {"name": fc.name, "arguments": fc.arguments},
                })
                i += 1
            # Check if next is an assistant message (the "done" response)
            # If so, that will be emitted on its own — reasoning attaches here
            msg = {"role": "assistant", "content": "", "reasoning_content": reasoning}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)

        elif it.type == "function_call":
            # Standalone function_call without preceding reasoning
            msg = {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": it.call_id, "type": "function",
                    "function": {"name": it.name, "arguments": it.arguments},
                }],
            }
            # Collect consecutive function_calls
            i += 1
            while i < len(items) and items[i].type == "function_call":
                fc = items[i]
                msg["tool_calls"].append({
                    "id": fc.call_id, "type": "function",
                    "function": {"name": fc.name, "arguments": fc.arguments},
                })
                i += 1
            messages.append(msg)

        elif it.type == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": it.call_id,
                "content": it.output,
            })
            i += 1

        else:
            i += 1

    return messages


def _set_weights(messages: list[dict]) -> list[dict]:
    """Set weight=1.0 on assistant, 0.0 on everything else."""
    for m in messages:
        m["weight"] = 1.0 if m.get("role") == "assistant" else 0.0
    return messages


def export_sft(conn, content_hash: str, *, trim_end: int | None = None,
               blob_dir: str = "blobs") -> dict | None:
    """Export one trajectory as panguml2 SFT record.

    Returns dict with {version, meta_info, tools, messages} or None if not found.
    """
    from trajlens.store import repo

    traj = repo.get_trajectory(conn, content_hash)
    if traj is None:
        return None

    # Try byte-faithful: load raw blob
    row = conn.execute(
        "SELECT raw_sha FROM ingestions WHERE content_hash=? AND raw_sha IS NOT NULL LIMIT 1",
        (content_hash,)).fetchone()

    if row and row["raw_sha"]:
        blob_row = conn.execute(
            "SELECT path FROM raw_blobs WHERE raw_sha=?", (row["raw_sha"],)).fetchone()
        if blob_row:
            import pathlib
            p = pathlib.Path(blob_row["path"])
            if p.exists():
                try:
                    raw = json.loads(p.read_text())
                    if isinstance(raw, dict) and "messages" in raw:
                        msgs = raw["messages"]
                        if trim_end is not None:
                            msgs = msgs[:trim_end]
                        result = {
                            "version": raw.get("version", "2.0.0"),
                            "meta_info": {**raw.get("meta_info", {}),
                                          "traj_lens_content_hash": content_hash,
                                          "export_mode": "byte_faithful"},
                            "tools": raw.get("tools", []),
                            "messages": _set_weights(msgs),
                        }
                        log.info("exported %s (byte-faithful, %d messages)", content_hash[:8], len(msgs))
                        return result
                except (json.JSONDecodeError, KeyError):
                    pass

    # Conversion fallback: items → messages
    items = list(traj.items)
    if trim_end is not None:
        items = items[:trim_end]

    msgs = items_to_messages(items)
    result = {
        "version": "2.0.0",
        "meta_info": {"traj_lens_content_hash": content_hash,
                      "export_mode": "converted"},
        "tools": traj.tools,
        "messages": _set_weights(msgs),
    }
    log.info("exported %s (converted, %d messages)", content_hash[:8], len(msgs))
    return result


EXPORTERS.register("panguml2", export_sft)
