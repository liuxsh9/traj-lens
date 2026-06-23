import json
import pathlib

import typer

app = typer.Typer(help="traj-lens CLI")


@app.command()
def ingest(
    path: str,
    dataset: str = "_default",
    db: str = "trajlens.db",
    blob_dir: str = "blobs",
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

    ds = repo.get_or_create_dataset(conn, name=dataset)
    text = pathlib.Path(path).read_text()
    raw_bytes = text.encode("utf-8")
    fname = pathlib.Path(path).name
    count = 0
    fmt = None  # determined by first successful detect_and_parse
    batch_id = None  # created lazily on first success

    def _ensure_batch(format_name: str) -> str:
        nonlocal batch_id, fmt
        if batch_id is None:
            fmt = format_name
            b = repo.create_batch(conn, dataset_id=ds["id"], format=format_name,
                                  name=fname, source_info={"filename": fname})
            batch_id = b["id"]
        return batch_id

    # Try single JSON object first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            traj, fmt_name = detect_and_parse(obj)
            bid = _ensure_batch(fmt_name)
            ch = repo.put_trajectory(conn, traj, source_path=path,
                                     raw_bytes=raw_bytes, blob_dir=blob_dir,
                                     batch_id=bid)
            typer.echo(ch)
            count = 1
            repo.update_batch_count(conn, bid, count)
            return
    except json.JSONDecodeError:
        pass

    # JSONL: parse all lines
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if not lines:
        typer.echo("no data found", err=True)
        raise typer.Exit(1)

    # ponytail: try the whole list as one session log (CC/Codex sniff checks list shape);
    # if no adapter matches, fall back to per-line independent trajectories.
    try:
        traj, fmt_name = detect_and_parse(lines)
        bid = _ensure_batch(fmt_name)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=raw_bytes, blob_dir=blob_dir,
                                 batch_id=bid)
        typer.echo(ch)
        count = 1
        repo.update_batch_count(conn, bid, count)
        return
    except ValueError:
        pass

    # Per-line: each line is an independent trajectory (openai_messages JSONL)
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        obj = json.loads(ln)
        traj, fmt_name = detect_and_parse(obj)
        bid = _ensure_batch(fmt_name)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=ln.encode("utf-8"), blob_dir=blob_dir,
                                 batch_id=bid)
        typer.echo(ch)
        count += 1

    if batch_id:
        repo.update_batch_count(conn, batch_id, count)


@app.command()
def annotate(
    config_path: str = typer.Argument(..., help="Annotator YAML config path"),
    db: str = "trajlens.db",
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
def metrics(db: str = "trajlens.db"):
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
    db: str = "trajlens.db",
    blob_dir: str = "blobs",
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
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the API + (later) hosted web."""
    import uvicorn
    uvicorn.run("trajlens.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
