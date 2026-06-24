import os
import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from trajlens.store import db as dbmod
from trajlens.api.routes import router

# ponytail: web/dist is the vite build output; serve if present, skip if not
WEB_DIST = pathlib.Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"


def create_app(db_path: str | None = None, blob_dir: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("TRAJLENS_DB", "trajlens.db")
    blob_dir = blob_dir or os.environ.get("TRAJLENS_BLOBS", "blobs")
    app = FastAPI(title="traj-lens", version="0.0.1")
    # Migrate once at startup
    conn = dbmod.connect(db_path)
    dbmod.migrate(conn)
    conn.close()
    # Store path — routes create per-request connections (SQLite conn is not thread-safe)
    app.state.db_path = db_path
    app.state.blob_dir = blob_dir
    app.include_router(router)
    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    if not WEB_DIST.is_dir():
        return
    index = WEB_DIST / "index.html"
    if not index.exists():
        return

    # Vite fingerprints asset filenames (index-AbC123.js) so they're immutable
    # and cache forever; index.html points at the current hash and MUST revalidate
    # each load, or a rebuild strands users on a stale bundle ("undefined imported").
    IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
    NO_CACHE = {"Cache-Control": "no-cache"}

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str):
        # serve static file if it exists, otherwise index.html (SPA)
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            headers = IMMUTABLE if full_path.startswith("assets/") else NO_CACHE
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers=NO_CACHE)


app = create_app()
