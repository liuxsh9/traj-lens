from typer.testing import CliRunner

from tests.conftest import FIXTURES
from trajlens.cli import app, _ensure_frontend_fresh
from trajlens.store import db as dbmod, repo

runner = CliRunner()


def _make_web(tmp_path, *, dist_newer: bool):
    """Build a fake web/ tree; return its path. dist_newer controls staleness."""
    import os
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "dist" / "assets").mkdir(parents=True)
    (web / "src" / "App.tsx").write_text("x")
    bundle = web / "dist" / "assets" / "index-abc.js"
    bundle.write_text("y")
    # force ordering: bump whichever should be newer
    src_t, dist_t = (10.0, 20.0) if dist_newer else (20.0, 10.0)
    os.utime(web / "src" / "App.tsx", (src_t, src_t))
    os.utime(bundle, (dist_t, dist_t))
    return web


def test_frontend_fresh_skips_build_when_current(tmp_path, monkeypatch):
    import subprocess
    web = _make_web(tmp_path, dist_newer=True)
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    _ensure_frontend_fresh(web, autobuild=True)
    assert called == []  # dist is current → never shells out to npm


def test_frontend_fresh_rebuilds_when_stale(tmp_path, monkeypatch):
    import shutil
    import subprocess
    web = _make_web(tmp_path, dist_newer=False)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/npm")
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append((a, k)))
    _ensure_frontend_fresh(web, autobuild=True)
    assert len(called) == 1
    assert called[0][0][0] == ["npm", "run", "build"]
    assert called[0][1]["cwd"] == str(web)


def test_frontend_fresh_warns_no_build_flag(tmp_path, monkeypatch):
    import subprocess
    web = _make_web(tmp_path, dist_newer=False)
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    _ensure_frontend_fresh(web, autobuild=False)
    assert called == []  # --no-build → warn only, never build


def test_ingest_prints_hash_and_stores(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text((FIXTURES / "panguml2_weather.json").read_text())
    db = tmp_path / "t.db"
    result = runner.invoke(app, ["ingest", str(src),
                                 "--db", str(db), "--blob-dir", str(tmp_path / "blobs")])
    assert result.exit_code == 0
    # output is like: ingested 1 trajectory (906845bc736f…)
    last_line = result.stdout.strip().splitlines()[-1]
    assert "ingested" in last_line

    conn = dbmod.connect(str(db))
    rows = conn.execute("SELECT content_hash FROM trajectories").fetchall()
    assert len(rows) == 1
