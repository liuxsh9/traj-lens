"""Stale-annotation detection: get_annotations_for_trajectory returns each
annotation with the annotator's currently-active version so the viewer can flag
stale ones, and dedupes when a trajectory carries multiple versions."""
import json

from trajlens.store import db as dbmod, repo
from trajlens.core.model import Trajectory, MessageItem
from trajlens.core.identity import content_hash


def _seed(conn):
    items = [MessageItem(role="user", content="hi")]
    ch = content_hash(items)
    ds = repo.get_or_create_dataset(conn, name="_default")
    b = repo.create_batch(conn, dataset_id=ds["id"], format="x", name="b", source_info={})
    repo.put_trajectory(conn, Trajectory(content_hash=ch, items=items),
                        source_path="x", raw_bytes=None, blob_dir="/tmp", batch_id=b["id"])
    return ch


def _annotate(conn, ch, version):
    repo.register_annotator(conn, id="resolution", version=version, config_hash=version)
    repo.link_annotation_target(conn, target_hash=ch, content_hash=ch,
                                target_type="session", target_idx=0)
    conn.commit()  # link doesn't commit; flush before put_annotation's BEGIN IMMEDIATE
    repo.put_annotation(conn, target_hash=ch, annotator_id="resolution",
                        annotator_version=version, value={"resolution": "resolved"},
                        inputs_hash="i")


def test_active_version_attached_and_fresh(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    _annotate(conn, ch, "v1")
    [a] = repo.get_annotations_for_trajectory(conn, ch)
    assert a["annotator_version"] == "v1" and a["active_version"] == "v1"  # fresh


def test_stale_when_active_version_advanced(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    _annotate(conn, ch, "v1")
    # config changed -> v2 registered active, but this trajectory only has v1
    repo.register_annotator(conn, id="resolution", version="v2", config_hash="v2")
    anns = repo.get_annotations_for_trajectory(conn, ch)
    assert len(anns) == 1  # still one chip, not duplicated
    a = anns[0]
    assert a["annotator_version"] == "v1" and a["active_version"] == "v2"  # stale


def test_dedup_prefers_active_when_both_versions_ran(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    ch = _seed(conn)
    _annotate(conn, ch, "v1")
    _annotate(conn, ch, "v2")  # re-run under new active version (v1 row lingers)
    anns = repo.get_annotations_for_trajectory(conn, ch)
    assert len(anns) == 1                       # deduped
    assert anns[0]["annotator_version"] == "v2"  # active kept, not stale
    assert anns[0]["active_version"] == "v2"
