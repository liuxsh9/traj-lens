import asyncio
import json
import sqlite3
import threading
import uuid
from typing import Generator

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from trajlens.adapters import detect_and_parse
from trajlens.store import db as dbmod, repo

router = APIRouter()


def _conn(request: Request) -> Generator[sqlite3.Connection, None, None]:
    """Per-request SQLite connection — avoids thread-safety issues with shared conn."""
    conn = dbmod.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/api/v1/trajectories")
def ingest(request: Request, raw: dict = Body(...),
           dataset: str = "_default",
           conn: sqlite3.Connection = Depends(_conn)):
    blob_dir = request.app.state.blob_dir
    try:
        traj, fmt = detect_and_parse(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    ds = repo.get_or_create_dataset(conn, name=dataset)
    batch = repo.create_batch(conn, dataset_id=ds["id"], format=fmt,
                              name="inline", source_info={"source": "api"})
    ch = repo.put_trajectory(conn, traj, source_path="inline",
                             raw_bytes=None, blob_dir=blob_dir,
                             batch_id=batch["id"])
    repo.update_batch_count(conn, batch["id"], 1)
    return {"content_hash": ch, "items_count": len(traj.items)}


@router.get("/api/v1/trajectories")
def list_all(
    request: Request,
    conn: sqlite3.Connection = Depends(_conn),
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    filters: str | None = None,
):
    parsed_filters = json.loads(filters) if filters else None
    return repo.query_trajectories(
        conn, limit=limit, offset=offset,
        sort_by=sort_by, sort_dir=sort_dir, filters=parsed_filters,
    )


@router.get("/api/v1/trajectories/{content_hash}")
def get_one(content_hash: str, conn: sqlite3.Connection = Depends(_conn)):
    traj = repo.get_trajectory(conn, content_hash)
    if traj is None:
        raise HTTPException(status_code=404, detail="not found")
    result = traj.model_dump()
    result["annotations"] = repo.get_annotations_for_trajectory(conn, content_hash)
    return result


@router.post("/api/v1/jobs")
def create_job(request: Request, body: dict = Body(...),
               conn: sqlite3.Connection = Depends(_conn)):
    config_path = body.get("annotator")
    if not config_path:
        raise HTTPException(status_code=422, detail="'annotator' config path required")

    from trajlens.annotate.runner import load_annotator_config, load_annotator_module, run_annotator

    spec = load_annotator_config(config_path)
    mod = load_annotator_module(spec)
    job_id = uuid.uuid4().hex[:12]

    profiles = None
    if spec.type == "llm":
        from trajlens.annotate.llm_client import load_profiles
        profiles = load_profiles()

    # Background thread gets its own connection
    db_path = request.app.state.db_path

    def _run():
        bg_conn = dbmod.connect(db_path)
        try:
            asyncio.run(run_annotator(bg_conn, spec, mod, llm_profiles=profiles,
                                      job_id=job_id))
        finally:
            bg_conn.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "annotator_id": spec.id, "status": "pending"}


@router.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(_conn)):
    job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(job)


# ── Dataset / Batch endpoints ─────────────────────────────────────────

@router.post("/api/v1/datasets")
def create_dataset(body: dict = Body(...),
                   conn: sqlite3.Connection = Depends(_conn)):
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="'name' required")
    ds = repo.create_dataset(conn, name=name, description=body.get("description", ""))
    return ds


@router.get("/api/v1/datasets")
def list_datasets(conn: sqlite3.Connection = Depends(_conn)):
    return repo.list_datasets(conn)


@router.get("/api/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str, conn: sqlite3.Connection = Depends(_conn)):
    ds = repo.get_dataset(conn, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return ds


@router.delete("/api/v1/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, conn: sqlite3.Connection = Depends(_conn)):
    if not repo.delete_dataset(conn, dataset_id):
        raise HTTPException(status_code=400, detail="cannot delete _default dataset")
    return {"ok": True}


@router.get("/api/v1/datasets/{dataset_id}/batches")
def list_batches(dataset_id: str, conn: sqlite3.Connection = Depends(_conn)):
    return repo.list_batches(conn, dataset_id)


@router.get("/api/v1/datasets/{dataset_id}/stats")
def dataset_stats(dataset_id: str, conn: sqlite3.Connection = Depends(_conn)):
    ds = repo.get_dataset(conn, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return repo.get_dataset_stats(conn, dataset_id)


@router.post("/api/v1/exports")
def create_export(request: Request, body: dict = Body(...),
                  conn: sqlite3.Connection = Depends(_conn)):
    dataset_id = body.get("dataset_id", "")
    fmt = body.get("format", "panguml2")
    output = body.get("output", "export.jsonl")

    if not dataset_id:
        raise HTTPException(status_code=422, detail="'dataset_id' required")
    ds = repo.get_dataset(conn, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")

    import trajlens.export.panguml2  # noqa: F401
    from trajlens.export import EXPORTERS

    exporter_fn = EXPORTERS.get(fmt)
    if exporter_fn is None:
        raise HTTPException(status_code=422, detail=f"unknown format '{fmt}'")

    blob_dir = request.app.state.blob_dir
    hashes = [r["content_hash"] for r in conn.execute("""
        SELECT DISTINCT i.content_hash FROM ingestions i
        JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
    """, (dataset_id,)).fetchall()]

    count = 0
    with open(output, "w") as f:
        for ch in hashes:
            record = exporter_fn(conn, ch, blob_dir=blob_dir)
            if record:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

    artifact = repo.create_export_artifact(
        conn, dataset_id=dataset_id, exporter=fmt,
        traj_count=count, output_path=output)
    return artifact


@router.get("/api/v1/datasets/{dataset_id}/trajectories")
def list_dataset_trajectories(
    dataset_id: str,
    conn: sqlite3.Connection = Depends(_conn),
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    filters: str | None = None,
):
    parsed_filters = json.loads(filters) if filters else None
    return repo.query_trajectories(
        conn, limit=limit, offset=offset,
        sort_by=sort_by, sort_dir=sort_dir, filters=parsed_filters,
        dataset_id=dataset_id,
    )
