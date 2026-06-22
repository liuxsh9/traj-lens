import json
import pathlib

from trajlens.adapters import detect_and_parse
from trajlens.adapters.claude_code import sniff, parse
from trajlens.core import grouping

SAMPLES = pathlib.Path(__file__).parent / "samples" / "claude_code"


def _load(name):
    return [json.loads(ln) for ln in (SAMPLES / name).read_text().splitlines() if ln.strip()]


def test_sniff():
    assert sniff(_load("cc_small.jsonl"))
    assert not sniff({"messages": []})     # openai format
    assert not sniff([{"type": "session_meta"}])  # codex


def test_parses_items():
    traj = detect_and_parse(_load("cc_small.jsonl"))
    assert len(traj.content_hash) == 64
    types = [it.type for it in traj.items]
    assert "message" in types
    # CC small has tool_use (WebFetch) → should produce function_call + function_call_output
    assert "function_call" in types
    assert "function_call_output" in types


def test_thinking_becomes_reasoning():
    traj = parse(_load("cc_medium.jsonl"))
    assert any(it.type == "reasoning" for it in traj.items)


def test_grouping_works():
    traj = parse(_load("cc_small.jsonl"))
    grouped = grouping.assign_groups(traj.items)
    # should have at least one run with steps
    run_ids = {it.run_id for it in grouped if it.run_id is not None}
    assert len(run_ids) >= 1


def test_provenance_set():
    traj = parse(_load("cc_small.jsonl"))
    for it in traj.items:
        assert it.provenance is not None
        assert it.provenance.content_hash == traj.content_hash
