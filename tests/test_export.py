"""Tests for export: trim validation + panguml2 exporter."""
import json

from tests.conftest import FIXTURES
from trajlens.adapters import detect_and_parse
from trajlens.core.model import parse_item
from trajlens.export.trim import validate_trim
from trajlens.store import db as dbmod, repo


def _db(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    return conn


# ── Trim validation ──────────────────────────────────────────────────

def _items(specs):
    """Build items from shorthand specs like ('message','user'), ('function_call',), etc."""
    items = []
    cid = 0
    for spec in specs:
        if spec[0] == "message":
            items.append(parse_item({"type": "message", "role": spec[1], "content": "x"}))
        elif spec[0] == "reasoning":
            items.append(parse_item({"type": "reasoning", "content": "x"}))
        elif spec[0] == "function_call":
            items.append(parse_item({"type": "function_call", "name": "f",
                                     "arguments": "{}", "call_id": f"c{cid}"}))
            cid += 1
        elif spec[0] == "function_call_output":
            items.append(parse_item({"type": "function_call_output",
                                     "call_id": f"c{cid-1}", "output": "ok"}))
    return items


def test_trim_prefix_ok():
    items = _items([("message", "user"), ("reasoning",),
                    ("function_call",), ("function_call_output",),
                    ("message", "assistant")])
    r = validate_trim(items)
    assert r.ok


def test_trim_r2_unpaired_call():
    items = _items([("message", "user"), ("function_call",),
                    ("message", "assistant")])
    r = validate_trim(items)
    assert not r.ok
    assert any("R2" in v for v in r.violations)


def test_trim_r3_mid_cut():
    items = _items([("message", "user"), ("message", "assistant"),
                    ("message", "user"), ("message", "assistant")])
    r = validate_trim(items, start=2, end=4)
    assert not r.ok
    assert any("R3" in v for v in r.violations)


def test_trim_r4_bad_ending_function_call():
    items = _items([("message", "user"), ("function_call",)])
    r = validate_trim(items)
    assert not r.ok
    assert any("R4" in v for v in r.violations)


def test_trim_r4_bad_ending_reasoning():
    items = _items([("message", "user"), ("reasoning",)])
    r = validate_trim(items)
    assert not r.ok
    assert any("R4" in v for v in r.violations)


# ── panguml2 exporter ────────────────────────────────────────────────

def test_panguml2_byte_faithful_roundtrip(tmp_path):
    """Ingest a panguml2 fixture, export it, verify structure matches."""
    import trajlens.export.panguml2  # noqa: F401
    from trajlens.export import EXPORTERS

    conn = _db(tmp_path)
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))
    blob_dir = str(tmp_path / "blobs")
    repo.put_trajectory(conn, traj, source_path="test.json",
                        raw_bytes=raw_bytes, blob_dir=blob_dir)

    exporter = EXPORTERS.get("panguml2")
    result = exporter(conn, traj.content_hash, blob_dir=blob_dir)

    assert result is not None
    assert result["version"] == "2.0.0"
    assert result["meta_info"]["export_mode"] == "byte_faithful"
    assert len(result["messages"]) == 5  # system + user + assistant + tool + assistant
    # weights: assistant=1.0, others=0.0
    for m in result["messages"]:
        if m["role"] == "assistant":
            assert m["weight"] == 1.0
        else:
            assert m["weight"] == 0.0


def test_panguml2_conversion_fallback(tmp_path):
    """Ingest without raw blob, export via conversion."""
    import trajlens.export.panguml2  # noqa: F401
    from trajlens.export import EXPORTERS

    conn = _db(tmp_path)
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))
    # no blob_dir → no raw blob stored
    repo.put_trajectory(conn, traj, source_path="test.json")

    exporter = EXPORTERS.get("panguml2")
    result = exporter(conn, traj.content_hash)

    assert result is not None
    assert result["meta_info"]["export_mode"] == "converted"
    assert len(result["messages"]) >= 3  # at least user + assistant + tool


def test_items_to_messages():
    """Test items → messages reconstruction preserves structure."""
    from trajlens.export.panguml2 import items_to_messages

    items = _items([
        ("message", "system"), ("message", "user"),
        ("reasoning",), ("function_call",), ("function_call_output",),
        ("message", "assistant"),
    ])
    msgs = items_to_messages(items)
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    # the reasoning+function_call merged into one assistant message
    assert "reasoning_content" in msgs[2]
    assert "tool_calls" in msgs[2]
