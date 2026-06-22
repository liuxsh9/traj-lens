from fastapi import FastAPI

from trajlens.store import db as dbmod
from trajlens.api.routes import router


def create_app(db_path: str = "trajlens.db", blob_dir: str = "blobs") -> FastAPI:
    app = FastAPI(title="traj-lens", version="0.0.1")
    conn = dbmod.connect(db_path)
    dbmod.migrate(conn)
    app.state.conn = conn
    app.state.blob_dir = blob_dir
    app.include_router(router)
    return app


app = create_app()
