import datetime
import hashlib
import json
import pathlib
import uuid

from trajlens.core import grouping
from trajlens.core.model import Trajectory, parse_item


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def put_trajectory(conn, traj: Trajectory, *, source_path=None,
                   raw_bytes: bytes | None = None, blob_dir: str | None = None,
                   batch_id: str | None = None) -> str:
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
        "INSERT INTO ingestions(content_hash, source_path, raw_sha, ingested_at, batch_id)"
        " VALUES(?, ?, ?, ?, ?)", (ch, source_path, raw_sha, _now(), batch_id))
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



# ── Dataset / Batch CRUD ──────────────────────────────────────────────

def _slug(name: str) -> str:
    """Lowercase, replace non-alphanum with hyphens, collapse runs."""
    import re
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "ds"


def create_dataset(conn, *, name: str, description: str = "") -> dict:
    did = _slug(name) if name != "_default" else "_default"
    # avoid slug collision: append short suffix
    if conn.execute("SELECT 1 FROM datasets WHERE id=?", (did,)).fetchone():
        did = f"{did}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO datasets(id, name, description, created_at) VALUES(?,?,?,?)",
        (did, name, description, _now()))
    conn.commit()
    return {"id": did, "name": name, "description": description}


def get_or_create_dataset(conn, *, name: str) -> dict:
    row = conn.execute("SELECT * FROM datasets WHERE name=?", (name,)).fetchone()
    if row:
        return dict(row)
    return create_dataset(conn, name=name)


def get_dataset(conn, dataset_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    return dict(row) if row else None


def list_datasets(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT d.*, COUNT(DISTINCT i.content_hash) AS traj_count,
               COUNT(DISTINCT b.id) AS batch_count
        FROM datasets d
        LEFT JOIN batches b ON b.dataset_id = d.id
        LEFT JOIN ingestions i ON i.batch_id = b.id
        GROUP BY d.id
        ORDER BY d.created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def delete_dataset(conn, dataset_id: str) -> bool:
    if dataset_id == "_default":
        return False
    # null out batch_ids on ingestions, delete batches, delete dataset
    batch_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM batches WHERE dataset_id=?", (dataset_id,)).fetchall()]
    for bid in batch_ids:
        conn.execute("UPDATE ingestions SET batch_id=NULL WHERE batch_id=?", (bid,))
    conn.execute("DELETE FROM batches WHERE dataset_id=?", (dataset_id,))
    conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
    conn.commit()
    return True


def create_batch(conn, *, dataset_id: str, format: str,
                 name: str = "", source_info: dict | None = None) -> dict:
    bid = uuid.uuid4().hex[:12]
    info = json.dumps(source_info or {})
    conn.execute(
        "INSERT INTO batches(id, dataset_id, name, format, source_info, traj_count, created_at)"
        " VALUES(?,?,?,?,?,0,?)", (bid, dataset_id, name, format, info, _now()))
    conn.commit()
    return {"id": bid, "dataset_id": dataset_id, "name": name, "format": format}


def list_batches(conn, dataset_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM batches WHERE dataset_id=? ORDER BY created_at DESC",
        (dataset_id,)).fetchall()
    return [dict(r) for r in rows]


def update_batch_count(conn, batch_id: str, count: int) -> None:
    conn.execute("UPDATE batches SET traj_count=? WHERE id=?", (count, batch_id))
    conn.commit()


def create_export_artifact(conn, *, dataset_id: str, exporter: str,
                           config: dict | None = None, traj_count: int = 0,
                           output_path: str = "") -> dict:
    eid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO export_artifacts(id, dataset_id, exporter, config, traj_count, output_path, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (eid, dataset_id, exporter, json.dumps(config or {}), traj_count, output_path, _now()))
    conn.commit()
    return {"id": eid, "dataset_id": dataset_id, "exporter": exporter,
            "traj_count": traj_count, "output_path": output_path}


def list_export_artifacts(conn, dataset_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM export_artifacts WHERE dataset_id=? ORDER BY created_at DESC",
        (dataset_id,)).fetchall()
    return [dict(r) for r in rows]


def get_dataset_stats(conn, dataset_id: str) -> dict:
    """Aggregate metrics, resolution distribution, tags, and batch breakdown for a dataset."""
    # ponytail: one query to get all metric values for trajectories in this dataset
    rows = conn.execute("""
        SELECT m.metric_id, m.value
        FROM metrics m
        INNER JOIN ingestions i ON i.content_hash = m.content_hash
        INNER JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
    """, (dataset_id,)).fetchall()

    from collections import defaultdict, Counter
    metric_vals: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        try:
            v = json.loads(r["value"])
            if isinstance(v, (int, float)) and v >= 0:
                metric_vals[r["metric_id"]].append(float(v))
        except (json.JSONDecodeError, TypeError):
            pass

    def _summarize(vals: list[float]) -> dict:
        if not vals:
            return {"min": 0, "max": 0, "avg": 0, "count": 0}
        return {"min": min(vals), "max": max(vals),
                "avg": round(sum(vals) / len(vals), 1), "count": len(vals)}

    metrics_summary = {k: _summarize(v) for k, v in metric_vals.items()}

    # resolution distribution
    res_rows = conn.execute("""
        SELECT a.value
        FROM annotations a
        JOIN annotation_targets at2 ON a.target_hash = at2.target_hash
        JOIN annotators n ON a.annotator_id = n.id AND a.annotator_version = n.version AND n.active = 1
        JOIN ingestions i ON i.content_hash = at2.content_hash
        JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
        WHERE a.annotator_id = 'resolution'
    """, (dataset_id,)).fetchall()
    res_dist = Counter()
    for r in res_rows:
        try:
            v = json.loads(r["value"])
            res_dist[v.get("resolution", "unknown")] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # top tags from topic annotations
    tag_rows = conn.execute("""
        SELECT a.value
        FROM annotations a
        JOIN annotation_targets at2 ON a.target_hash = at2.target_hash
        JOIN annotators n ON a.annotator_id = n.id AND a.annotator_version = n.version AND n.active = 1
        JOIN ingestions i ON i.content_hash = at2.content_hash
        JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
        WHERE a.annotator_id = 'topic'
    """, (dataset_id,)).fetchall()
    tag_counter = Counter()
    for r in tag_rows:
        try:
            v = json.loads(r["value"])
            for tag in v.get("tags", []):
                tag_counter[tag] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # batch breakdown
    batches = conn.execute("""
        SELECT b.id, b.name, b.format, b.traj_count, b.created_at
        FROM batches b WHERE b.dataset_id = ?
        ORDER BY b.created_at DESC
    """, (dataset_id,)).fetchall()

    # total unique trajectories
    total = conn.execute("""
        SELECT COUNT(DISTINCT i.content_hash) FROM ingestions i
        JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
    """, (dataset_id,)).fetchone()[0]

    return {
        "total": total,
        "metrics": metrics_summary,
        "resolution": dict(res_dist),
        "top_tags": [{"tag": t, "count": c} for t, c in tag_counter.most_common(20)],
        "batches": [dict(r) for r in batches],
    }


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
        "SELECT a.target_hash, a.annotator_id, a.annotator_version, a.value, a.produced_at,"
        " at.target_type, at.target_idx"
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


# ── Metric CRUD ───────────────────────────────────────────────────────

def put_metric(conn, *, content_hash: str, metric_id: str,
               value, version: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO metrics"
        "(content_hash, metric_id, value, version, produced_at)"
        " VALUES(?, ?, ?, ?, ?)",
        (content_hash, metric_id, json.dumps(value), version, _now()))
    conn.commit()


def get_metrics_for_trajectory(conn, content_hash: str) -> dict:
    rows = conn.execute(
        "SELECT metric_id, value FROM metrics WHERE content_hash=?",
        (content_hash,)).fetchall()
    return {r["metric_id"]: json.loads(r["value"]) for r in rows}


def get_metrics_for_trajectory_full(conn, content_hash: str) -> dict:
    """Returns {metric_id: {value, version}} — includes version for staleness check."""
    rows = conn.execute(
        "SELECT metric_id, value, version FROM metrics WHERE content_hash=?",
        (content_hash,)).fetchall()
    return {r["metric_id"]: {"value": json.loads(r["value"]), "version": r["version"]}
            for r in rows}


def list_trajectories_with_metrics(conn) -> list[dict]:
    """List all — legacy compat wrapper."""
    return query_trajectories(conn)["items"]


def query_trajectories(
    conn,
    *,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    filters: list[dict] | None = None,
    dataset_id: str | None = None,
) -> dict:
    """Paginated list with server-side filtering + sorting.

    Returns {"items": [...], "total": N, "limit": L, "offset": O}.
    Filters: [{"field": "resolution", "op": "=", "value": "resolved"}, ...]
    """
    # ponytail: build a single CTE that joins trajectories + metrics + annotations,
    # then filter/sort/page on that. Metrics and annotations are pivoted via
    # GROUP BY + json_extract so each trajectory is one row.

    # --- materialised view CTE ---
    # ponytail: dataset scoping via optional INNER JOIN on ingestions+batches
    ds_join = ""
    cte_params: list = []
    if dataset_id:
        ds_join = (" INNER JOIN ingestions _di ON _di.content_hash = t.content_hash"
                   " INNER JOIN batches _db ON _di.batch_id = _db.id AND _db.dataset_id = ?")
        cte_params.append(dataset_id)

    cte = f"""
    WITH mv AS (
      SELECT
        t.content_hash, t.items_count, t.created_at,
        -- metrics (pivoted)
        MAX(CASE WHEN m.metric_id='turn_count' THEN CAST(m.value AS INTEGER) END) AS turn_count,
        MAX(CASE WHEN m.metric_id='step_count' THEN CAST(m.value AS INTEGER) END) AS step_count,
        MAX(CASE WHEN m.metric_id='tool_count' THEN CAST(m.value AS INTEGER) END) AS tool_count,
        MAX(CASE WHEN m.metric_id='pushback_count' THEN CAST(m.value AS INTEGER) END) AS pushback_count,
        MAX(CASE WHEN m.metric_id='success_score' THEN CAST(m.value AS INTEGER) END) AS success_score,
        -- annotations (resolution + topic)
        MAX(CASE WHEN a.annotator_id='resolution' THEN a.value END) AS ann_resolution,
        MAX(CASE WHEN a.annotator_id='topic' THEN a.value END) AS ann_topic
      FROM trajectories t
      {ds_join}
      LEFT JOIN metrics m ON m.content_hash = t.content_hash
      LEFT JOIN (
        annotation_targets at2
        JOIN annotations a ON a.target_hash = at2.target_hash
        JOIN annotators n ON a.annotator_id = n.id AND a.annotator_version = n.version AND n.active = 1
      ) ON at2.content_hash = t.content_hash AND a.annotator_id IN ('resolution','topic')
      GROUP BY t.content_hash
    )
    """

    where_parts: list[str] = []
    params: list = list(cte_params)

    # --- safe column map for filtering/sorting ---
    col_map = {
        "turns": "turn_count", "steps": "step_count", "tools": "tool_count",
        "pushback_count": "pushback_count", "score": "success_score",
        "created_at": "created_at",
    }
    op_map = {"=": "=", "≥": ">=", "≤": "<=", "≠": "!="}

    for f in (filters or []):
        field, op, val = f.get("field", ""), f.get("op", ""), f.get("value", "")
        if field == "resolution":
            sql_op = "=" if op == "=" else "!="
            where_parts.append(f"json_extract(ann_resolution, '$.resolution') {sql_op} ?")
            params.append(val)
        elif field == "tags":
            if op == "∋":
                where_parts.append("ann_topic LIKE ?")
            else:
                where_parts.append("(ann_topic IS NULL OR ann_topic NOT LIKE ?)")
            params.append(f"%{val}%")
        elif field in col_map and op in op_map:
            where_parts.append(f"COALESCE({col_map[field]}, 0) {op_map[op]} ?")
            params.append(int(val))

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # --- sort ---
    sort_col = col_map.get(sort_by, "created_at")
    direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
    order_sql = f" ORDER BY {sort_col} {direction}"

    # --- count ---
    count_sql = cte + f"SELECT COUNT(*) FROM mv{where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]

    # --- page ---
    page_sql = cte + f"SELECT * FROM mv{where_sql}{order_sql} LIMIT ? OFFSET ?"
    rows = conn.execute(page_sql, params + [limit, offset]).fetchall()

    # --- format ---
    items = []
    for r in rows:
        ann_res = json.loads(r["ann_resolution"]) if r["ann_resolution"] else None
        ann_topic = json.loads(r["ann_topic"]) if r["ann_topic"] else None
        summary: dict = {}
        if ann_res:
            summary["resolution"] = ann_res.get("resolution", "indeterminate")
        if ann_topic:
            summary["title"] = ann_topic.get("title", "")
            summary["summary"] = ann_topic.get("summary", "")
            summary["tags"] = ann_topic.get("tags", [])
        items.append({
            "content_hash": r["content_hash"],
            "items_count": r["items_count"],
            "created_at": r["created_at"],
            "metrics": {
                "turn_count": r["turn_count"] or 0,
                "step_count": r["step_count"] or 0,
                "tool_count": r["tool_count"] or 0,
                "pushback_count": r["pushback_count"] or 0,
                "success_score": r["success_score"] if r["success_score"] is not None else -1,
            },
            "annotations": summary,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}
