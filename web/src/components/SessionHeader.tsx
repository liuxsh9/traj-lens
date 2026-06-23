import type { Item, Annotation } from "../api";

interface Props {
  items: Item[];
  annotations: Annotation[];
  onBack: () => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

export function SessionHeader({ items, annotations, onBack, onExpandAll, onCollapseAll }: Props) {
  const turns = items.filter((it) => it.type === "message" && it.role === "user").length;
  const steps = new Set(items.filter((it) => it.step_id != null).map((it) => `${it.run_id}-${it.step_id}`)).size;
  const tools = items.filter((it) => it.type === "function_call").length;

  let pbCount = 0;
  let score: number | null = null;
  let resolution = "";
  for (const a of annotations) {
    let v: Record<string, unknown> = {};
    try { v = JSON.parse(a.value); } catch { /* skip */ }
    if (a.annotator_id === "pushback" && v.category && v.category !== "none") pbCount++;
    if (a.annotator_id === "resolution" && typeof v.resolution === "string") resolution = v.resolution;
  }

  // ponytail: compute score same way as backend — resolution baseline minus pushback penalty
  if (resolution === "resolved") score = Math.max(0, 100 - pbCount * 5);
  else if (resolution === "partially_resolved") score = Math.max(0, 50 - pbCount * 5);
  else if (resolution === "unresolved") score = 0;

  const scoreCls = score === null ? "score-na"
    : score >= 80 ? "score-good"
    : score >= 40 ? "score-mid"
    : "score-bad";

  // Extract topic annotation
  let title = "";
  let summary = "";
  let tags: string[] = [];
  for (const a of annotations) {
    if (a.annotator_id !== "topic") continue;
    let v: Record<string, unknown> = {};
    try { v = JSON.parse(a.value); } catch { /* skip */ }
    if (typeof v.title === "string") title = v.title;
    if (typeof v.summary === "string") summary = v.summary;
    if (Array.isArray(v.tags)) tags = v.tags as string[];
  }

  return (
    <div className="shdr" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <button className="btn" onClick={onBack}>← 返回列表</button>
        <span className={`score-badge ${scoreCls}`}>{score ?? "—"}</span>
        {title && <span style={{ fontWeight: 600, fontSize: 15 }}>{title}</span>}
        <span className="kv">{items.length} atoms · <b>{turns}</b> turns</span>
        <span className="kv"><b>{steps}</b> steps · <b>{tools}</b> tools</span>
        {pbCount > 0 && <span className="kv" style={{ color: "var(--warn)" }}>pushback <b>{pbCount}</b></span>}
        {resolution && (
          <span className={`chip-sm ${resolution === "resolved" ? "res-ok" : resolution === "unresolved" ? "res-fail" : "res-part"}`}>
            {resolution}
          </span>
        )}
        <div className="htools">
          <button className="btn" onClick={onExpandAll}>展开全部</button>
          <button className="btn" onClick={onCollapseAll}>折叠全部</button>
        </div>
      </div>
      {(summary || tags.length > 0) && (
        <div style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.6, padding: "0 4px" }}>
          {summary && <div>{summary}</div>}
          {tags.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
              {tags.map((t) => (
                <span key={t} className="chip-sm" style={{ fontSize: 10, background: "var(--border-light)" }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
