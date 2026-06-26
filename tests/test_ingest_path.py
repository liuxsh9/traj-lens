"""Server-side path ingest: the integration seam for same-host systems
(e.g. Dataviewer) that share the data disk — ingest by absolute path, no upload.
Covers the happy path, traversal defense, Bearer auth, and idempotency."""
import json
import time

from fastapi.testclient import TestClient

from tests.conftest import FIXTURES
from trajlens.api.app import create_app

SAMPLES = FIXTURES.parent / "samples"


def _client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), blob_dir=str(tmp_path / "blobs"))
    return TestClient(app)


def _wait(c: TestClient, jid: str) -> dict:
    for _ in range(50):
        time.sleep(0.1)
        j = c.get(f"/api/v1/jobs/{jid}").json()
        if j["status"] != "pending":
            return j
    raise AssertionError("ingest job never finished")


def _make_jsonl(tmp_path) -> str:
    """One panguml2 trajectory per line — exercises the per-line shape."""
    obj = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    p = tmp_path / "src" / "foo.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(obj) + "\n")
    return str(p)


def test_path_ingest_happy(tmp_path, monkeypatch):
    """Roots configured → ingest by path, dataset auto-named from file stem,
    returns dataset_id so the caller can deep-link straight to it."""
    src = _make_jsonl(tmp_path)
    monkeypatch.setenv("TRAJLENS_INGEST_ROOTS", str(tmp_path / "src"))
    c = _client(tmp_path)

    r = c.post("/api/v1/ingest/path", json={"path": src})
    assert r.status_code == 200
    body = r.json()
    assert body["dataset_name"] == "foo"   # from foo.jsonl stem
    assert body["dataset_id"]

    j = _wait(c, body["job_id"])
    assert j["status"] == "done"
    assert j["done"] == 1
    assert c.get(f"/api/v1/datasets/{body['dataset_id']}/trajectories").json()["total"] == 1


def test_path_ingest_disabled_without_roots(tmp_path, monkeypatch):
    """No roots set → endpoint refuses (safe default: opt-in only)."""
    monkeypatch.delenv("TRAJLENS_INGEST_ROOTS", raising=False)
    c = _client(tmp_path)
    r = c.post("/api/v1/ingest/path", json={"path": str(tmp_path / "x.jsonl")})
    assert r.status_code == 403


def test_path_ingest_traversal_blocked(tmp_path, monkeypatch):
    """`..` escaping the root is resolved THEN rejected — not a string-prefix
    check that `../` could fool."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    monkeypatch.setenv("TRAJLENS_INGEST_ROOTS", str(src_dir))
    c = _client(tmp_path)
    # FIXTURES/panguml2_weather.json exists but lives OUTSIDE src/.
    escape = str(src_dir / ".." / "fixtures" / "panguml2_weather.json")
    r = c.post("/api/v1/ingest/path", json={"path": escape})
    assert r.status_code == 403


def test_path_ingest_auth(tmp_path, monkeypatch):
    """Token configured → Authorization: Bearer required."""
    src = _make_jsonl(tmp_path)
    monkeypatch.setenv("TRAJLENS_INGEST_ROOTS", str(tmp_path / "src"))
    monkeypatch.setenv("TRAJLENS_INGEST_TOKEN", "s3cret")
    c = _client(tmp_path)

    assert c.post("/api/v1/ingest/path", json={"path": src}).status_code == 401
    assert c.post("/api/v1/ingest/path", json={"path": src},
                  headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.post("/api/v1/ingest/path", json={"path": src},
                headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_path_ingest_idempotent(tmp_path, monkeypatch):
    """Re-ingesting the same file is safe — content_hash dedup means trajectory
    count does not double, so callers can retry freely."""
    src = _make_jsonl(tmp_path)
    monkeypatch.setenv("TRAJLENS_INGEST_ROOTS", str(tmp_path / "src"))
    c = _client(tmp_path)

    b1 = c.post("/api/v1/ingest/path", json={"path": src}).json()
    _wait(c, b1["job_id"])
    b2 = c.post("/api/v1/ingest/path", json={"path": src}).json()
    _wait(c, b2["job_id"])
    assert b1["dataset_id"] == b2["dataset_id"]  # same stem → same dataset
    total = c.get(f"/api/v1/datasets/{b1['dataset_id']}/trajectories").json()["total"]
    assert total == 1  # not 2


def test_integration_manifest(tmp_path, monkeypatch):
    """Self-describing endpoint reports auth + roots + formats in one call."""
    monkeypatch.setenv("TRAJLENS_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("TRAJLENS_INGEST_TOKEN", "x")
    c = _client(tmp_path)
    m = c.get("/api/v1/integration").json()
    assert m["auth_required"] is True
    assert str(tmp_path.resolve()) in m["ingest_roots"]
    assert "openai_messages" in m["formats"]
    # OpenAPI must not be swallowed by the SPA fallback
    assert c.get("/openapi.json").status_code == 200
