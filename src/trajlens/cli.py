import json
import os
import pathlib

import typer


def _load_dotenv():
    """Read .env from CWD if present — stdlib only, no dependency."""
    env_file = pathlib.Path(".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

_DB = os.environ.get("TRAJLENS_DB", "trajlens.db")
_BLOBS = os.environ.get("TRAJLENS_BLOBS", "blobs")

app = typer.Typer(help="traj-lens CLI")


@app.command()
def ingest(
    path: str,
    dataset: str = "_default",
    description: str = "",
    db: str = _DB,
    blob_dir: str = _BLOBS,
):
    """Ingest trajectories from JSON or JSONL files.

    Supports three shapes:
    - Single JSON object (openai_messages / panguml2) → 1 trajectory
    - JSONL where each line is an independent trajectory → N trajectories
    - JSONL session log (CC / Codex: all lines = one session) → 1 trajectory
    """
    from trajlens.adapters import detect_and_parse
    from trajlens.store import db as dbmod, repo

    conn = dbmod.connect(db)
    dbmod.migrate(conn)

    ds = repo.get_or_create_dataset(conn, name=dataset, description=description)
    fpath = pathlib.Path(path)
    fname = fpath.name
    count = 0
    errors: list[str] = []
    fmt = None
    batch_id = None

    def _ensure_batch(format_name: str) -> str:
        nonlocal batch_id, fmt
        if batch_id is None:
            fmt = format_name
            b = repo.create_batch(conn, dataset_id=ds["id"], format=format_name,
                                  name=fname, source_info={"filename": fname})
            batch_id = b["id"]
        return batch_id

    # Try single JSON object first
    text = fpath.read_text()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            traj, fmt_name = detect_and_parse(obj)
            bid = _ensure_batch(fmt_name)
            ch = repo.put_trajectory(conn, traj, source_path=path,
                                     raw_bytes=text.encode("utf-8"),
                                     blob_dir=blob_dir, batch_id=bid)
            repo.update_batch_count(conn, bid, 1)
            typer.echo(f"ingested 1 trajectory ({ch[:12]}…)")
            return
    except (json.JSONDecodeError, ValueError):
        pass

    # ponytail: read lines from file (not splitlines — avoids breaking on \n inside JSON strings)
    raw_lines: list[str] = []
    with open(path) as f:
        raw_lines = f.readlines()
    raw_lines = [ln for ln in raw_lines if ln.strip()]
    if not raw_lines:
        typer.echo("no data found", err=True)
        raise typer.Exit(1)

    # Try the whole list as one session log (CC/Codex sniff checks list shape)
    try:
        parsed_all = [json.loads(ln) for ln in raw_lines]
        traj, fmt_name = detect_and_parse(parsed_all)
        bid = _ensure_batch(fmt_name)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=text.encode("utf-8"),
                                 blob_dir=blob_dir, batch_id=bid)
        repo.update_batch_count(conn, bid, 1)
        typer.echo(f"ingested 1 session trajectory ({ch[:12]}…)")
        return
    except (ValueError, json.JSONDecodeError):
        pass

    # Per-line: each line is an independent trajectory
    total = len(raw_lines)
    for i, ln in enumerate(raw_lines):
        try:
            obj = json.loads(ln)
            traj, fmt_name = detect_and_parse(obj)
            bid = _ensure_batch(fmt_name)
            repo.put_trajectory(conn, traj, source_path=path,
                                raw_bytes=ln.encode("utf-8"),
                                blob_dir=blob_dir, batch_id=bid)
            count += 1
        except Exception as e:
            errors.append(f"line {i+1}: {e}")
        if (i + 1) % 500 == 0 or i + 1 == total:
            typer.echo(f"\r  {i+1}/{total} processed, {count} ok, {len(errors)} errors", nl=(i+1 == total), err=True)

    if batch_id:
        repo.update_batch_count(conn, batch_id, count)
    typer.echo(f"ingested {count} trajectories into \"{dataset}\"" +
               (f" ({len(errors)} errors skipped)" if errors else ""))
    for err in errors[:10]:
        typer.echo(f"  {err}", err=True)
    if len(errors) > 10:
        typer.echo(f"  … and {len(errors)-10} more", err=True)


@app.command()
def annotate(
    config_path: str = typer.Argument(..., help="Annotator YAML config path"),
    db: str = _DB,
):
    """Run an annotator on all stored trajectories."""
    import asyncio
    from trajlens.annotate.runner import load_annotator_config, load_annotator_module, run_annotator
    from trajlens.store import db as dbmod

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    spec = load_annotator_config(config_path)
    mod = load_annotator_module(spec)
    typer.echo(f"Running {spec.id}@{spec.version} ({spec.type}, target={spec.target.value})")

    profiles = None
    if spec.type == "llm":
        from trajlens.annotate.llm_client import load_profiles
        profiles = load_profiles()

    result = asyncio.run(run_annotator(
        conn, spec, mod, llm_profiles=profiles))
    typer.echo(json.dumps(result, indent=2))


@app.command()
def metrics(db: str = _DB):
    """Compute all built-in metrics for stored trajectories."""
    from trajlens.store import db as dbmod
    import trajlens.metrics.builtins  # noqa: F401 — registers metrics
    from trajlens.metrics import compute_all

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    n = compute_all(conn)
    typer.echo(f"Computed metrics for {n} trajectories")


@app.command()
def export(
    dataset: str = typer.Argument(..., help="Dataset name or id"),
    format: str = typer.Option("panguml2", help="Export format"),
    output: str = typer.Option("export.jsonl", help="Output file path"),
    db: str = _DB,
    blob_dir: str = _BLOBS,
):
    """Export trajectories from a dataset to training format."""
    from trajlens.store import db as dbmod, repo
    import trajlens.export.panguml2  # noqa: F401 — register exporter
    from trajlens.export import EXPORTERS

    conn = dbmod.connect(db)
    dbmod.migrate(conn)

    # resolve dataset by name or id
    ds = conn.execute("SELECT id FROM datasets WHERE name=? OR id=?",
                      (dataset, dataset)).fetchone()
    if not ds:
        typer.echo(f"dataset '{dataset}' not found", err=True)
        raise typer.Exit(1)
    ds_id = ds["id"]

    exporter_fn = EXPORTERS.get(format)
    if exporter_fn is None:
        typer.echo(f"unknown format '{format}', available: {list(EXPORTERS.keys())}", err=True)
        raise typer.Exit(1)

    # get all trajectories in dataset
    hashes = [r["content_hash"] for r in conn.execute("""
        SELECT DISTINCT i.content_hash FROM ingestions i
        JOIN batches b ON i.batch_id = b.id AND b.dataset_id = ?
    """, (ds_id,)).fetchall()]

    count = 0
    with open(output, "w") as f:
        for ch in hashes:
            record = exporter_fn(conn, ch, blob_dir=blob_dir)
            if record:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

    repo.create_export_artifact(conn, dataset_id=ds_id, exporter=format,
                                traj_count=count, output_path=output)
    typer.echo(f"exported {count} trajectories to {output}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, db: str = _DB, blob_dir: str = _BLOBS):
    """Run the API + web viewer."""
    import uvicorn
    os.environ["TRAJLENS_DB"] = db
    os.environ["TRAJLENS_BLOBS"] = blob_dir
    uvicorn.run("trajlens.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
