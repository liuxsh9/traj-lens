import { useEffect, useState } from "react";
import { listTrajectories, type TrajSummary } from "./api";
import { TrajectoryView } from "./components/TrajectoryView";

export function App() {
  const [selected, setSelected] = useState<string | null>(null);
  if (selected) {
    return <TrajectoryView hash={selected} onBack={() => setSelected(null)} />;
  }
  return <ListView onOpen={setSelected} />;
}

function ListView({ onOpen }: { onOpen: (h: string) => void }) {
  const [rows, setRows] = useState<TrajSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listTrajectories().then(setRows).catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="page">
      <h1>traj-lens</h1>
      {err && <p className="error">{err}</p>}
      {!rows && !err && <p className="dim">loading…</p>}
      {rows && rows.length === 0 && (
        <p className="dim">
          no trajectories — ingest one with <code>trajlens ingest</code>
        </p>
      )}
      {rows && rows.length > 0 && (
        <table className="list">
          <thead>
            <tr>
              <th>content_hash</th>
              <th>items</th>
              <th>created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.content_hash} onClick={() => onOpen(r.content_hash)}>
                <td className="mono">{r.content_hash.slice(0, 16)}…</td>
                <td>{r.items_count}</td>
                <td className="dim">{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
