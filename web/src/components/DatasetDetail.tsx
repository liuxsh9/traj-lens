import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listBatches, getDatasetStats, listAnnotators, uploadToDataset,
  createJob, getJob, listDatasetJobs, computeMetrics, scanDataset,
  type Batch, type DatasetStats, type AnnotatorInfo, type JobInfo,
} from "../api";
import { ListView } from "./ListView";
import { useSticky } from "../useSticky";

interface Props {
  datasetId: string;
  datasetName: string;
  onBack: () => void;
  onOpen: (hash: string) => void;
}

const RES_COLORS: Record<string, string> = {
  resolved: "var(--good)", partially_resolved: "var(--warn)",
  unresolved: "var(--bad)", indeterminate: "var(--faint)",
};
const RES_ORDER = ["resolved", "partially_resolved", "unresolved", "indeterminate"];

function orderedResolution(resolution: Record<string, number>): [string, number][] {
  const known = RES_ORDER.filter((k) => k in resolution).map((k) => [k, resolution[k]] as [string, number]);
  const extra = Object.entries(resolution).filter(([k]) => !RES_ORDER.includes(k));
  return [...known, ...extra];
}

function StatsPanel({ stats }: { stats: DatasetStats }) {
  const resTotal = Object.values(stats.resolution).reduce((a, b) => a + b, 0) || 1;
  const metricKeys = ["success_score", "turn_count", "step_count", "tool_count", "pushback_count"];

  return (
    <div className="stats-panel">
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value">{stats.total}</div>
          <div className="dim" style={{ fontSize: 11 }}>trajectories</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.metrics.success_score?.avg ?? "—"}</div>
          <div className="dim" style={{ fontSize: 11 }}>avg score</div>
        </div>
        {stats.security && stats.security.scanned > 0 && (
          <div className="stat-card">
            <div className="stat-value" style={{ color: stats.security.introduced > 0 ? "var(--bad)" : "var(--good)" }}>
              {stats.security.introduced}
            </div>
            <div className="dim" style={{ fontSize: 11 }}>引入漏洞</div>
            <div className="dim" style={{ fontSize: 10, marginTop: 2 }}>
              {stats.security.affected} 轨迹 · 已扫 {stats.security.scanned}/{stats.total}
            </div>
          </div>
        )}
        <div className="stat-card" style={{ flex: 2 }}>
          <div className="dim" style={{ fontSize: 11, marginBottom: 4 }}>resolution</div>
          <div className="res-bar">
            {orderedResolution(stats.resolution).map(([k, v]) => (
              <div
                key={k}
                title={`${k}: ${v}`}
                style={{
                  width: `${(v / resTotal) * 100}%`,
                  background: RES_COLORS[k] || "var(--border)",
                  minWidth: v > 0 ? 4 : 0,
                }}
              />
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 3, fontSize: 10 }}>
            {orderedResolution(stats.resolution).map(([k, v]) => (
              <span key={k} className="dim">
                <span style={{ color: RES_COLORS[k] || "var(--faint)" }}>●</span> {k}: {v}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="stats-row">
        {metricKeys.map((key) => {
          const m = stats.metrics[key];
          if (!m || m.count === 0) return null;
          return (
            <div key={key} className="stat-card">
              <div className="dim" style={{ fontSize: 11 }}>{key.replace(/_/g, " ")}</div>
              <div style={{ fontSize: 12, marginTop: 2 }}>
                <span>avg <b>{m.avg}</b></span>
                <span className="dim" style={{ marginLeft: 8 }}>
                  {m.min}–{m.max}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {stats.top_tags.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {stats.top_tags.slice(0, 12).map((t) => (
            <span key={t.tag} className="chip chip-sm">
              {t.tag} <span className="dim">({t.count})</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Upload dropzone ─────────────────────────────────────────────── */

function UploadZone({ datasetId, onDone }: { datasetId: string; onDone: () => void }) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<JobInfo | null>(null);
  const [result, setResult] = useState<{ count: number; errors_count: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const doUpload = useCallback(async (file: File) => {
    setUploading(true);
    setResult(null);
    setProgress(null);
    try {
      const job = await uploadToDataset(datasetId, file);
      // Poll the background ingest job until it finishes (server streams the
      // file to disk and parses in a worker thread — never blocks).
      let j = job;
      let pollFails = 0;  // a saturated server (big import) drops the odd poll — don't abort on one
      while (j.status === "pending" && j.job_id) {
        await new Promise((r) => setTimeout(r, 1000));
        try { j = await getJob(j.job_id); pollFails = 0; }
        catch { if (++pollFails >= 5) j = { ...j, status: "error" }; }
        setProgress(j);
      }
      const errs = j.errors ? (() => { try { return JSON.parse(j.errors!).length; } catch { return 0; } })() : 0;
      setResult({ count: j.status === "error" ? 0 : (j.done ?? 0), errors_count: j.status === "error" ? -1 : errs });
      onDone();
    } catch {
      setResult({ count: 0, errors_count: -1 });
    } finally {
      setUploading(false);
      setProgress(null);
    }
  }, [datasetId, onDone]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) doUpload(file);
  }, [doUpload]);

  return (
    <div
      className={`upload-zone ${dragging ? "upload-zone-active" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => fileRef.current?.click()}
    >
      <input
        ref={fileRef}
        type="file"
        accept=".jsonl,.json"
        style={{ display: "none" }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) doUpload(f); }}
      />
      {uploading ? (
        <span>
          Importing…
          {progress && progress.total ? ` ${progress.done ?? 0}/${progress.total}` : ""}
        </span>
      ) : result ? (
        <span>
          {result.errors_count === -1
            ? "Upload failed"
            : `${result.count} imported${result.errors_count > 0 ? `, ${result.errors_count} errors` : ""}`
          }
          {" · "}click to upload another
        </span>
      ) : (
        <span>Drop JSONL file here or click to upload</span>
      )}
    </div>
  );
}

/* ── Annotator runner ─────────────────────────────────────────────── */

function jobErrCount(j: JobInfo): number {
  if (!j.errors) return 0;
  try { return JSON.parse(j.errors).length; } catch { return 0; }
}

// Human-readable status for one annotator job. "done 0/86" used to read as a
// failure; it's actually "86 already annotated, 0 new".
function jobLabel(j: JobInfo): { text: string; color: string } {
  if (j.status === "error") return { text: "failed", color: "var(--bad)" };
  if (j.status === "interrupted") {
    // server restarted mid-run; re-running is cheap (cache-aware) and resumes
    const prog = j.total ? ` at ${j.done ?? 0}/${j.total}` : "";
    return { text: `interrupted${prog} · re-run to resume`, color: "var(--warn)" };
  }
  if (j.status === "pending") {
    const prog = j.total ? ` ${j.done ?? 0}/${j.total}` : "";
    return { text: `running…${prog}`, color: "var(--warn)" };
  }
  const done = j.done ?? 0, skipped = j.skipped ?? 0, errs = jobErrCount(j);
  const parts: string[] = [];
  if (done > 0) parts.push(`${done} new`);
  if (skipped > 0) parts.push(`${skipped} cached`);
  if (errs > 0) parts.push(`${errs} errors`);
  if (parts.length === 0) parts.push("nothing to do");
  return { text: `✓ ${parts.join(" · ")}`, color: errs > 0 ? "var(--warn)" : "var(--good)" };
}

function metricsLabel(m: { status: string; computed?: number }): { text: string; color: string } {
  if (m.status === "pending") return { text: "running…", color: "var(--warn)" };
  if (m.status === "error") return { text: "failed", color: "var(--bad)" };
  return { text: `✓ ${m.computed ?? 0} computed`, color: "var(--good)" };
}

function AnnotatePanel({ datasetId }: { datasetId: string }) {
  const qc = useQueryClient();
  const { data: annotators = [] } = useQuery({
    queryKey: ["annotators"],
    queryFn: listAnnotators,
  });
  // Persist active jobs per-dataset (sessionStorage): opening a sample unmounts
  // this panel, but the backend jobs keep running. On remount the poll effect
  // below resumes from these job_ids and catches up jobs that finished while away.
  const [activeJobs, setActiveJobs] = useSticky<JobInfo[]>(`jobs:${datasetId}`, []);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<
    { status: "pending" | "done" | "error"; computed?: number } | null
  >(null);

  // Recompute metrics (annotation-independent ones aren't touched by the
  // annotator path; this fills/refreshes them) then refresh the views.
  const runMetrics = useCallback(async () => {
    setMetrics({ status: "pending" });
    try {
      const { computed } = await computeMetrics(datasetId);
      setMetrics({ status: "done", computed });
    } catch {
      setMetrics({ status: "error" });
    }
    qc.invalidateQueries({ queryKey: ["stats", datasetId] });
    qc.invalidateQueries({ queryKey: ["trajectories"] });
  }, [datasetId, qc]);

  // Hydrate from the server once on mount: jobs live in the DB (with dataset_id),
  // so a fresh tab/browser — where sessionStorage is empty — can still recover a
  // run that's in progress or just finished. Server is the source of truth; we
  // keep pending jobs (any age) plus anything finished in the last 10 min.
  useEffect(() => {
    let cancelled = false;
    listDatasetJobs(datasetId).then((jobs) => {
      if (cancelled) return;
      const RECENT_MS = 10 * 60 * 1000;
      const now = Date.now();
      const relevant = jobs.filter((j) =>
        j.status === "pending" ||
        (j.created_at && now - new Date(j.created_at).getTime() < RECENT_MS)
      );
      if (relevant.length === 0) return;
      // Merge, don't replace: a Run All started between this fetch and its
      // resolution put fresh jobs in state that the (older) server snapshot
      // lacks. Keep locally-known jobs; only seed server-only ones. The poll
      // effect refreshes pending jobs from the server anyway.
      setActiveJobs((prev) => {
        const known = new Set(prev.map((j) => j.job_id));
        const extra = relevant.filter((j) => !known.has(j.job_id));
        return extra.length > 0 ? [...prev, ...extra] : prev;
      });
    }).catch(() => { /* offline / not built — sticky state still paints */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  // Poll active jobs
  useEffect(() => {
    const pending = activeJobs.filter((j) => j.status === "pending" && j.job_id);
    if (pending.length === 0) return;
    const timer = setInterval(async () => {
      const updated = await Promise.all(
        activeJobs.map(async (j) => {
          if (j.status !== "pending" || !j.job_id) return j;
          try { return await getJob(j.job_id); }
          catch { return { ...j, status: "error" }; }
        })
      );
      setActiveJobs(updated);
      if (updated.every((j) => j.status !== "pending")) {
        // annotators recompute their own dependent metrics; this also fills
        // annotation-independent ones (tool_count, etc.) and shows the chip.
        await runMetrics();
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [activeJobs, runMetrics]);

  const runAll = async () => {
    setRunning(true);
    try {
      const results = await Promise.allSettled(
        annotators.map((a) => createJob(a.path, datasetId))
      );
      const jobs = results
        .filter((r): r is PromiseFulfilledResult<JobInfo> => r.status === "fulfilled")
        .map((r) => r.value);
      // semgrep batch scan rides along — it's a job too (skipped if not installed)
      try { jobs.push(await scanDataset(datasetId)); } catch { /* semgrep absent */ }
      if (jobs.length > 0) setActiveJobs(jobs);
    } finally {
      setRunning(false);
    }
  };

  const runScan = async () => {
    try {
      const job = await scanDataset(datasetId);
      setActiveJobs((prev) => [...prev.filter((j) => j.annotator_id !== "semgrep"), job]);
    } catch { /* semgrep not installed */ }
  };

  const runOne = async (a: AnnotatorInfo) => {
    try {
      const job = await createJob(a.path, datasetId);
      setActiveJobs((prev) => [...prev, job]);
    } catch { /* backend may reject if LLM profile missing */ }
  };

  return (
    <div className="annotate-panel">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button className="btn btn-sm" onClick={runAll} disabled={running || annotators.length === 0}>
          {running ? "Starting…" : "Run All Annotators"}
        </button>
        <button className="btn btn-sm btn-ghost" onClick={runMetrics}
          title="Fill missing & refresh stale metrics (e.g. success_score) without re-running annotators">
          Compute Metrics
        </button>
        <button className="btn btn-sm btn-ghost" onClick={runScan}
          title="Semgrep-scan every trajectory's code changes (cached; skips unchanged)">
          Scan Security
        </button>
        {annotators.map((a) => (
          <button
            key={a.id}
            className="btn btn-sm btn-ghost"
            onClick={() => runOne(a)}
            title={`${a.type} · target: ${a.target}`}
          >
            {a.id}
            <span className="dim" style={{ marginLeft: 4, fontSize: 10 }}>
              ({a.type})
            </span>
          </button>
        ))}
      </div>
      {(activeJobs.length > 0 || metrics) && (
        <>
          {activeJobs.some((j) => j.status === "pending") && (() => {
            // Aggregate progress across every annotator job in this "Run All".
            // A job only publishes its real `total` after its Phase-1 enumeration
            // finishes, so the denominator fills in over the first few polls.
            const sum = (k: "done" | "skipped") =>
              activeJobs.reduce((s, j) => s + (j[k] ?? 0), 0);
            const total = activeJobs.reduce((s, j) => s + (j.total ?? 0), 0);
            const finished = sum("done") + sum("skipped");
            const pct = total ? Math.round((finished / total) * 100) : 0;
            const pending = activeJobs.filter((j) => j.status === "pending").length;
            return (
              <div style={{ marginTop: 8 }}>
                <div className="dim" style={{ fontSize: 11 }}>
                  Annotating · {finished}/{total || "…"}{total ? ` (${pct}%)` : ""} · {pending} job{pending === 1 ? "" : "s"} left
                </div>
                <div className="res-bar" style={{ marginTop: 3 }}>
                  <div style={{ width: `${pct}%`, background: "var(--warn)", minWidth: pct > 0 ? 4 : 0 }} />
                </div>
              </div>
            );
          })()}
          {activeJobs.length > 0 && activeJobs.every((j) => j.status !== "pending") && (
            <div className="dim" style={{ marginTop: 8, fontSize: 12 }}>
              {(() => {
                const tot = (k: "done" | "skipped") =>
                  activeJobs.reduce((s, j) => s + (j[k] ?? 0), 0);
                const errs = activeJobs.reduce((s, j) => s + jobErrCount(j), 0);
                const failed = activeJobs.filter((j) => j.status === "error").length;
                const parts = [`${tot("done")} new`, `${tot("skipped")} cached`];
                if (errs > 0) parts.push(`${errs} errors`);
                if (failed > 0) parts.push(`${failed} jobs failed`);
                return `Annotators · ${parts.join(" · ")}`;
              })()}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", fontSize: 12 }}>
            {metrics && (() => {
              const { text, color } = metricsLabel(metrics);
              return (
                <span className="chip chip-sm">
                  metrics: <span style={{ color }}>{text}</span>
                </span>
              );
            })()}
            {activeJobs.map((j) => {
              const { text, color } = jobLabel(j);
              return (
                <span key={j.job_id} className="chip chip-sm">
                  {j.annotator_id}: <span style={{ color }}>{text}</span>
                </span>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────── */

export function DatasetDetail({ datasetId, datasetName, onBack, onOpen }: Props) {
  const qc = useQueryClient();
  const [showStats, setShowStats] = useState(true);
  const { data: batches = [] } = useQuery({
    queryKey: ["batches", datasetId],
    queryFn: () => listBatches(datasetId),
  });
  const { data: stats } = useQuery({
    queryKey: ["stats", datasetId],
    queryFn: () => getDatasetStats(datasetId),
  });

  const refreshAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["batches", datasetId] });
    qc.invalidateQueries({ queryKey: ["stats", datasetId] });
    qc.invalidateQueries({ queryKey: ["trajectories"] });
  }, [qc, datasetId]);

  return (
    <div className="page">
      <div className="page-header">
        <button className="btn btn-sm btn-ghost" onClick={onBack}>
          ← Datasets
        </button>
        <h2 style={{ margin: 0 }}>{datasetName}</h2>
        <button
          className="btn btn-sm btn-ghost"
          onClick={() => setShowStats((s) => !s)}
        >
          {showStats ? "▾ Stats" : "▸ Stats"}
        </button>
      </div>

      {showStats && stats && <StatsPanel stats={stats} />}

      <UploadZone datasetId={datasetId} onDone={refreshAll} />

      <AnnotatePanel datasetId={datasetId} />

      {batches.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {batches.map((b: Batch) => (
            <span key={b.id} className="chip chip-sm">
              {b.format} · {b.traj_count} · {b.name || b.id.slice(0, 8)}
            </span>
          ))}
        </div>
      )}

      <ListView onOpen={onOpen} datasetId={datasetId} />
    </div>
  );
}
