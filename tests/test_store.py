import json

from tests.conftest import FIXTURES
from trajlens.store import db as dbmod
from trajlens.store import repo
from trajlens.adapters import detect_and_parse
from trajlens.core.identity import content_hash


def test_migrate_creates_tables_and_sets_version(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    v = dbmod.migrate(conn)
    assert v == 11
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"trajectories", "ingestions", "raw_blobs", "items",
            "annotators", "annotations", "annotation_targets", "jobs",
            "datasets", "batches", "security_findings", "security_scans"} <= names


def test_migrate_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    assert dbmod.migrate(conn) == 11
    assert dbmod.migrate(conn) == 11  # second run is a no-op


def test_jobs_scoped_to_dataset(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.create_job(conn, job_id="j1", annotator_id="a", dataset_id="ds1")
    repo.create_job(conn, job_id="j2", annotator_id="b", dataset_id="ds2")
    # idempotent re-create (route pre-creates, runner re-calls) must not clobber
    repo.update_job(conn, "j1", status="done", done=5)
    repo.create_job(conn, job_id="j1", annotator_id="a", dataset_id="ds1")
    assert repo.get_job(conn, "j1")["status"] == "done"

    ds1 = repo.list_jobs(conn, dataset_id="ds1")
    assert [j["id"] for j in ds1] == ["j1"]
    assert repo.list_jobs(conn, dataset_id="ds2")[0]["id"] == "j2"
    assert repo.list_jobs(conn, dataset_id="nope") == []


def test_interrupt_stale_jobs(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.create_job(conn, job_id="p", annotator_id="a", dataset_id="ds")
    repo.create_job(conn, job_id="d", annotator_id="a", dataset_id="ds")
    repo.update_job(conn, "d", status="done")
    assert repo.interrupt_stale_jobs(conn) == 1  # only the pending one
    assert repo.get_job(conn, "p")["status"] == "interrupted"
    assert repo.get_job(conn, "d")["status"] == "done"  # finished job untouched
    assert repo.interrupt_stale_jobs(conn) == 0  # idempotent: nothing left pending


def test_wal_enabled(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def _ingest(conn, blob_dir):
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))
    return repo.put_trajectory(conn, traj, source_path="x.json",
                               raw_bytes=raw_bytes, blob_dir=str(blob_dir))


def test_put_is_idempotent_by_content_hash(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    h1 = _ingest(conn, tmp_path / "blobs")
    h2 = _ingest(conn, tmp_path / "blobs")
    assert h1 == h2
    n_traj = conn.execute("SELECT COUNT(*) FROM trajectories").fetchone()[0]
    n_ing = conn.execute("SELECT COUNT(*) FROM ingestions").fetchone()[0]
    assert n_traj == 1   # deduped
    assert n_ing == 2    # both ingestions recorded


def test_get_returns_items_with_grouping(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    h = _ingest(conn, tmp_path / "blobs")
    t = repo.get_trajectory(conn, h)
    assert t is not None
    assert [it.type for it in t.items][0] == "message"
    assert t.items[1].run_id is None          # user
    assert t.items[2].run_id == 0             # reasoning (assistant run)


def test_get_missing_returns_none(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    assert repo.get_trajectory(conn, "nope") is None


# ── Dataset / Batch tests ─────────────────────────────────────────────

def test_default_dataset_seeded(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds = repo.get_dataset(conn, "_default")
    assert ds is not None
    assert ds["name"] == "_default"


def test_create_dataset_and_list(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds = repo.create_dataset(conn, name="My Dataset", description="test")
    assert ds["name"] == "My Dataset"
    assert ds["id"] == "my-dataset"

    all_ds = repo.list_datasets(conn)
    names = {d["name"] for d in all_ds}
    assert "My Dataset" in names
    assert "_default" in names


def test_get_or_create_dataset_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    d1 = repo.get_or_create_dataset(conn, name="test-ds")
    d2 = repo.get_or_create_dataset(conn, name="test-ds")
    assert d1["id"] == d2["id"]


def test_update_dataset_metadata_preserves_id(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds = repo.create_dataset(conn, name="Original", description="old")

    updated = repo.update_dataset(conn, ds["id"], name="Renamed", description="new note")

    assert updated["id"] == ds["id"]
    assert updated["name"] == "Renamed"
    assert updated["description"] == "new note"
    assert repo.get_dataset(conn, ds["id"])["name"] == "Renamed"


def test_get_or_create_default_dataset_uses_stable_id_after_rename(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.update_dataset(conn, "_default", name="Inbox", description="renamed")

    ds = repo.get_or_create_dataset(conn, name="_default")

    assert ds["id"] == "_default"
    assert ds["name"] == "Inbox"


def test_delete_dataset_refuses_default(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    assert repo.delete_dataset(conn, "_default") is False


def test_recreated_dataset_does_not_recycle_id(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    d1 = repo.create_dataset(conn, name="test")
    assert d1["id"] == "test"
    repo.delete_dataset(conn, d1["id"])
    d2 = repo.create_dataset(conn, name="test")
    assert d2["id"] != d1["id"]        # no aliasing of the deleted dataset
    assert d2["id"].startswith("test-")


def test_put_trajectory_with_batch(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds = repo.get_or_create_dataset(conn, name="_default")
    batch = repo.create_batch(conn, dataset_id=ds["id"], format="openai_messages",
                              name="test.json")
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))
    ch = repo.put_trajectory(conn, traj, source_path="x.json",
                             raw_bytes=raw_bytes, blob_dir=str(tmp_path / "blobs"),
                             batch_id=batch["id"])
    repo.update_batch_count(conn, batch["id"], 1)

    row = conn.execute("SELECT batch_id FROM ingestions WHERE content_hash=?", (ch,)).fetchone()
    assert row["batch_id"] == batch["id"]

    batches = repo.list_batches(conn, ds["id"])
    assert batches[0]["traj_count"] == 1


def test_query_trajectories_scoped_by_dataset(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds1 = repo.create_dataset(conn, name="ds-one")
    ds2 = repo.create_dataset(conn, name="ds-two")
    b1 = repo.create_batch(conn, dataset_id=ds1["id"], format="openai_messages")
    b2 = repo.create_batch(conn, dataset_id=ds2["id"], format="openai_messages")

    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))
    repo.put_trajectory(conn, traj, source_path="x.json", batch_id=b1["id"])

    # ds1 should have 1, ds2 should have 0
    r1 = repo.query_trajectories(conn, dataset_id=ds1["id"])
    assert r1["total"] == 1
    r2 = repo.query_trajectories(conn, dataset_id=ds2["id"])
    assert r2["total"] == 0


def test_query_trajectories_tag_filters_can_match_any(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.register_annotator(conn, id="topic", version="v1", config_hash="cfg")
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))

    hashes = []
    for idx, tags in enumerate((["前端"], ["后端"], ["前端", "后端"])):
        t = traj.model_copy(deep=True)
        t.items[1].content = f"distinct user turn {idx}"
        t.content_hash = content_hash(t.items, t.tools)
        h = repo.put_trajectory(conn, t, source_path=f"{idx}.json")
        repo.link_annotation_target(conn, target_hash=h, content_hash=h, target_type="trajectory", target_idx=0)
        conn.commit()
        repo.put_annotation(
            conn,
            target_hash=h,
            annotator_id="topic",
            annotator_version="v1",
            value={"tags": tags},
            inputs_hash="test",
        )
        hashes.append(h)

    all_mode = repo.query_trajectories(conn, filters=[
        {"field": "tags", "op": "∋", "value": "前端", "mode": "all"},
        {"field": "tags", "op": "∋", "value": "后端", "mode": "all"},
    ])
    assert all_mode["total"] == 1
    assert {item["content_hash"] for item in all_mode["items"]} == {hashes[2]}

    any_mode = repo.query_trajectories(conn, filters=[
        {"field": "tags", "op": "∋", "value": "前端", "mode": "any"},
        {"field": "tags", "op": "∋", "value": "后端", "mode": "any"},
    ])
    assert any_mode["total"] == 3


def test_query_trajectories_tag_filters_match_exact_tag_members(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.register_annotator(conn, id="topic", version="v1", config_hash="cfg")
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))

    hashes = []
    for idx, value in enumerate((
        {"title": "exact", "summary": "real tag", "tags": ["C#"]},
        {"title": "mentions C#", "summary": "text only C#", "tags": ["代码审查"]},
    )):
        t = traj.model_copy(deep=True)
        t.items[1].content = f"exact tag user turn {idx}"
        t.content_hash = content_hash(t.items, t.tools)
        h = repo.put_trajectory(conn, t, source_path=f"exact-{idx}.json")
        repo.link_annotation_target(conn, target_hash=h, content_hash=h, target_type="trajectory", target_idx=0)
        conn.commit()
        repo.put_annotation(
            conn,
            target_hash=h,
            annotator_id="topic",
            annotator_version="v1",
            value=value,
            inputs_hash="test",
        )
        hashes.append(h)

    found = repo.query_trajectories(conn, filters=[
        {"field": "tags", "op": "∋", "value": "C#"},
    ])

    assert found["total"] == 1
    assert {item["content_hash"] for item in found["items"]} == {hashes[0]}


def test_query_trajectories_sorts_all_list_columns(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    repo.register_annotator(conn, id="topic", version="v1", config_hash="cfg")
    repo.register_annotator(conn, id="resolution", version="v1", config_hash="cfg")
    repo.register_annotator(conn, id="change_acceptance", version="v1", config_hash="cfg")
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))

    hashes = []
    rows = [
        {
            "title": "Alpha", "resolution": "unresolved", "acceptance": "low",
            "turn_count": 1, "step_count": 2, "tool_count": 3, "pushback_count": 4,
            "error_steps": 5, "loop_count": 6, "recovery_count": 7,
            "introduced_findings_count": 8, "overall_score": 9,
        },
        {
            "title": "Zulu", "resolution": "resolved", "acceptance": "high",
            "turn_count": 9, "step_count": 8, "tool_count": 7, "pushback_count": 6,
            "error_steps": 1, "loop_count": 4, "recovery_count": 3,
            "introduced_findings_count": 2, "overall_score": 1,
        },
    ]
    for idx, row in enumerate(rows):
        t = traj.model_copy(deep=True)
        t.items[1].content = f"sortable row {idx}"
        t.content_hash = content_hash(t.items, t.tools)
        h = repo.put_trajectory(conn, t, source_path=f"sort-{idx}.json")
        repo.link_annotation_target(conn, target_hash=h, content_hash=h, target_type="trajectory", target_idx=0)
        conn.commit()
        repo.put_annotation(conn, target_hash=h, annotator_id="topic", annotator_version="v1",
                            value={"title": row["title"], "summary": "", "tags": []}, inputs_hash="test")
        repo.put_annotation(conn, target_hash=h, annotator_id="resolution", annotator_version="v1",
                            value={"resolution": row["resolution"]}, inputs_hash="test")
        repo.put_annotation(conn, target_hash=h, annotator_id="change_acceptance", annotator_version="v1",
                            value={"likelihood": row["acceptance"], "no_edits": False}, inputs_hash="test")
        repo.put_metric(conn, content_hash=h, metric_id="tool_intensity", value={"error_steps": row["error_steps"], "recovery_rate": None}, version="test")
        for metric in (
            "turn_count", "step_count", "tool_count", "pushback_count", "loop_count",
            "recovery_count", "introduced_findings_count", "overall_score",
        ):
            repo.put_metric(conn, content_hash=h, metric_id=metric, value=row[metric], version="test")
        hashes.append(h)

    expected_desc_first = {
        "title": hashes[1],
        "resolution": hashes[1],
        "acceptance": hashes[1],
        "turns": hashes[1],
        "steps": hashes[1],
        "tools": hashes[1],
        "pushback_count": hashes[1],
        "error_steps": hashes[0],
        "loop_count": hashes[0],
        "recovery_count": hashes[0],
        "security_findings": hashes[0],
        "score": hashes[0],
        "created_at": hashes[1],
    }
    for sort_by, first_hash in expected_desc_first.items():
        got = repo.query_trajectories(conn, sort_by=sort_by, sort_dir="desc")
        assert got["items"][0]["content_hash"] == first_hash, sort_by


def test_dataset_stats_returns_all_tags(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ds = repo.create_dataset(conn, name="many-tags")
    batch = repo.create_batch(conn, dataset_id=ds["id"], format="test")
    repo.register_annotator(conn, id="topic", version="v1", config_hash="cfg")
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj, _ = detect_and_parse(json.loads(raw_bytes))

    for idx in range(25):
        t = traj.model_copy(deep=True)
        t.items[1].content = f"many tags user turn {idx}"
        t.content_hash = content_hash(t.items, t.tools)
        h = repo.put_trajectory(conn, t, source_path=f"{idx}.json", batch_id=batch["id"])
        repo.link_annotation_target(conn, target_hash=h, content_hash=h, target_type="trajectory", target_idx=0)
        conn.commit()
        repo.put_annotation(
            conn,
            target_hash=h,
            annotator_id="topic",
            annotator_version="v1",
            value={"tags": [f"tag-{idx:02d}"]},
            inputs_hash="test",
        )

    stats = repo.get_dataset_stats(conn, ds["id"])

    assert len(stats["top_tags"]) == 25
    assert {t["tag"] for t in stats["top_tags"]} == {f"tag-{idx:02d}" for idx in range(25)}
