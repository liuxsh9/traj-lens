import { ACCEPT_DISPLAY, acceptSignalsZh, type AcceptLikelihood,
  type Item, type Annotation } from "../api";

interface Props {
  items: Item[];
  annotations: Annotation[];
  score: number | null;  // backend-computed overall_score — single source of truth
  onBack: () => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

export function SessionHeader({ items, annotations, score, onBack, onExpandAll, onCollapseAll }: Props) {
  const turns = items.filter((it) => it.type === "message" && it.role === "user").length;
  const steps = new Set(items.filter((it) => it.step_id != null).map((it) => `${it.run_id}-${it.step_id}`)).size;
  const tools = items.filter((it) => it.type === "function_call").length;

  let pbCount = 0;
  let resolution = "";
  let errorSteps = 0;
  let recoveredSteps = 0;
  let interrupted = false;
  let interruptReason = "";
  let acceptance = "";          // change_acceptance likelihood (empty = no code edited)
  let acceptSignals: string[] = [];
  let acceptEdits = 0;
  for (const a of annotations) {
    let v: Record<string, unknown> = {};
    try { v = JSON.parse(a.value); } catch { /* skip */ }
    // first user turn (idx 0) is the initial request, never pushback — match backend
    if (a.annotator_id === "pushback" && a.target_idx !== 0 && v.category && v.category !== "none") pbCount++;
    if (a.annotator_id === "resolution" && typeof v.resolution === "string") resolution = v.resolution;
    if (a.annotator_id === "error_recovery" && v.has_error) {
      errorSteps++;
      if (v.recovered === true) recoveredSteps++;
    }
    if (a.annotator_id === "hard_interruption" && v.interrupted) {
      interrupted = true;
      interruptReason = (v.reason as string) ?? "";
    }
    if (a.annotator_id === "change_acceptance" && !v.no_edits && typeof v.likelihood === "string") {
      acceptance = v.likelihood;
      acceptSignals = Array.isArray(v.signals) ? (v.signals as string[]) : [];
      acceptEdits = typeof v.edit_count === "number" ? v.edit_count : 0;
    }
  }

  const acceptDisp = acceptance ? ACCEPT_DISPLAY[acceptance as AcceptLikelihood] : null;
  const acceptEvidenceZh = acceptSignalsZh(acceptSignals);

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

  // Stale: an annotation run by a version older than the annotator's active one.
  // One session-level badge; tooltip lists which annotators lag (id v_old→v_new).
  const staleIds = new Set<string>();
  const staleDetail: string[] = [];
  for (const a of annotations) {
    if (a.active_version && a.annotator_version !== a.active_version && !staleIds.has(a.annotator_id)) {
      staleIds.add(a.annotator_id);
      staleDetail.push(`${a.annotator_id} ${a.annotator_version.slice(0, 8)}→${a.active_version.slice(0, 8)}`);
    }
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
          <span className={`chip-sm ${resolution === "resolved" ? "res-ok" : resolution === "unresolved" ? "res-fail" : resolution === "indeterminate" ? "res-ind" : "res-part"}`}>
            {resolution}
          </span>
        )}
        {errorSteps > 0 && (
          <span className="kv" title={`${recoveredSteps}/${errorSteps} errors recovered`}>
            errors <b>{errorSteps}</b> · recovered <b>{recoveredSteps}</b>
          </span>
        )}
        {interrupted && (
          <span className="chip-sm res-fail" title={interruptReason}>interrupted</span>
        )}
        {acceptance && acceptDisp && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span className="chip-sm" style={{ background: acceptDisp.color, color: "#fff" }}>
              {acceptDisp.icon} 修改采纳可能性: {acceptDisp.zh}
            </span>
            <span className="faint" style={{ fontSize: 11 }}>
              {acceptEvidenceZh.length
                ? `依据: ${acceptEvidenceZh.join(" · ")} · ${acceptEdits} 处编辑`
                : `改了 ${acceptEdits} 处，无 git/测试信号`}
            </span>
          </span>
        )}
        {staleIds.size > 0 && (
          <span className="chip-sm" style={{ background: "var(--warn)", color: "#fff" }}
            title={`有新版标注器可重跑：\n${staleDetail.join("\n")}`}>
            ⟳ {staleIds.size} 陈旧
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
