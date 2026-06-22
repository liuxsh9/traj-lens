import datetime
import hashlib
import json
import pathlib

from trajlens.core import grouping
from trajlens.core.model import Trajectory, parse_item


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def put_trajectory(conn, traj: Trajectory, *, source_path=None,
                   raw_bytes: bytes | None = None, blob_dir: str | None = None) -> str:
    """Insert trajectory+items if new (dedup by content_hash); always record an ingestion."""
    ch = traj.content_hash
    exists = conn.execute(
        "SELECT 1 FROM trajectories WHERE content_hash=?", (ch,)).fetchone()

    raw_sha = None
    if raw_bytes is not None and blob_dir is not None:
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        d = pathlib.Path(blob_dir)
        d.mkdir(parents=True, exist_ok=True)
        fp = d / raw_sha
        if not fp.exists():
            fp.write_bytes(raw_bytes)
        conn.execute("INSERT OR IGNORE INTO raw_blobs(raw_sha, path) VALUES(?, ?)",
                     (raw_sha, str(fp)))

    if not exists:
        conn.execute(
            "INSERT INTO trajectories(content_hash, items_count, tools, meta, created_at)"
            " VALUES(?, ?, ?, ?, ?)",
            (ch, len(traj.items), json.dumps(traj.tools), json.dumps(traj.meta), _now()))
        for i, it in enumerate(traj.items):
            payload = it.model_dump(exclude={"provenance", "step_id", "run_id"})
            prov = it.provenance.model_dump() if it.provenance else None
            conn.execute(
                "INSERT INTO items(content_hash, idx, type, payload, provenance)"
                " VALUES(?, ?, ?, ?, ?)",
                (ch, i, it.type, json.dumps(payload),
                 json.dumps(prov) if prov else None))

    conn.execute(
        "INSERT INTO ingestions(content_hash, source_path, raw_sha, ingested_at)"
        " VALUES(?, ?, ?, ?)", (ch, source_path, raw_sha, _now()))
    conn.commit()
    return ch


def get_trajectory(conn, content_hash: str) -> Trajectory | None:
    row = conn.execute(
        "SELECT * FROM trajectories WHERE content_hash=?", (content_hash,)).fetchone()
    if not row:
        return None
    rows = conn.execute(
        "SELECT * FROM items WHERE content_hash=? ORDER BY idx", (content_hash,)).fetchall()
    items = [parse_item(json.loads(r["payload"]),
                        json.loads(r["provenance"]) if r["provenance"] else None)
             for r in rows]
    items = grouping.assign_groups(items)   # grouping is a read-time projection (§3.5)
    return Trajectory(content_hash=content_hash, items=items,
                      tools=json.loads(row["tools"]), meta=json.loads(row["meta"]))



# ── Annotation CRUD ────────────────────────────────────────────────────

def register_annotator(conn, *, id: str, version: str, config_hash: str) -> None:
    conn.execute("UPDATE annotators SET active=0 WHERE id=?", (id,))
    conn.execute(
        "INSERT OR REPLACE INTO annotators(id, version, config_hash, active, registered_at)"
        " VALUES(?, ?, ?, 1, ?)", (id, version, config_hash, _now()))
    conn.commit()


def put_annotation(conn, *, target_hash: str, annotator_id: str,
                   annotator_version: str, value, inputs_hash: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT OR REPLACE INTO annotations"
        "(target_hash, annotator_id, annotator_version, value, inputs_hash, produced_at)"
        " VALUES(?, ?, ?, ?, ?, ?)",
        (target_hash, annotator_id, annotator_version,
         json.dumps(value, ensure_ascii=False), inputs_hash, _now()))
    conn.commit()


def get_annotations(conn, target_hash: str) -> list[dict]:
    rows = conn.execute(
        "SELECT a.* FROM annotations a"
        " JOIN annotators t ON a.annotator_id=t.id AND a.annotator_version=t.version"
        " WHERE a.target_hash=? AND t.active=1", (target_hash,)).fetchall()
    return [dict(r) for r in rows]


def get_annotations_for_trajectory(conn, content_hash: str) -> list[dict]:
    # ponytail: annotation_targets maps target_hash→content_hash; query via that
    rows = conn.execute(
        "SELECT a.target_hash, a.annotator_id, a.annotator_version, a.value, a.produced_at"
        " FROM annotations a"
        " JOIN annotation_targets at ON a.target_hash=at.target_hash"
        " JOIN annotators t ON a.annotator_id=t.id AND a.annotator_version=t.version"
        " WHERE at.content_hash=? AND t.active=1"
        " ORDER BY a.produced_at", (content_hash,)).fetchall()
    return [dict(r) for r in rows]


def link_annotation_target(conn, *, target_hash: str, content_hash: str,
                           target_type: str, target_idx: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO annotation_targets(target_hash, content_hash, target_type, target_idx)"
        " VALUES(?, ?, ?, ?)", (target_hash, content_hash, target_type, target_idx))


def create_job(conn, *, job_id: str, annotator_id: str) -> dict:
    now = _now()
    conn.execute(
        "INSERT INTO jobs(id, annotator_id, status, total, done, errors, created_at, updated_at)"
        " VALUES(?, ?, 'pending', 0, 0, '[]', ?, ?)", (job_id, annotator_id, now, now))
    conn.commit()
    return {"id": job_id, "annotator_id": annotator_id, "status": "pending"}


def update_job(conn, job_id: str, **kwargs) -> None:
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    conn.execute(f"UPDATE jobs SET {sets}, updated_at=? WHERE id=?", vals + [_now(), job_id])
    conn.commit()


def get_job(conn, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_trajectories(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT content_hash, items_count, created_at FROM trajectories"
        " ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
