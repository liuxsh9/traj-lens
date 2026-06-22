import json
import pathlib

import typer

app = typer.Typer(help="traj-lens CLI")


@app.command()
def ingest(path: str, db: str = "trajlens.db", blob_dir: str = "blobs"):
    """Ingest a JSON object or JSONL file (one trajectory per line)."""
    from trajlens.adapters import detect_and_parse
    from trajlens.store import db as dbmod, repo

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    text = pathlib.Path(path).read_text()
    try:
        records = [(json.loads(text), text.encode("utf-8"))]          # one JSON object (maybe pretty-printed)
    except json.JSONDecodeError:
        records = [(json.loads(ln), ln.encode("utf-8"))               # JSONL: one trajectory per line
                   for ln in text.splitlines() if ln.strip()]
    for raw, raw_bytes in records:
        traj = detect_and_parse(raw)
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=raw_bytes, blob_dir=blob_dir)
        typer.echo(ch)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the API + (later) hosted web."""
    import uvicorn
    uvicorn.run("trajlens.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
