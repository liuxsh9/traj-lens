from typer.testing import CliRunner

from tests.conftest import FIXTURES
from trajlens.cli import app
from trajlens.store import db as dbmod, repo

runner = CliRunner()


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
