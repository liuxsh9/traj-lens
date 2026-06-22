import hashlib
import json


def _canonical_args(arguments: str) -> str:
    try:
        return json.dumps(json.loads(arguments), sort_keys=True,
                          ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return arguments


def _semantic(item) -> dict:
    # Excludes volatile meta: call_id, provenance, step/run, timestamps, token usage.
    # function_call <-> output pairing is preserved by ORDER, not id.
    if item.type == "message":
        return {"k": "m", "role": item.role, "content": item.content}
    if item.type == "reasoning":
        return {"k": "r", "content": item.content}
    if item.type == "function_call":
        return {"k": "c", "name": item.name, "arguments": _canonical_args(item.arguments)}
    if item.type == "function_call_output":
        return {"k": "o", "output": item.output}
    raise ValueError(f"unknown item type: {item.type}")


def content_hash(items, tools=None) -> str:
    projection = {"tools": tools or [], "items": [_semantic(it) for it in items]}
    blob = json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
