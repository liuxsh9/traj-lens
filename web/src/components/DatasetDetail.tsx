import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listBatches, getDatasetStats, type Batch, type DatasetStats } from "../api";
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

export function DatasetDetail({ datasetId, datasetName, onBack, onOpen }: Props) {
  const [showStats, setShowStats] = useState(true);
  const { data: batches = [] } = useQuery({
    queryKey: ["batches", datasetId],
    queryFn: () => listBatches(datasetId),
  });
  const { data: stats } = useQuery({
    queryKey: ["stats", datasetId],
    queryFn: () => getDatasetStats(datasetId),
  });

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
