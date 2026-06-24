import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listBatches, getDatasetStats, listAnnotators, uploadToDataset,
  createJob, getJob, computeMetrics, scanDataset,
  type Batch, type DatasetStats, type AnnotatorInfo, type JobInfo,
} from "../api";
import { ListView } from "./ListView";

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
            {Object.entries(stats.resolution).map(([k, v]) => (
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
            {Object.entries(stats.resolution).map(([k, v]) => (
              <span key={k} className="dim">{k}: {v}</span>
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
  const [result, setResult] = useState<{ count: number; errors_count: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const doUpload = useCallback(async (file: File) => {
    setUploading(true);
    setResult(null);
    try {
      const r = await uploadToDataset(datasetId, file);
      setResult({ count: r.count, errors_count: r.errors_count });
      onDone();
    } catch (e) {
      setResult({ count: 0, errors_count: -1 });
    } finally {
      setUploading(false);
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
        <span>Uploading…</span>
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
  const [activeJobs, setActiveJobs] = useState<JobInfo[]>([]);
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
