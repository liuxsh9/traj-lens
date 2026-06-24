import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listBatches, getDatasetStats, listAnnotators, uploadToDataset,
  createJob, getJob,
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

function AnnotatePanel({ datasetId }: { datasetId: string }) {
  const qc = useQueryClient();
  const { data: annotators = [] } = useQuery({
    queryKey: ["annotators"],
    queryFn: listAnnotators,
  });
  const [activeJobs, setActiveJobs] = useState<JobInfo[]>([]);
  const [running, setRunning] = useState(false);

  // Poll active jobs
  useEffect(() => {
    const pending = activeJobs.filter((j) => j.status === "pending");
    if (pending.length === 0) return;
    const timer = setInterval(async () => {
      const updated = await Promise.all(
        activeJobs.map((j) => (j.status === "pending" ? getJob(j.job_id) : j))
      );
      setActiveJobs(updated);
      if (updated.every((j) => j.status !== "pending")) {
        qc.invalidateQueries({ queryKey: ["stats", datasetId] });
        qc.invalidateQueries({ queryKey: ["trajectories"] });
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [activeJobs, datasetId, qc]);

  const runAll = async () => {
    setRunning(true);
    try {
      const jobs = await Promise.all(
        annotators.map((a) => createJob(a.path, datasetId))
      );
      setActiveJobs(jobs);
    } finally {
      setRunning(false);
    }
  };

  const runOne = async (a: AnnotatorInfo) => {
    const job = await createJob(a.path, datasetId);
    setActiveJobs((prev) => [...prev, job]);
  };

  return (
    <div className="annotate-panel">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button className="btn btn-sm" onClick={runAll} disabled={running || annotators.length === 0}>
          {running ? "Starting…" : "Run All Annotators"}
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
      {activeJobs.length > 0 && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", fontSize: 12 }}>
          {activeJobs.map((j) => (
            <span key={j.job_id} className="chip chip-sm">
              {j.annotator_id}:{" "}
              {j.status === "pending" ? (
                <span style={{ color: "var(--warn)" }}>running…{j.done != null ? ` ${j.done}/${j.total}` : ""}</span>
              ) : (
                <span style={{ color: "var(--good)" }}>done {j.done}/{j.total}</span>
              )}
            </span>
          ))}
        </div>
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
