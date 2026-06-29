"""Tests for the loop_detect rule annotator and the annotation runner end-to-end."""
import json
import pathlib

from trajlens.adapters import detect_and_parse
from trajlens.annotate import Target, enumerate_targets
from trajlens.annotate.rules import loop_detect
from trajlens.annotate import runner
from trajlens.core.model import FunctionCallItem, MessageItem
from trajlens.store import db as dbmod, repo

SAMPLES = pathlib.Path(__file__).parent / "samples"
LONG_RUN = SAMPLES / "openai_messages" / "agentic_long_run.json"


def _call(name, args, call_id="c"):
    return FunctionCallItem(name=name, arguments=json.dumps(args), call_id=call_id)


# ── annotate() unit tests ──────────────────────────────────────────────

def test_annotate_flags_repeated_edits():
    ctx = [_call("edit", {"file_path": "a.py", "new_string": f"x{i}"}) for i in range(3)]
    out = loop_detect.annotate(unit=ctx[-1:], ctx=ctx)
    assert out["detected"] is True
    assert out["files"] == {"a.py": 3}


def test_annotate_below_threshold_not_flagged():
    ctx = [_call("Write", {"path": "a.py"}), _call("Write", {"path": "a.py"})]
    out = loop_detect.annotate(unit=ctx[-1:], ctx=ctx)
    assert out["detected"] is False
    assert out["files"] == {}


def test_annotate_ignores_editor_view_calls():
    ctx = [
        _call("str_replace_editor", {"command": "view", "path": "a.py"}, call_id=f"v{i}")
        for i in range(3)
    ]
    out = loop_detect.annotate(unit=ctx[-1:], ctx=ctx)
    assert out == {"detected": False, "files": {}}


def test_annotate_no_edits():
    ctx = [MessageItem(role="user", content="hi"),
           _call("read_file", {"path": "a.py"})]
    out = loop_detect.annotate(unit=[], ctx=ctx)
    assert out == {"detected": False, "files": {}}


def test_annotate_distinct_files_counted_separately():
    ctx = ([_call("edit", {"file_path": "a.py", "new_string": f"a{i}"}) for i in range(3)]
           + [_call("edit", {"file_path": "b.py", "new_string": f"b{i}"}) for i in range(2)])
    out = loop_detect.annotate(unit=[], ctx=ctx)
    assert out["detected"] is True
    assert out["files"] == {"a.py": 3}  # b.py only edited twice


def test_annotate_ignores_malformed_arguments():
    bad = FunctionCallItem(name="edit", arguments="{not json", call_id="c")
    out = loop_detect.annotate(unit=[], ctx=[bad])
    assert out == {"detected": False, "files": {}}


# ── runner end-to-end ──────────────────────────────────────────────────

async def test_runner_e2e_on_sample(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)

    raw = json.loads(LONG_RUN.read_text())
    traj, _ = detect_and_parse(raw)
    ch = repo.put_trajectory(conn, traj, source_path=str(LONG_RUN),
                             raw_bytes=LONG_RUN.read_bytes(), blob_dir=str(tmp_path / "blobs"))

    spec = runner.load_annotator_config("config/annotators/loop_detect.yaml")
    mod = runner.load_annotator_module(spec)
    result = await runner.run_annotator(conn, spec, mod, content_hashes=[ch],
                                        job_id="job-1")

    # every STEP target got annotated, nothing skipped on a fresh DB
    # (step_id is assigned at read time, so count from the stored/grouped trajectory)
    n_steps = len(enumerate_targets(repo.get_trajectory(conn, ch), Target.STEP))
    assert result["total"] == n_steps
    assert result["done"] == n_steps
    assert result["skipped"] == 0
    assert result["errors"] == []

    rows = repo.get_annotations_for_trajectory(conn, ch)
    assert len(rows) == n_steps
    for r in rows:
        val = json.loads(r["value"])
        assert set(val) == {"detected", "files"}

    job = repo.get_job(conn, "job-1")
    assert job["status"] == "done"
    assert job["done"] == n_steps


async def test_rule_runner_publishes_progress_before_done(tmp_path, monkeypatch):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)

    raw = json.loads(LONG_RUN.read_text())
    traj, _ = detect_and_parse(raw)
    ch = repo.put_trajectory(conn, traj, blob_dir=str(tmp_path / "blobs"))

    seen: list[dict] = []
    real_update = repo.update_job

    def spy_update_job(conn_arg, job_id, **kwargs):
        seen.append(kwargs)
        return real_update(conn_arg, job_id, **kwargs)

    monkeypatch.setattr(repo, "update_job", spy_update_job)

    spec = runner.load_annotator_config("config/annotators/loop_detect.yaml")
    mod = runner.load_annotator_module(spec)
    await runner.run_annotator(conn, spec, mod, content_hashes=[ch], job_id="job-progress")

    final = next(kwargs for kwargs in reversed(seen) if kwargs.get("status") == "done")
    progress = [
        kwargs for kwargs in seen
        if kwargs.get("done", 0) > 0 and kwargs.get("status") != "done"
    ]
    assert progress, "rule jobs should publish progress before the final done update"
    assert all(kwargs["total"] == final["total"] for kwargs in progress)


async def test_runner_is_cache_aware(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    raw = json.loads(LONG_RUN.read_text())
    traj, _ = detect_and_parse(raw)
    ch = repo.put_trajectory(conn, traj, blob_dir=str(tmp_path / "blobs"))

    spec = runner.load_annotator_config("config/annotators/loop_detect.yaml")
    mod = runner.load_annotator_module(spec)

    first = await runner.run_annotator(conn, spec, mod, content_hashes=[ch])
    second = await runner.run_annotator(conn, spec, mod, content_hashes=[ch])

    assert first["done"] > 0
    assert second["done"] == 0           # all cached on the second pass
    assert second["skipped"] == first["total"]


async def test_runner_force_refresh_ignores_cache(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    raw = json.loads(LONG_RUN.read_text())
    traj, _ = detect_and_parse(raw)
    ch = repo.put_trajectory(conn, traj, blob_dir=str(tmp_path / "blobs"))

    spec = runner.load_annotator_config("config/annotators/loop_detect.yaml")
    mod = runner.load_annotator_module(spec)

    first = await runner.run_annotator(conn, spec, mod, content_hashes=[ch])
    forced = await runner.run_annotator(conn, spec, mod, content_hashes=[ch], force=True)

    assert first["done"] > 0
    assert forced["total"] == first["total"]
    assert forced["done"] == first["done"]
    assert forced["skipped"] == 0
