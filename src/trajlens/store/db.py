import pathlib
import sqlite3

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def connect(path: str) -> sqlite3.Connection:
    # ponytail: check_same_thread=False — single connection, no concurrent writers in slice 1
    # (FastAPI routes run on worker threads). Slice 2's async runner needs §10.C.8 single-writer discipline.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Run *.sql in migrations/ whose NNN prefix exceeds PRAGMA user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        n = int(f.name.split("_")[0])
        if n > version:
            conn.executescript(f.read_text())
            conn.execute(f"PRAGMA user_version={n}")
            conn.commit()
            version = n
    return version
