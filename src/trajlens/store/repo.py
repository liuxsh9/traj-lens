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


def list_trajectories(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT content_hash, items_count, created_at FROM trajectories"
        " ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
