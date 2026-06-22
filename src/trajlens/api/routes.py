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
    traj = repo.get_trajectory(request.app.state.conn, content_hash)
    if traj is None:
        raise HTTPException(status_code=404, detail="not found")
    return traj.model_dump()
