"""Shared JSONL → DB import job, used by both /upload (temp file) and
/ingest/path (server-side path). Pure: takes db_path/blob_dir/file path, no
FastAPI objects, so it runs in a background thread and is unit-testable.

Handles three shapes (same three-way sniff as the CLI ingest, cli.py):
  1. whole file is one JSON object   → 1 trajectory
  2. whole file is one session log   → 1 trajectory (CC / Codex: all lines = one session)
  3. each line is its own trajectory → N trajectories
This makes path-ingest and upload robust to CC/Codex session logs, which the
old line-only /upload path silently mishandled.
"""
import json
import os

from trajlens.adapters import detect_and_parse
from trajlens.store import db as dbmod, repo

COMMIT_EVERY = 200  # ponytail: one transaction per N trajectories; tune if I/O-bound


def import_jsonl_job(db_path: str, blob_dir: str, dataset_id: str, src_path: str,
                     fname: str, job_id: str, *, cleanup: bool = False) -> None:
    """Parse src_path into dataset_id, tracking progress on job_id.

    cleanup=True deletes src_path when done (owned temp file from /upload);
    cleanup=False leaves it (server file owned by the caller, e.g. Dataviewer).
    Updates the job row to done/error; never raises — a dead background thread
    would leave the job 'pending' forever.
    """
    bg = dbmod.connect(db_path)
    batch = None
    done = skipped = 0
    errors: list[str] = []
    hashes: list[str] = []

    def _ensure_batch(fmt: str) -> dict:
        nonlocal batch
        if batch is None:
            batch = repo.create_batch(bg, dataset_id=dataset_id, format=fmt, name=fname,
                                      source_info={"filename": fname, "source": "import"})
        return batch

    def _store(traj, raw_bytes: bytes, fmt: str) -> None:
        nonlocal done
        b = _ensure_batch(fmt)
        ch = repo.put_trajectory(bg, traj, source_path=fname, raw_bytes=raw_bytes,
                                 blob_dir=blob_dir, batch_id=b["id"], commit=False)
        hashes.append(ch)
        done += 1

    try:
        text = None
        with open(src_path, encoding="utf-8") as f:
            text = f.read()

        # Shape 1: whole file is a single JSON object.
        single = None
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                single = obj
        except json.JSONDecodeError:
            pass
        if single is not None:
            try:
                traj, fmt = detect_and_parse(single)
                _store(traj, text.encode("utf-8"), fmt)
            except ValueError as e:
                errors.append(f"single object: {e}")
            _finish(bg, job_id, batch, done, skipped, errors, hashes, total=1)
            return

        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            repo.update_job(bg, job_id, status="done", total=0, done=0, skipped=0)
            return

        # Shape 2: the whole list is one session log (CC/Codex sniff list shape).
        try:
            parsed_all = [json.loads(ln) for ln in lines]
            traj, fmt = detect_and_parse(parsed_all)
            _store(traj, text.encode("utf-8"), fmt)
            _finish(bg, job_id, batch, done, skipped, errors, hashes, total=1)
            return
        except (ValueError, json.JSONDecodeError):
            pass

        # Shape 3: each line is an independent trajectory.
        total = len(lines)
        for i, ln in enumerate(lines):
            try:
                obj = json.loads(ln)
                traj, fmt = detect_and_parse(obj)
                _store(traj, ln.encode("utf-8"), fmt)
            except Exception as e:  # noqa: BLE001 — one bad line shouldn't kill the batch
                errors.append(f"line {i+1}: {e}")
            if (done + skipped) % COMMIT_EVERY == 0:
                bg.commit()
                repo.update_job(bg, job_id, total=total, done=done, skipped=skipped)
        _finish(bg, job_id, batch, done, skipped, errors, hashes, total=total)
    except Exception as exc:  # noqa: BLE001 — otherwise job stays 'pending' forever
        repo.update_job(bg, job_id, status="error",
                        errors=json.dumps([{"error": str(exc)}], ensure_ascii=False))
    finally:
        bg.close()
        if cleanup:
            try:
                os.unlink(src_path)
            except OSError:
                pass


def _finish(bg, job_id, batch, done, skipped, errors, hashes, *, total: int) -> None:
    """Commit, count the batch, mark job done, then compute structural metrics.

    Status='done' is set BEFORE the metric loop on purpose (same lesson as the
    annotation runner): metrics on thousands of rows take minutes, and blocking
    'done' behind them kept the UI poller spinning until a timed-out poll aborted
    the import mid-count. Data is queryable the moment rows land.
    """
    bg.commit()
    if batch:
        repo.update_batch_count(bg, batch["id"], done)
    repo.update_job(bg, job_id, status="done", total=total, done=done, skipped=skipped,
                    errors=json.dumps(errors[:50], ensure_ascii=False))
    if hashes:
        from trajlens.metrics import compute_metrics
        import trajlens.metrics.builtins  # noqa: F401 — ensure registered
        for ch in hashes:
            try:
                compute_metrics(bg, ch)
            except Exception:  # noqa: BLE001 — metrics self-refresh on staleness
                pass
