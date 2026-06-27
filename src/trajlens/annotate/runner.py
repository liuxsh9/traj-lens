"""Annotation runner — drives a rule or LLM annotator over stored trajectories.

Cache-aware: skips (target, annotator, version) triples already in the DB, so
re-runs after a version bump only fill the gaps. Errors are per-target, logged,
and recorded on the job; one bad target never aborts the run.
"""
import asyncio
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
                        job_id=None, force: bool = False) -> dict:
    """Run `annotator_mod` over trajectories per `spec`. Returns {total, done, skipped, errors}.

    LLM annotators run concurrently (bounded by the rate limiter in llm_client).
    Rule annotators stay serial (fast enough, simpler DB access).
    """
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
    rule_progress_interval = 50

    # Phase 1: enumerate all work items, do cache check + DB linking (serial, fast)
    pending: list[tuple[str, str, list, list, str]] = []  # (ch, th, unit, messages_or_ctx, ih)
    for ch in content_hashes:
        traj = repo.get_trajectory(conn, ch)
        if traj is None:
            continue
        for idx, (th, unit, unit_range) in enumerate(enumerate_targets(traj, spec.target)):
            total += 1
            if not force and _has_annotation(conn, th, spec.id, spec.version):
                skipped += 1
                continue
            try:
                ctx = project_context(traj.items, unit_range, spec.context)
                ih = compute_inputs_hash(unit, ctx)
                repo.link_annotation_target(
                    conn, target_hash=th, content_hash=ch,
                    target_type=spec.target.value, target_idx=idx)
                conn.commit()

                if spec.type == "rule":
                    # rules are CPU-only, run inline
                    value = annotator_mod.annotate(unit, ctx)
                    repo.put_annotation(
                        conn, target_hash=th, annotator_id=spec.id,
                        annotator_version=spec.version, value=value, inputs_hash=ih)
                    done += 1
                    if job_id and total % rule_progress_interval == 0:
                        repo.update_job(conn, job_id, total=total, done=done, skipped=skipped)
                else:
                    messages = annotator_mod.build(unit, ctx)
                    pending.append((ch, th, unit, messages, ih))
            except Exception as exc:  # noqa: BLE001
                log.exception("annotator %s failed on target %s", spec.id, th)
                errors.append({"content_hash": ch, "target_hash": th, "error": str(exc)})

    # publish the real denominator now that enumeration is done, so the UI
    # shows "running… 0/86" instead of "running…" with no total.
    if job_id:
        repo.update_job(conn, job_id, total=total, skipped=skipped)

    # Phase 2: fire LLM calls concurrently; process each as it completes so the
    # job's `done` count tracks real progress (the wait is in the LLM calls, not
    # the DB writes — updating only after gather() shows 0/N for minutes).
    # ponytail: rate limiter in llm_client throttles concurrency; as_completed
    # just changes when we observe each result, not how many run at once.
    if pending:
        log.info("annotator %s: launching %d LLM calls concurrently", spec.id, len(pending))
        by_messages = {id(m): (ch, th, unit, ih) for (ch, th, unit, m, ih) in pending}

        async def _call_llm(messages):
            content, _usage = await chat_completion(
                profile, messages,
                json_schema=getattr(annotator_mod, "SCHEMA", None))
            return id(messages), content

        progress_interval = max(1, len(pending) // 20)
        completed = 0
        for fut in asyncio.as_completed([_call_llm(m) for (_, _, _, m, _) in pending]):
            completed += 1
            try:
                msg_id, content = await fut
                ch, th, unit, ih = by_messages[msg_id]
                value = annotator_mod.parse(content)
                repo.put_annotation(
                    conn, target_hash=th, annotator_id=spec.id,
                    annotator_version=spec.version, value=value, inputs_hash=ih)
                done += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("annotator %s LLM/parse failed: %s", spec.id, exc)
                errors.append({"error": str(exc)})
            if job_id and completed % progress_interval == 0:
                repo.update_job(conn, job_id, done=done)

    # mark the job done BEFORE the metric recompute below — recompute walks every
    # trajectory (CPU+DB heavy, minutes at scale) and must not block the UI from
    # seeing the annotations that are already written.
    result = {"total": total, "done": done, "skipped": skipped, "errors": errors}
    if job_id:
        repo.update_job(conn, job_id, status="done", total=total, done=done,
                        skipped=skipped, errors=json.dumps(errors, ensure_ascii=False))

    # ponytail: invalidate cached metrics that depend on this annotator, then
    # recompute so the metrics table is repopulated (web read path has no lazy
    # compute — empty table renders as 0). compute_metrics is cache-aware, so
    # this only does work for the metrics we just invalidated.
    if done > 0:
        _invalidate_dependent_metrics(conn, spec.id, content_hashes)
        _recompute_metrics(conn, content_hashes)

    return result


def _recompute_metrics(conn, content_hashes):
    """Recompute metrics for the given trajectories (cache-aware: only fills
    missing/invalidated entries)."""
    try:
        from trajlens.metrics import compute_metrics
        import trajlens.metrics.builtins  # noqa: F401 — ensure registered
        for ch in content_hashes:
            compute_metrics(conn, ch)
    except Exception:
        log.debug("metric recompute skipped (metrics module not available)")


def _invalidate_dependent_metrics(conn, annotator_id: str, content_hashes=None):
    """Delete cached metrics that depend on the given annotator."""
    try:
        from trajlens.metrics import REGISTRY
        import trajlens.metrics.builtins  # noqa: F401 — ensure registered
        to_delete = [name for name, (_fn, _ver, deps) in REGISTRY.items()
                     if annotator_id in deps]
        if to_delete:
            metric_placeholders = ",".join("?" * len(to_delete))
            params = list(to_delete)
            where = f"metric_id IN ({metric_placeholders})"
            if content_hashes is not None:
                hashes = list(content_hashes)
                if not hashes:
                    return
                hash_placeholders = ",".join("?" * len(hashes))
                where += f" AND content_hash IN ({hash_placeholders})"
                params.extend(hashes)
            n = conn.execute(f"DELETE FROM metrics WHERE {where}", params).rowcount
            conn.commit()
            log.info("invalidated %d cached metrics (%s) after %s run",
                     n, ", ".join(to_delete), annotator_id)
    except Exception:
        log.debug("metric invalidation skipped (metrics module not available)")
