"""Session-level metrics computed from trajectories and their annotations."""
import logging
from typing import Any, Callable

from trajlens.core.model import Trajectory
from trajlens.store import repo

log = logging.getLogger("trajlens.metrics")

MetricFn = Callable  # (traj: Trajectory, conn, anns: list[dict]) -> int | float | dict | None

# name -> (fn, version, depends_on)
REGISTRY: dict[str, tuple[MetricFn, str, list[str]]] = {}


def register(name: str, version: str, depends_on: list[str] | None = None):
    def _wrap(fn: MetricFn) -> MetricFn:
        REGISTRY[name] = (fn, version, depends_on or [])
        return fn
    return _wrap


def _effective_version(name: str, conn) -> str:
    """Compound version: metric code version + active dependency annotator versions.

    When an annotator is re-run with new config (new version), any metric that
    depends on it will get a different effective_version → cache miss → recompute.
    """
    _fn, version, deps = REGISTRY[name]
    if not deps:
        return version
    parts = [version]
    for dep_id in sorted(deps):
        row = conn.execute(
            "SELECT version FROM annotators WHERE id=? AND active=1", (dep_id,)
        ).fetchone()
        parts.append(f"{dep_id}:{row['version'][:8]}" if row else f"{dep_id}:_")
    return "|".join(parts)


def compute_metrics(conn, content_hash: str) -> dict[str, Any]:
    """Compute all registered metrics for one trajectory. Staleness-aware cache."""
    traj = repo.get_trajectory(conn, content_hash)
    if traj is None:
        return {}
    stored = repo.get_metrics_for_trajectory_full(conn, content_hash)
    results: dict[str, Any] = {}
    anns: list | None = None  # fetched once, lazily — only if a metric needs recompute
    for name, (fn, _ver, _deps) in REGISTRY.items():
        eff = _effective_version(name, conn)
        prev = stored.get(name)
        if prev is not None and prev["version"] == eff:
            results[name] = prev["value"]
            continue
        # stale or missing → (re)compute. Share one annotation fetch across all
        # metrics (3 builtins read the same set) instead of querying per-metric.
        if anns is None:
            anns = repo.get_annotations_for_trajectory(conn, content_hash)
        value = fn(traj, conn, anns)
        repo.put_metric(conn, content_hash=content_hash,
                        metric_id=name, value=value, version=eff)
        if prev is not None:
            log.info("refreshed stale %s for %s (was %s, now %s)",
                     name, content_hash[:12], prev["version"][:16], eff[:16])
        else:
            log.info("computed %s=%s for %s", name, value, content_hash[:12])
        results[name] = value
    return results


def compute_all(conn) -> int:
    """Compute metrics for every trajectory. Returns count processed."""
    trajs = repo.list_trajectories(conn)
    for t in trajs:
        compute_metrics(conn, t["content_hash"])
    return len(trajs)
