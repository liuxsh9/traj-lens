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


@pytest.mark.parametrize("path", SWE_CHAT_SAMPLES, ids=lambda p: p.name)
def test_swe_chat_sample_is_preserved(path):
    # Not ingestible yet (needs the slice-2 swe_chat adapter); just guard the fixtures
    # against rot: valid JSON with session rows.
    obj = json.loads(path.read_text())
    assert obj["rows"], "swe_chat sample has no rows"
    assert obj["session_id"]
