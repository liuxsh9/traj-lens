import json
import pathlib

import typer

app = typer.Typer(help="traj-lens CLI")


@app.command()
def ingest(path: str, db: str = "trajlens.db", blob_dir: str = "blobs"):
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
    text = pathlib.Path(path).read_text()
    raw_bytes = text.encode("utf-8")

    # Try single JSON object first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            traj = detect_and_parse(obj)
            ch = repo.put_trajectory(conn, traj, source_path=path,
                                     raw_bytes=raw_bytes, blob_dir=blob_dir)
            typer.echo(ch)
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
        traj = detect_and_parse(lines)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=raw_bytes, blob_dir=blob_dir)
        typer.echo(ch)
        return
    except ValueError:
        pass

    # Per-line: each line is an independent trajectory (openai_messages JSONL)
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        obj = json.loads(ln)
        traj = detect_and_parse(obj)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=ln.encode("utf-8"), blob_dir=blob_dir)
        typer.echo(ch)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the API + (later) hosted web."""
    import uvicorn
    uvicorn.run("trajlens.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
