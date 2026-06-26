import json
import time

from fastapi.testclient import TestClient

from tests.conftest import FIXTURES
from trajlens.api.app import create_app


def _client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), blob_dir=str(tmp_path / "blobs"))
    return TestClient(app)


def _upload_and_wait(c: TestClient, dataset_id: str, body: str) -> dict:
    r = c.post(f"/api/v1/datasets/{dataset_id}/upload",
               files={"file": ("u.jsonl", body.encode(), "application/x-ndjson")})
    jid = r.json()["job_id"]
    for _ in range(50):
        time.sleep(0.1)
        j = c.get(f"/api/v1/jobs/{jid}").json()
        if j["status"] != "pending":
            return j
    raise AssertionError("upload job never finished")


def test_upload_done_survives_metric_failure(tmp_path, monkeypatch):
    """Regression: a crash in the post-insert metric loop must not un-'done' an
    upload whose rows already landed. Pre-fix, status="done" was set AFTER the
    (minutes-long) compute_metrics loop with no guard, so any metric error
    flipped the job to "error" and the data looked lost until a manual refresh."""
    import trajlens.metrics as metrics

    monkeypatch.setattr(metrics, "compute_metrics",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "up"}).json()
    obj = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    body = json.dumps(obj) + "\n"

    jid = c.post(f"/api/v1/datasets/{ds['id']}/upload",
                 files={"file": ("u.jsonl", body.encode(), "application/x-ndjson")}).json()["job_id"]

    for _ in range(50):
        time.sleep(0.1)
        j = c.get(f"/api/v1/jobs/{jid}").json()
        if j["status"] != "pending":
            break
    else:
        raise AssertionError("upload job never finished")

    assert j["status"] == "done"   # data landed → done, despite the metric crash
    assert j["done"] == 1
    assert c.get(f"/api/v1/datasets/{ds['id']}/trajectories").json()["total"] == 1


def test_export_then_download(tmp_path):
    """POST /exports writes a unique file + records an artifact; GET .../download
    streams it back. Two exports must not clobber each other."""
    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "exp"}).json()
    obj = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    _upload_and_wait(c, ds["id"], json.dumps(obj) + "\n")

    a1 = c.post("/api/v1/exports", json={"dataset_id": ds["id"], "format": "panguml2"}).json()
    a2 = c.post("/api/v1/exports", json={"dataset_id": ds["id"], "format": "panguml2"}).json()
    assert a1["id"] != a2["id"]
    assert a1["output_path"] != a2["output_path"]   # unique → no clobber
    assert a1["traj_count"] == 1

    listed = c.get(f"/api/v1/datasets/{ds['id']}/exports").json()
    assert {a1["id"], a2["id"]} <= {x["id"] for x in listed}

    dl = c.get(f"/api/v1/exports/{a1['id']}/download")
    assert dl.status_code == 200
    lines = [l for l in dl.text.splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["meta_info"]["traj_lens_content_hash"]

    assert c.get("/api/v1/exports/nope/download").status_code == 404


def test_export_respects_filters_and_excludes(tmp_path):
    """Export set = filters-matched minus exclude_hashes — same query path as the
    list view, so what you see is what you export."""
    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "exp2"}).json()
    # two distinct trajectories
    a = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    b = json.loads(json.dumps(a))
    b["messages"][1]["content"] = "totally different first user turn"  # new content_hash
    body = json.dumps(a) + "\n" + json.dumps(b) + "\n"
    _upload_and_wait(c, ds["id"], body)

    all_hashes = [r["content_hash"] for r in
                  c.get(f"/api/v1/datasets/{ds['id']}/trajectories").json()["items"]]
    assert len(all_hashes) == 2

    # exclude one → export only the other
    art = c.post("/api/v1/exports", json={
        "dataset_id": ds["id"], "format": "panguml2",
        "exclude_hashes": [all_hashes[0]],
    }).json()
    assert art["traj_count"] == 1
    dl = c.get(f"/api/v1/exports/{art['id']}/download").text
    got = [json.loads(l)["meta_info"]["traj_lens_content_hash"]
           for l in dl.splitlines() if l.strip()]
    assert got == [all_hashes[1]]

    # history row self-explains: selected/matched exposes the manual de-selection
    listed = c.get(f"/api/v1/datasets/{ds['id']}/exports").json()
    row = next(x for x in listed if x["id"] == art["id"])
    assert row["config"]["matched"] == 2
    assert row["config"]["selected"] == 1

    # delete removes the row + the on-disk file
    import os
    path = art["output_path"]
    assert os.path.exists(path)
    assert c.delete(f"/api/v1/exports/{art['id']}").status_code == 200
    assert not os.path.exists(path)
    remaining = [x["id"] for x in c.get(f"/api/v1/datasets/{ds['id']}/exports").json()]
    assert art["id"] not in remaining
    assert c.delete(f"/api/v1/exports/{art['id']}").status_code == 404


def test_spa_cache_headers(tmp_path):
    """index.html must revalidate (no-cache) so a rebuild never strands the
    browser on a stale bundle; fingerprinted assets cache forever."""
    import re
    from trajlens.api.app import WEB_DIST

    if not (WEB_DIST / "index.html").exists():
        import pytest
        pytest.skip("web/dist not built")

    c = _client(tmp_path)
    r = c.get("/")
    assert r.headers["cache-control"] == "no-cache"

    m = re.search(r'assets/[^"]+\.js', r.text)
    assert m, "index.html should reference a hashed asset"
    a = c.get(f"/{m.group(0)}")
    assert "immutable" in a.headers["cache-control"]


def test_health(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}


def test_update_dataset_display_metadata_preserves_id(tmp_path):
    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "Original", "description": "old"}).json()

    r = c.patch(f"/api/v1/datasets/{ds['id']}",
                json={"name": "Renamed", "description": "new note"})

    assert r.status_code == 200
    updated = r.json()
    assert updated["id"] == ds["id"]
    assert updated["name"] == "Renamed"
    assert updated["description"] == "new note"
    got = c.get(f"/api/v1/datasets/{ds['id']}").json()
    assert got["name"] == "Renamed"
    assert got["description"] == "new note"


def test_update_dataset_rejects_empty_name(tmp_path):
    c = _client(tmp_path)
    ds = c.post("/api/v1/datasets", json={"name": "Original"}).json()

    r = c.patch(f"/api/v1/datasets/{ds['id']}", json={"name": "   "})

    assert r.status_code == 422


def test_update_missing_dataset_404(tmp_path):
    c = _client(tmp_path)

    r = c.patch("/api/v1/datasets/missing", json={"name": "Renamed"})

    assert r.status_code == 404


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
