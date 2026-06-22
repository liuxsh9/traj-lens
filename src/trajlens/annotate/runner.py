"""Annotation runner — drives a rule or LLM annotator over stored trajectories.

Cache-aware: skips (target, annotator, version) triples already in the DB, so
re-runs after a version bump only fill the gaps. Errors are per-target, logged,
and recorded on the job; one bad target never aborts the run.
"""
import importlib
import json
import logging

from trajlens.annotate import (
    AnnotatorSpec, Target,
    compute_version, enumerate_targets, project_context, compute_inputs_hash,
)
from trajlens.annotate.llm_client import chat_completion
from trajlens.store import repo

import yaml

log = logging.getLogger(__name__)


def load_annotator_config(path: str) -> AnnotatorSpec:
    """Load annotator YAML config and derive its content version."""
    with open(path) as f:
        cfg = yaml.safe_load(f)
    spec = AnnotatorSpec(
        id=cfg["id"], type=cfg["type"],
        target=Target(cfg["target"]), context=cfg.get("context", "self"),
        config=cfg)
    spec.version = compute_version(spec)
    return spec


def load_annotator_module(spec: AnnotatorSpec):
    """Import the module implementing the annotator (rule: annotate(); llm: build()+parse())."""
    return importlib.import_module(spec.config["module"])


def _has_annotation(conn, target_hash, annotator_id, version) -> bool:
    return conn.execute(
        "SELECT 1 FROM annotations WHERE target_hash=? AND annotator_id=? AND annotator_version=?",
        (target_hash, annotator_id, version)).fetchone() is not None


async def run_annotator(conn, spec: AnnotatorSpec, annotator_mod, *,
                        content_hashes=None, llm_profiles=None,
                        semaphore=None, job_id=None) -> dict:
    """Run `annotator_mod` over trajectories per `spec`. Returns {total, done, skipped, errors}."""
    repo.register_annotator(conn, id=spec.id, version=spec.version, config_hash=spec.version)
    if job_id:
        repo.create_job(conn, job_id=job_id, annotator_id=spec.id)

    if content_hashes is None:
        content_hashes = [t["content_hash"] for t in repo.list_trajectories(conn)]

    profile = None
    if spec.type == "llm":
        profiles = llm_profiles or {}
        profile = profiles.get(spec.config.get("profile"))
        if profile is None:
            raise ValueError(f"llm annotator {spec.id!r} needs profile "
                             f"{spec.config.get('profile')!r} in llm_profiles")

    total = done = skipped = 0
    errors: list[dict] = []

    for ch in content_hashes:
        traj = repo.get_trajectory(conn, ch)
        if traj is None:
            continue
        for idx, (th, unit, unit_range) in enumerate(enumerate_targets(traj, spec.target)):
            total += 1
            if _has_annotation(conn, th, spec.id, spec.version):
                skipped += 1
                continue
            try:
                ctx = project_context(traj.items, unit_range, spec.context)
                ih = compute_inputs_hash(unit, ctx)
                repo.link_annotation_target(
                    conn, target_hash=th, content_hash=ch,
                    target_type=spec.target.value, target_idx=idx)
                conn.commit()  # close the implicit txn before put_annotation's BEGIN IMMEDIATE

                if spec.type == "rule":
                    value = annotator_mod.annotate(unit, ctx)
                else:
                    messages = annotator_mod.build(unit, ctx)
                    content, _usage = await chat_completion(
                        profile, messages,
                        json_schema=getattr(annotator_mod, "SCHEMA", None),
                        semaphore=semaphore)
                    value = annotator_mod.parse(content)

                repo.put_annotation(
                    conn, target_hash=th, annotator_id=spec.id,
                    annotator_version=spec.version, value=value, inputs_hash=ih)
                done += 1
            except Exception as exc:  # noqa: BLE001 — one bad target must not abort the run
                log.exception("annotator %s failed on target %s", spec.id, th)
                errors.append({"content_hash": ch, "target_hash": th, "error": str(exc)})

    result = {"total": total, "done": done, "skipped": skipped, "errors": errors}
    if job_id:
        repo.update_job(conn, job_id, status="done", total=total, done=done,
                        errors=json.dumps(errors, ensure_ascii=False))
    return result
