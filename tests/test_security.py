import json

from trajlens.store import db as dbmod, repo
from trajlens.core.model import Trajectory, MessageItem
from trajlens.core.identity import content_hash


def _seed(conn):
    items = [MessageItem(role="user", content="hi")]
    ch = content_hash(items)
    traj = Trajectory(content_hash=ch, items=items)
    ds = repo.get_or_create_dataset(conn, name="_default")
    b = repo.create_batch(conn, dataset_id=ds["id"], format="x", name="b", source_info={})
    repo.put_trajectory(conn, traj, source_path="x", raw_bytes=None,
                        blob_dir=str("/tmp"), batch_id=b["id"])
    return ch


def test_persist_findings_and_mirror_metric(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    findings = [
        {"item_idx": 14, "check_id": "dockerfile.last-user-is-root",
         "severity": "ERROR", "message": "root", "line": 1, "introduced": True},
        {"item_idx": 14, "check_id": "x.y", "severity": "WARNING", "message": "w",
         "line": None, "introduced": False},  # pre-existing
    ]
    repo.put_security_scan(conn, content_hash=ch, findings=findings,
                           scanned=3, ruleset_version="semgrep-1.2.3")

    got = repo.get_security_findings(conn, ch)
    assert len(got) == 2
    assert got[0]["introduced"] is True  # introduced sorted first
    scan = repo.get_security_scan(conn, ch)
    assert scan["finding_count"] == 2 and scan["introduced_count"] == 1
    assert scan["ruleset_version"] == "semgrep-1.2.3"
    # mirrored metric is the INTRODUCED count, not the total
    assert repo.get_metrics_for_trajectory(conn, ch)["introduced_findings_count"] == 1


def test_rescan_replaces_old_findings(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    repo.put_security_scan(conn, content_hash=ch, scanned=1, ruleset_version="v1",
                           findings=[{"item_idx": 1, "check_id": "a", "severity": "ERROR",
                                      "message": "m", "line": 2, "introduced": True}])
    repo.put_security_scan(conn, content_hash=ch, scanned=1, ruleset_version="v2", findings=[])
    assert repo.get_security_findings(conn, ch) == []
    assert repo.get_metrics_for_trajectory(conn, ch)["introduced_findings_count"] == 0


def test_query_filters_by_security_findings(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    repo.put_security_scan(conn, content_hash=ch, scanned=2, ruleset_version="v1",
                           findings=[{"item_idx": 1, "check_id": "a", "severity": "ERROR",
                                      "message": "m", "line": 1, "introduced": True}])
    # surfaced in list output
    row = repo.query_trajectories(conn)["items"][0]
    assert row["metrics"]["introduced_findings_count"] == 1
    # filterable: ≥1 matches, ≥2 excludes
    assert repo.query_trajectories(conn, filters=[
        {"field": "security_findings", "op": "≥", "value": "1"}])["total"] == 1
    assert repo.query_trajectories(conn, filters=[
        {"field": "security_findings", "op": "≥", "value": "2"}])["total"] == 0
