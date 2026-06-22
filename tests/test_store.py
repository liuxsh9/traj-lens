import json

from tests.conftest import FIXTURES
from trajlens.store import db as dbmod
from trajlens.store import repo
from trajlens.adapters import detect_and_parse


def test_migrate_creates_tables_and_sets_version(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    v = dbmod.migrate(conn)
    assert v == 1
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"trajectories", "ingestions", "raw_blobs", "items"} <= names


def test_migrate_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    assert dbmod.migrate(conn) == 1
    assert dbmod.migrate(conn) == 1  # second run is a no-op


def test_wal_enabled(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def _ingest(conn, blob_dir):
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj = detect_and_parse(json.loads(raw_bytes))
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
