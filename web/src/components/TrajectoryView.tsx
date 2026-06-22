import { useEffect, useState } from "react";
import { getTrajectory, type Annotation, type Item, type Trajectory } from "../api";

export function TrajectoryView({ hash, onBack }: { hash: string; onBack: () => void }) {
  const [traj, setTraj] = useState<Trajectory | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getTrajectory(hash).then(setTraj).catch((e) => setErr(String(e)));
  }, [hash]);

  return (
    <div className="page">
      <button className="back" onClick={onBack}>
        ← back
      </button>
      {err && <p className="error">{err}</p>}
      {traj && (
        <>
          <h2 className="mono">
            {traj.content_hash.slice(0, 16)}…{" "}
            <span className="dim">· {traj.items.length} items</span>
          </h2>
          {traj.annotations && traj.annotations.length > 0 && (
            <div className="annotation-bar">
              {traj.annotations.map((a, i) => (
                <AnnotationChip key={i} ann={a} />
              ))}
            </div>
          )}
          <div className="transcript">
            {traj.items.map((it, i) => (
              <ItemRow key={i} item={it} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ItemRow({ item }: { item: Item }) {
  const group = item.run_id === null ? "user" : `r${item.run_id}·s${item.step_id}`;
  return (
    <div className={`row ty-${item.type}`}>
      <div className="gutter">
        <span className="ty">{label(item)}</span>
        <span className="grp">{group}</span>
      </div>
      <div className="body">{renderBody(item)}</div>
    </div>
  );
}

function AnnotationChip({ ann }: { ann: Annotation }) {
  let parsed: Record<string, unknown> = {};
  try { parsed = JSON.parse(ann.value); } catch { /* show raw */ }
  const summary = parsed.category
    ? `${parsed.category}${parsed.confidence ? ` (${(parsed.confidence as number).toFixed(1)})` : ""}`
    : parsed.detected !== undefined
      ? `loop:${parsed.detected ? "yes" : "no"}`
      : ann.value.slice(0, 30);
  return (
    <span className="chip" title={`${ann.annotator_id}@${ann.annotator_version.slice(0, 6)} — ${ann.value}`}>
      {ann.annotator_id}: {summary}
    </span>
  );
}

function label(it: Item): string {
  if (it.type === "message") return it.role ?? "message";
  if (it.type === "function_call") return `call · ${it.name}`;
  if (it.type === "function_call_output") return "tool_result";
  return "reasoning";
}

function renderBody(it: Item) {
  if (it.type === "message") return <div className="text">{it.content}</div>;
  if (it.type === "reasoning") return <div className="text dim">{it.content}</div>;
  if (it.type === "function_call") {
    return (
      <pre className="tool">
        {it.name}({it.arguments})
      </pre>
    );
  }
  if (it.type === "function_call_output") return <pre className="tool out">{it.output}</pre>;
  return null;
}
