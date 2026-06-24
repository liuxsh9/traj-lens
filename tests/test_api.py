import json

from fastapi.testclient import TestClient

from tests.conftest import FIXTURES
from trajlens.api.app import create_app


def _client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), blob_dir=str(tmp_path / "blobs"))
    return TestClient(app)


def test_health(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}


def test_ingest_then_get(tmp_path):
    c = _client(tmp_path)
    raw = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    r = c.post("/api/v1/trajectories", json=raw)
    assert r.status_code == 200
    ch = r.json()["content_hash"]
    assert len(ch) == 64

    got = c.get(f"/api/v1/trajectories/{ch}").json()
    assert got["content_hash"] == ch
    assert got["items"][2]["type"] == "reasoning"
    assert got["items"][2]["run_id"] == 0          # grouping present in DTO


def test_ingest_is_idempotent(tmp_path):
    c = _client(tmp_path)
    raw = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    h1 = c.post("/api/v1/trajectories", json=raw).json()["content_hash"]
    h2 = c.post("/api/v1/trajectories", json=raw).json()["content_hash"]
    assert h1 == h2
    assert c.get("/api/v1/trajectories").json()["total"] == 1


def test_get_missing_404(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/v1/trajectories/nope").status_code == 404


def test_job_lifecycle_uses_consistent_job_id_key(tmp_path):
    """POST /jobs and GET /jobs/{id} must both expose 'job_id' — else frontend
    polling reassigns from the GET 'id' field, loses job_id, and hits /jobs/undefined."""
    import time

    c = _client(tmp_path)
    raw = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    c.post("/api/v1/trajectories", json=raw)

    created = c.post("/api/v1/jobs",
                     json={"annotator": "config/annotators/loop_detect.yaml"}).json()
    assert "job_id" in created
    jid = created["job_id"]

    # Poll until done; each GET response must keep the same job_id key (no 'id' surprise)
    for _ in range(40):
        time.sleep(0.1)
        got = c.get(f"/api/v1/jobs/{jid}")
        assert got.status_code == 200
        body = got.json()
        assert body["job_id"] == jid
        assert "id" not in body
        if body["status"] != "pending":
            break
    else:
        raise AssertionError("job never finished")


def test_upload_runs_as_background_job(tmp_path):
    """Upload returns a job_id immediately (never blocks); polling shows the
    streamed JSONL imported line-by-line, with bad lines counted as errors."""
    import time

    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "up"}).json()
    raw = (FIXTURES / "panguml2_weather.json").read_text()
    obj = json.loads(raw)
    # two good lines (same content → deduped to 1 trajectory, 2 ingestions) + one bad
    body = "\n".join([json.dumps(obj), json.dumps(obj), "{not json"]) + "\n"

    r = c.post(f"/api/v1/datasets/{ds['id']}/upload",
               files={"file": ("u.jsonl", body.encode(), "application/x-ndjson")})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "pending" and j["annotator_id"] == "upload"
    jid = j["job_id"]

    for _ in range(50):
        time.sleep(0.1)
        body_j = c.get(f"/api/v1/jobs/{jid}").json()
        if body_j["status"] != "pending":
            break
    else:
        raise AssertionError("upload job never finished")

    assert body_j["status"] == "done"
    assert body_j["done"] == 2                       # two parseable lines
    assert len(json.loads(body_j["errors"])) == 1    # one bad line
    # trajectory is queryable and metrics were computed in the worker
    page = c.get(f"/api/v1/datasets/{ds['id']}/trajectories").json()
    assert page["total"] == 1                        # deduped by content_hash
    assert page["items"][0]["metrics"]["turn_count"] >= 0
