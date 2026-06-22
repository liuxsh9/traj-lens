import json
import pathlib

from trajlens.adapters import detect_and_parse
from trajlens.adapters.codex import sniff, parse
from trajlens.core import grouping

SAMPLES = pathlib.Path(__file__).parent / "samples" / "codex"


def _load(name):
    return [json.loads(ln) for ln in (SAMPLES / name).read_text().splitlines() if ln.strip()]


def test_sniff():
    assert sniff(_load("codex_small.jsonl"))
    assert not sniff({"messages": []})      # openai format
    assert not sniff([{"type": "assistant"}])  # CC format


def test_parses_items():
    traj = detect_and_parse(_load("codex_small.jsonl"))
    assert len(traj.content_hash) == 64
    types = [it.type for it in traj.items]
    assert "function_call" in types
    assert "function_call_output" in types


def test_reasoning_extracted():
    traj = parse(_load("codex_medium.jsonl"))
    # codex response_item type=reasoning should map to ReasoningItem
    assert any(it.type == "reasoning" for it in traj.items)


def test_grouping_works():
    traj = parse(_load("codex_small.jsonl"))
    grouped = grouping.assign_groups(traj.items)
    run_ids = {it.run_id for it in grouped if it.run_id is not None}
    assert len(run_ids) >= 1


def test_provenance_set():
    traj = parse(_load("codex_small.jsonl"))
    for it in traj.items:
        assert it.provenance is not None
        assert it.provenance.content_hash == traj.content_hash
