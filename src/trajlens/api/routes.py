import asyncio
import json
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile

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
    result["metrics"] = repo.get_metrics_for_trajectory(conn, content_hash)
    # read-time projection of file edits/creates + shell runs (slice-5)
    from trajlens.core.code_changes import changes_as_dicts
    result["code_changes"] = changes_as_dicts(traj.items)
    # persisted semgrep findings (if scanned before) — shown without re-scanning
    result["security_findings"] = repo.get_security_findings(conn, content_hash)
    result["security_scan"] = repo.get_security_scan(conn, content_hash)
    return result


@router.post("/api/v1/trajectories/{content_hash}/semgrep")
def scan_semgrep(content_hash: str, force: bool = False,
                 conn: sqlite3.Connection = Depends(_conn)):
    """Semgrep scan of code extracted from this trajectory's tool calls.
    Cache-aware: returns persisted findings when the stored scan's ruleset_version
    matches the installed semgrep (pass force=true to re-scan). Persists results so
    the count surfaces in the list/filter. available=False if semgrep isn't installed."""
    traj = repo.get_trajectory(conn, content_hash)
    if traj is None:
        raise HTTPException(status_code=404, detail="not found")
    from trajlens.core.semgrep_scan import scan_changes, semgrep_available, ruleset_version
    if not semgrep_available():
        return {"available": False, "scanned": 0, "findings": [], "cached": False}

    cur = ruleset_version()
    scan = repo.get_security_scan(conn, content_hash)
    if scan and scan["ruleset_version"] == cur and not force:
        return {"available": True, "scanned": scan["scanned"], "cached": True,
                "findings": repo.get_security_findings(conn, content_hash)}

    res = scan_changes(traj.items)
    if res.get("available") and "error" not in res:
        repo.put_security_scan(conn, content_hash=content_hash, findings=res["findings"],
                               scanned=res["scanned"], ruleset_version=res.get("ruleset_version", cur))
    res["cached"] = False
    return res


@router.post("/api/v1/datasets/{dataset_id}/semgrep")
def scan_dataset(dataset_id: str, request: Request,
                 conn: sqlite3.Connection = Depends(_conn)):
    """Background batch Semgrep scan of every trajectory in a dataset. semgrep is
    slow (network rule fetch), so this runs as a job the UI polls — like the
    annotator runner. Cache-aware: trajectories whose stored scan matches the
    current ruleset version are skipped, so re-runs are near-instant."""
    from trajlens.core.semgrep_scan import semgrep_available, ruleset_version, scan_changes
    if not semgrep_available():
        raise HTTPException(status_code=400, detail="semgrep not installed")

    job_id = uuid.uuid4().hex[:12]
    repo.create_job(conn, job_id=job_id, annotator_id="semgrep")
    hashes = [t["content_hash"] for t in repo.list_trajectories(conn, dataset_id=dataset_id)]
    repo.update_job(conn, job_id, total=len(hashes))
    db_path = request.app.state.db_path

    # semgrep shells out (subprocess releases the GIL), so a thread pool saturates
    # cores. Parallelize read+scan; keep DB writes serial on `bg` — SQLite WAL is
    # multi-reader / single-writer. ponytail: cpu_count, SEMGREP_CONCURRENCY overrides.
    workers = int(os.environ.get("SEMGREP_CONCURRENCY") or (os.cpu_count() or 4))

    def _scan_one(ch: str, cur: str):
        """Worker: own connection (conn isn't thread-safe), read + scan, no writes.
        Returns (ch, res); res is None when the cached scan is still fresh."""
        w = dbmod.connect(db_path)
        try:
            prev = repo.get_security_scan(w, ch)
            if prev and prev["ruleset_version"] == cur:
                return ch, None
            return ch, scan_changes(repo.get_trajectory(w, ch).items)
        finally:
            w.close()

    def _run():
        bg = dbmod.connect(db_path)
        cur = ruleset_version()
        done = skipped = 0
        errors: list[dict] = []
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_scan_one, ch, cur) for ch in hashes]
                for fut in as_completed(futures):
                    ch, res = fut.result()
                    if res is None:
                        skipped += 1
                    elif res.get("available") and "error" not in res:
                        repo.put_security_scan(bg, content_hash=ch, findings=res["findings"],
                                               scanned=res["scanned"],
                                               ruleset_version=res.get("ruleset_version", cur))
                    else:
                        errors.append({"content_hash": ch, "error": res.get("error", "scan failed")})
                    done += 1
                    repo.update_job(bg, job_id, done=done, skipped=skipped)
            repo.update_job(bg, job_id, status="done", done=done, skipped=skipped,
                            errors=json.dumps(errors, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            repo.update_job(bg, job_id, status="error", errors=json.dumps([{"error": str(exc)}]))
        finally:
            bg.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "annotator_id": "semgrep", "status": "pending"}


@router.post("/api/v1/jobs")
def create_job(request: Request, body: dict = Body(...),
               conn: sqlite3.Connection = Depends(_conn)):
    config_path = body.get("annotator")
    if not config_path:
        raise HTTPException(status_code=422, detail="'annotator' config path required")
    dataset_id = body.get("dataset_id")

    from trajlens.annotate.runner import load_annotator_config, load_annotator_module, run_annotator

    spec = load_annotator_config(config_path)
    mod = load_annotator_module(spec)
    job_id = uuid.uuid4().hex[:12]

    profiles = None
    if spec.type == "llm":
        from trajlens.annotate.llm_client import load_profiles
        profiles = load_profiles()

    content_hashes = None
    if dataset_id:
        content_hashes = [t["content_hash"] for t in
                          repo.list_trajectories(conn, dataset_id=dataset_id)]

    db_path = request.app.state.db_path

    def _run():
        bg_conn = dbmod.connect(db_path)
        try:
            asyncio.run(run_annotator(bg_conn, spec, mod, llm_profiles=profiles,
                                      content_hashes=content_hashes, job_id=job_id))
        except Exception as exc:  # noqa: BLE001
            # otherwise the job row stays 'pending' forever and the UI polls
            # it indefinitely (e.g. missing LLM profile raises mid-run).
            repo.update_job(bg_conn, job_id, status="error",
                            errors=json.dumps([{"error": str(exc)}]))
        finally:
            bg_conn.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "annotator_id": spec.id, "status": "pending"}


@router.post("/api/v1/metrics/compute")
def compute_metrics_endpoint(body: dict = Body(default={}),
                             conn: sqlite3.Connection = Depends(_conn)):
    """(Re)compute metrics for a dataset (or all). Staleness-aware: fills
    missing, refreshes stale, skips up-to-date. Cheap & synchronous —
    metrics are pure functions of stored trajectory + annotations."""
    from trajlens.metrics import compute_metrics
    import trajlens.metrics.builtins  # noqa: F401 — registers metrics

    dataset_id = body.get("dataset_id")
    hashes = [t["content_hash"] for t in
              repo.list_trajectories(conn, dataset_id=dataset_id)]
    for ch in hashes:
        compute_metrics(conn, ch)
    return {"computed": len(hashes)}


@router.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(_conn)):
    job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    d = dict(job)
    d["job_id"] = d.pop("id")  # align with POST /jobs response key
    return d


# ── Annotator discovery ──────────────────────────────────────────────

@router.get("/api/v1/annotators")
def list_annotators(conn: sqlite3.Connection = Depends(_conn)):
    """List available annotator configs from config/annotators/, each annotated
    with the currently-active registered version (if any) so the UI can flag
    stale annotations (run by an older version)."""
    import pathlib, yaml  # noqa: E401
    configs_dir = pathlib.Path("config/annotators")
    if not configs_dir.is_dir():
        return []
    active = {r["id"]: r["version"] for r in conn.execute(
        "SELECT id, version FROM annotators WHERE active=1").fetchall()}
    result = []
    for p in sorted(configs_dir.glob("*.yaml")):
        with open(p) as f:
            cfg = yaml.safe_load(f)
        aid = cfg.get("id", p.stem)
        result.append({
            "id": aid,
            "type": cfg.get("type", "unknown"),
            "target": cfg.get("target", "unknown"),
            "path": str(p),
            "active_version": active.get(aid),
        })
    return result


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


@router.post("/api/v1/datasets/{dataset_id}/upload")
async def upload_to_dataset(
    dataset_id: str,
    request: Request,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(_conn),
):
    """Upload a JSONL file into a dataset. Each line = one trajectory."""
    ds = repo.get_dataset(conn, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")

    blob_dir = request.app.state.blob_dir
    content = (await file.read()).decode("utf-8")
    fname = file.filename or "upload.jsonl"

    batch = None
    count = 0
    errors: list[str] = []
    hashes: list[str] = []

    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            traj, fmt = detect_and_parse(obj)
            if batch is None:
                batch = repo.create_batch(conn, dataset_id=dataset_id, format=fmt,
                                          name=fname, source_info={"filename": fname, "source": "upload"})
            ch = repo.put_trajectory(conn, traj, source_path=fname,
                                     raw_bytes=line.encode("utf-8"),
                                     blob_dir=blob_dir, batch_id=batch["id"])
            hashes.append(ch)
            count += 1
        except Exception as e:
            errors.append(f"line {i+1}: {e}")

    if batch:
        repo.update_batch_count(conn, batch["id"], count)

    # compute structural metrics (turns/steps/tools) now so list columns aren't
    # 0; annotation-dependent metrics stay None until annotators run, then
    # self-refresh via the effective-version staleness check.
    if hashes:
        from trajlens.metrics import compute_metrics
        import trajlens.metrics.builtins  # noqa: F401 — ensure registered
        for ch in hashes:
            compute_metrics(conn, ch)

    return {"count": count, "errors_count": len(errors),
            "errors": errors[:20], "batch_id": batch["id"] if batch else None}


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
