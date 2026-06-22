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
    ch = result.stdout.strip().splitlines()[-1]
    assert len(ch) == 64

    conn = dbmod.connect(str(db))
    assert repo.get_trajectory(conn, ch) is not None
