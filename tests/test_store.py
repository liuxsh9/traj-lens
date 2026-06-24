import json

from tests.conftest import FIXTURES
from trajlens.store import db as dbmod
from trajlens.store import repo
from trajlens.adapters import detect_and_parse


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
