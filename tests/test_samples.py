"""Compatibility regression: every curated real-world sample must ingest cleanly.

These samples are curated from real datasets (see tests/samples/README.md) to
exercise the system's tolerance for diverse trajectory shapes. If a future change
breaks one, that's a real compatibility regression.
"""
import json
import pathlib

import pytest

from trajlens.adapters import detect_and_parse
from trajlens.core import grouping
from trajlens.store import db as dbmod, repo

SAMPLES = pathlib.Path(__file__).parent / "samples"
OPENAI_SAMPLES = sorted((SAMPLES / "openai_messages").glob("*.json"))
SWE_CHAT_SAMPLES = sorted((SAMPLES / "swe_chat").glob("*.json"))
CC_SAMPLES = sorted((SAMPLES / "claude_code").glob("*.jsonl"))
CODEX_SAMPLES = sorted((SAMPLES / "codex").glob("*.jsonl"))

assert OPENAI_SAMPLES, "no openai_messages samples found"


@pytest.mark.parametrize("path", OPENAI_SAMPLES, ids=lambda p: p.name)
def test_openai_sample_ingests_and_groups(path, tmp_path):
    raw = json.loads(path.read_text())
    traj = detect_and_parse(raw)

    assert len(traj.content_hash) == 64
    assert traj.items, "no items parsed"

    grouped = grouping.assign_groups(traj.items)
    for it in grouped:
        if it.type == "message" and it.role in ("user", "system", "developer"):
            assert it.run_id is None          # user-side turns are not in a run
        else:
            assert it.run_id is not None      # assistant-side items belong to a run
            assert it.step_id is not None

    # store round-trip preserves identity + item count
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = repo.put_trajectory(conn, traj, source_path=str(path),
                             raw_bytes=path.read_bytes(), blob_dir=str(tmp_path / "blobs"))
    got = repo.get_trajectory(conn, ch)
    assert got is not None
    assert ch == traj.content_hash
    assert len(got.items) == len(traj.items)


def _load_jsonl(path):
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


@pytest.mark.parametrize("path", CC_SAMPLES, ids=lambda p: p.name)
def test_cc_sample_ingests_and_groups(path, tmp_path):
    raw = _load_jsonl(path)
    traj = detect_and_parse(raw)
    assert len(traj.content_hash) == 64
    assert traj.items, "no items parsed"
    grouped = grouping.assign_groups(traj.items)
    assert any(it.run_id is not None for it in grouped)
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = repo.put_trajectory(conn, traj, source_path=str(path),
                             raw_bytes=path.read_bytes(), blob_dir=str(tmp_path / "blobs"))
    assert repo.get_trajectory(conn, ch) is not None


@pytest.mark.parametrize("path", CODEX_SAMPLES, ids=lambda p: p.name)
def test_codex_sample_ingests_and_groups(path, tmp_path):
    raw = _load_jsonl(path)
    traj = detect_and_parse(raw)
    assert len(traj.content_hash) == 64
    assert traj.items, "no items parsed"
    grouped = grouping.assign_groups(traj.items)
    assert any(it.run_id is not None for it in grouped)
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = repo.put_trajectory(conn, traj, source_path=str(path),
                             raw_bytes=path.read_bytes(), blob_dir=str(tmp_path / "blobs"))
    assert repo.get_trajectory(conn, ch) is not None


@pytest.mark.parametrize("path", SWE_CHAT_SAMPLES, ids=lambda p: p.name)
def test_swe_chat_sample_is_preserved(path):
    obj = json.loads(path.read_text())
    assert obj["rows"], "swe_chat sample has no rows"
    assert obj["session_id"]
