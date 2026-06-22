import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, Body, HTTPException, Request

from trajlens.adapters import detect_and_parse
from trajlens.store import repo

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/api/v1/trajectories")
def ingest(request: Request, raw: dict = Body(...)):
    conn = request.app.state.conn
    blob_dir = request.app.state.blob_dir
    try:
        traj = detect_and_parse(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    ch = repo.put_trajectory(conn, traj, source_path="inline",
                             raw_bytes=None, blob_dir=blob_dir)
    return {"content_hash": ch, "items_count": len(traj.items)}


@router.get("/api/v1/trajectories")
def list_all(request: Request):
    return repo.list_trajectories(request.app.state.conn)


@router.get("/api/v1/trajectories/{content_hash}")
def get_one(request: Request, content_hash: str):
    conn = request.app.state.conn
    traj = repo.get_trajectory(conn, content_hash)
    if traj is None:
        raise HTTPException(status_code=404, detail="not found")
    result = traj.model_dump()
    result["annotations"] = repo.get_annotations_for_trajectory(conn, content_hash)
    return result


@router.post("/api/v1/jobs")
def create_job(request: Request, body: dict = Body(...)):
    conn = request.app.state.conn
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

    def _run():
        asyncio.run(run_annotator(conn, spec, mod, llm_profiles=profiles,
                                  semaphore=asyncio.Semaphore(5), job_id=job_id))

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "annotator_id": spec.id, "status": "pending"}


@router.get("/api/v1/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    job = repo.get_job(request.app.state.conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(job)
