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
_HOST = os.environ.get("TRAJLENS_HOST", "127.0.0.1")  # 0.0.0.0 to allow LAN/server access
_PORT = int(os.environ.get("TRAJLENS_PORT", "8000"))

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
    dataset: str = typer.Option("", help="Restrict to a dataset (name or id). Empty = all."),
    db: str = _DB,
):
    """Run an annotator on stored trajectories."""
    import asyncio
    from trajlens.annotate.runner import load_annotator_config, load_annotator_module, run_annotator
    from trajlens.store import db as dbmod, repo

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    spec = load_annotator_config(config_path)
    mod = load_annotator_module(spec)

    content_hashes = None
    ds_label = "all"
    if dataset:
        ds = conn.execute("SELECT id, name FROM datasets WHERE name=? OR id=?",
                          (dataset, dataset)).fetchone()
        if not ds:
            typer.echo(f"dataset '{dataset}' not found", err=True)
            raise typer.Exit(1)
        content_hashes = [t["content_hash"] for t in repo.list_trajectories(conn, dataset_id=ds["id"])]
        ds_label = ds["name"]

    typer.echo(f"Running {spec.id}@{spec.version} ({spec.type}, target={spec.target.value}, dataset={ds_label})")

    profiles = None
    if spec.type == "llm":
        from trajlens.annotate.llm_client import load_profiles
        profiles = load_profiles()

    result = asyncio.run(run_annotator(
        conn, spec, mod, content_hashes=content_hashes, llm_profiles=profiles))
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


def _newest_mtime(root: pathlib.Path, skip: set[str]) -> float:
    latest = 0.0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dirpath, f)))
            except OSError:
                pass
    return latest


def _ensure_frontend_fresh(web: pathlib.Path | None = None, *, autobuild: bool = True) -> None:
    """Root-cause fix for the stale-bundle class of bug. web/dist is a gitignored
    Vite artifact that `serve` only statically hosts — a git pull/push never updates
    it, so an out-of-date dist silently serves old JS against a newer API (symptom:
    "undefined imported"). On startup, rebuild dist when any build input under web/
    is newer (build is <1s). Degrade gracefully — missing npm or a failed build
    warns loudly but never blocks serving the existing bundle."""
    import shutil
    import subprocess

    if web is None:
        from trajlens.api.app import WEB_DIST
        web = WEB_DIST.parent
    src_root = web / "src"
    if not src_root.is_dir():
        return  # installed without frontend sources — nothing to build
    dist = web / "dist"
    # newest of all build inputs (src, package.json, vite/ts config, index.html)
    # vs the built bundle. node_modules/dist excluded.
    inputs_mtime = _newest_mtime(web, {"node_modules", "dist"})
    dist_mtime = _newest_mtime(dist, set()) if dist.is_dir() else 0.0
    if dist.is_dir() and dist_mtime >= inputs_mtime:
        return  # bundle already current

    why = "missing" if not dist.is_dir() else "stale (web source is newer)"
    if not autobuild:
        typer.secho(f"⚠ web/dist is {why} — run: cd web && npm run build", fg="yellow", err=True)
        return
    if shutil.which("npm") is None:
        typer.secho(f"⚠ web/dist is {why} and npm not found — serving as-is. "
                    "Build on a machine with npm: cd web && npm run build", fg="yellow", err=True)
        return
    typer.secho(f"web/dist is {why} — rebuilding frontend (cd web && npm run build)…",
                fg="cyan", err=True)
    try:
        subprocess.run(["npm", "run", "build"], cwd=str(web), check=True)
        typer.secho("✓ frontend rebuilt", fg="green", err=True)
    except subprocess.CalledProcessError as e:
        typer.secho(f"⚠ frontend build failed ({e}) — serving existing web/dist", fg="red", err=True)


@app.command()
def serve(host: str = _HOST, port: int = _PORT, db: str = _DB, blob_dir: str = _BLOBS,
          reload: bool = False, build: bool = True):
    """Run the API + web viewer. Pass --reload for dev (auto-restart on code edits).

    Host/port default from TRAJLENS_HOST/TRAJLENS_PORT in .env; set host=0.0.0.0
    to expose on a LAN/server. CLI flags override .env. By default a stale/missing
    web/dist is rebuilt automatically before serving (pass --no-build to skip).
    """
    import uvicorn
    os.environ["TRAJLENS_DB"] = db
    os.environ["TRAJLENS_BLOBS"] = blob_dir
    _ensure_frontend_fresh(autobuild=build)
    # reload watches src/ and respawns workers; env vars above are inherited.
    uvicorn.run("trajlens.api.app:app", host=host, port=port, reload=reload,
                reload_dirs=["src"] if reload else None)


if __name__ == "__main__":
    app()
