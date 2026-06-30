import { type Item, type Annotation, groupByTurns, groupBySteps, parseAnnotationValue } from "../api";
import { ItemTranscript } from "./ItemTranscript";
import { markerBadgeText, stepMarkerKey, type StepErrorMarker } from "./errorMarkers";
import {
  loopEpisodeLabel,
  loopEpisodeTitle,
  loopLabelMarkersForStep,
  loopMarkersForStep,
  loopStepRole,
  type LoopEpisode,
  type LoopStepMarker,
} from "./loopMarkers";

interface Props {
  items: Item[];
  annotations: Annotation[];
  errorMarkers: Map<string, StepErrorMarker>;
  loopEpisodes: LoopEpisode[];
  expanded: Set<string>;
  onToggle: (key: string) => void;
}

function stepKey(runId: number, stepId: number) {
  return `${runId}-${stepId}`;
}

function summarizeStep(items: Item[]): string {
  // ponytail: tool chain first — most useful collapsed summary
  const tools = items.filter((it) => it.type === "function_call").map((it) => it.name);
  if (tools.length) return tools.join(" → ");
  const reasoning = items.find((it) => it.type === "reasoning");
  if (reasoning?.content) return reasoning.content.slice(0, 80).replace(/\n/g, " ");
  const asst = items.find((it) => it.type === "message" && it.role === "assistant");
  if (asst?.content) return asst.content.slice(0, 80).replace(/\n/g, " ");
  return "…";
}

function toolFootprint(items: Item[]): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  for (const it of items) {
    if (it.type === "function_call" && it.name && !seen.has(it.name)) {
      seen.add(it.name);
      names.push(it.name);
    }
  }
  return names;
}

function markerTooltip(marker: StepErrorMarker | null): string {
  if (!marker) return "";
  const parts: string[] = [];
  if (marker.hasError) {
    parts.push(marker.errorSummary ? `error: ${marker.errorSummary}` : "error");
  }
  if (marker.hasRecovery && marker.recoveredFromKey) {
    parts.push(`recovers ${marker.recoveredFromKey}${marker.recoverySummary ? `: ${marker.recoverySummary}` : ""}`);
  } else if (marker.hasRecovery) {
    parts.push("recovery action");
  }
  return parts.join(" | ");
}

function loopMarkerTooltip(marker: LoopStepMarker): string {
  return loopEpisodeTitle(marker.episode);
}

// Build a map: user-message-index → pushback annotation (for active pushbacks only)
// ponytail: skip target_idx=0 — first user message can't be pushback (no prior agent action)
function buildPushbackMap(annotations: Annotation[]): Map<number, Annotation> {
  const map = new Map<number, Annotation>();
  for (const a of annotations) {
    if (a.annotator_id !== "pushback" || a.target_type !== "user_turn") continue;
    if (a.target_idx == null || a.target_idx === 0) continue;
    const v = parseAnnotationValue(a);
    if (v.category && v.category !== "none") {
      map.set(a.target_idx, a);
    }
  }
  return map;
}

function buildIntentMap(annotations: Annotation[]): Map<number, string> {
  const map = new Map<number, string>();
  for (const a of annotations) {
    if (a.annotator_id !== "intent" || a.target_type !== "user_turn") continue;
    if (a.target_idx == null) continue;
    const v = parseAnnotationValue(a);
    if (v.intent && v.intent !== "other") map.set(a.target_idx, v.intent as string);
  }
  return map;
}

// ── UserCard (expandable: header preview + body) ──
function UserCard({ items, id, pushback, intent, isExpanded, onToggle }: {
  items: Item[]; id: string; pushback: Annotation | null; intent: string | null; isExpanded: boolean; onToggle: () => void;
}) {
  const msg = items.find((it) => it.type === "message" && it.role === "user")
           ?? items.find((it) => it.type === "message");
  const content = msg?.content ?? "";
  const pb = pushback;
  const isPush = pb !== null;
  const preview = content.replace(/\n/g, " ").slice(0, 120);

  let pbLabel = "";
  if (pb) {
    const v = parseAnnotationValue(pb);
    pbLabel = `pushback · ${v.category}`;
  }

  return (
    <div className={`card ${isPush ? "push-card" : "user-card"}`}>
      <div className="chd" onClick={onToggle}>
        <span className="actor">🧑</span>
        <span className="summ">{preview || "…"}</span>
        <span className="meta">
          {intent && <span className="chip-sm" style={{ background: "var(--border-light)", fontSize: 10 }}>{intent}</span>}
          {isPush && <span className="chip-sm res-fail">{pbLabel}</span>}
          <span className="caret">{isExpanded ? "▾" : "▸"}</span>
        </span>
      </div>
      {isExpanded && (
        <div className="exp">
          <ItemTranscript items={items} />
        </div>
      )}
    </div>
  );
}

// ── StepCard (collapsible) ──
function StepCard({
  items,
  runId,
  stepId,
  marker,
  loopMarkers,
  isExpanded,
  onToggle,
}: {
  items: Item[];
  runId: number;
  stepId: number;
  marker: StepErrorMarker | null;
  loopMarkers: LoopStepMarker[];
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const tools = toolFootprint(items);
  const summary = tools.length
    ? tools.join(" → ")
    : summarizeStep(items);
  const markerClass = marker
    ? marker.hasError && marker.hasRecovery ? "error-step error-recovered"
      : marker.hasError ? "error-step error"
      : marker.hasRecovery ? "recovery-step"
      : ""
    : "";
  const markerTitle = markerTooltip(marker);
  const stepKeyValue = stepKey(runId, stepId);
  const labelLoops = loopLabelMarkersForStep(stepKeyValue, loopMarkers.map((m) => m.episode));
  const visibleLoopLanes = loopMarkers.slice(0, 3);
  const extraLoopCount = Math.max(0, loopMarkers.length - visibleLoopLanes.length);

  return (
    <div className={`card ${markerClass} ${loopMarkers.length ? "loop-step" : ""}`}>
      {visibleLoopLanes.length > 0 && (
        <div className="loop-lanes" aria-hidden="true">
          {visibleLoopLanes.map((lm, laneIdx) => (
            <span
              key={`${lm.episode.id}-${laneIdx}`}
              className={`loop-lane loop-${loopStepRole(lm.episode, stepKeyValue) ?? lm.role}`}
              style={{ left: 8 + laneIdx * 5 }}
              title={loopMarkerTooltip(lm)}
            />
          ))}
          {extraLoopCount > 0 && <span className="loop-lane-more">+{extraLoopCount}</span>}
        </div>
      )}
      <div className="chd" onClick={onToggle}>
        <span className="actor">🤖</span>
        <span className="summ">{summary}</span>
        <span className="meta">
          {labelLoops.slice(0, 2).map((lm) => (
            <span
              key={lm.episode.id}
              className="chip-sm loop-chip"
              title={loopMarkerTooltip(lm)}
            >
              LOOP · {loopEpisodeLabel(lm.episode)}
            </span>
          ))}
          {labelLoops.length > 2 && (
            <span className="chip-sm loop-chip" title={`${labelLoops.length} loops start here`}>
              +{labelLoops.length - 2}
            </span>
          )}
          {marker && (
            <span
              className={`chip-sm err-chip ${markerClass}`}
              title={markerTitle}
            >
              {markerBadgeText(marker)}
            </span>
          )}
          <span className="caret">{isExpanded ? "▾" : "▸"}</span>
        </span>
      </div>
      {isExpanded && (
        <div className="exp">
          <ItemTranscript items={items} />
        </div>
      )}
    </div>
  );
}

// ── RunGroup (collapsible wrapper around steps) ──
function RunGroup({
  runId,
  items,
  errorMarkers,
  loopEpisodes,
  expanded,
  onToggle,
}: {
  runId: number;
  items: Item[];
  errorMarkers: Map<string, StepErrorMarker>;
  loopEpisodes: LoopEpisode[];
  expanded: Set<string>;
  onToggle: (key: string) => void;
}) {
  const steps = groupBySteps(items);
  const tools = toolFootprint(items);
  const isRunExpanded = expanded.has(`run-${runId}`);

  return (
    <div className="run-group">
      <div className="run-header" onClick={() => onToggle(`run-${runId}`)}>
        <span className="caret">{isRunExpanded ? "▾" : "▸"}</span>
        <span>Run {runId}</span>
        <span>· <b>{steps.length}</b> steps</span>
        {tools.length > 0 && (
          <span className="dim" style={{ marginLeft: 4 }}>{tools.join(" → ")}</span>
        )}
      </div>
      {isRunExpanded && (
        <div className="run-steps">
          {steps.map((sg) => {
            const k = stepKey(sg.run_id, sg.step_id);
            const marker = errorMarkers.get(stepMarkerKey(sg.run_id, sg.step_id)) ?? null;
            const loopMarkers = loopMarkersForStep(k, loopEpisodes);
            return (
              <StepCard
                key={k}
                items={sg.items}
                runId={sg.run_id}
                stepId={sg.step_id}
                marker={marker}
                loopMarkers={loopMarkers}
                isExpanded={expanded.has(k)}
                onToggle={() => onToggle(k)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Pinned first-user card (top bookend) ──
export function PinnedUser({ items, annotations, isExpanded, onToggle }: {
  items: Item[]; annotations: Annotation[]; isExpanded: boolean; onToggle: () => void;
}) {
  const msg = items.find((it) => it.type === "message" && it.role === "user")
           ?? items.find((it) => it.type === "message");
  const content = msg?.content ?? "";
  const preview = content.replace(/\n/g, " ").slice(0, 140);

  return (
    <div className="pinned user-card">
      <div className="chd" onClick={onToggle}>
        <span className="actor">🧑</span>
        <span className="summ">{preview || "…"}</span>
        <span className="meta">
          <span className="chip-sm" style={{ fontSize: 10, color: "var(--faint)" }}>TASK</span>
          <span className="caret">{isExpanded ? "▾" : "▸"}</span>
        </span>
      </div>
      {isExpanded && (
        <div className="exp">
          <ItemTranscript items={items} />
        </div>
      )}
    </div>
  );
}

// ── Pinned last-assistant reply (bottom bookend) ──
export function PinnedReply({ items, isExpanded, onToggle }: {
  items: Item[]; isExpanded: boolean; onToggle: () => void;
}) {
  // Find last assistant message
  const msg = [...items].reverse().find((it) => it.type === "message" && it.role === "assistant");
  const content = msg?.content ?? "";
  const preview = content.replace(/\n/g, " ").slice(0, 140);
  if (!msg) return null;

  return (
    <div className="pinned reply-card">
      <div className="chd" onClick={onToggle}>
        <span className="actor">🤖</span>
        <span className="summ">{preview || "…"}</span>
        <span className="meta">
          <span className="chip-sm" style={{ fontSize: 10, color: "var(--faint)" }}>REPLY</span>
          <span className="caret">{isExpanded ? "▾" : "▸"}</span>
        </span>
      </div>
      {isExpanded && (
        <div className="ubody">{content}</div>
      )}
    </div>
  );
}

// ── CardStack (all turns) ──
export function CardStack({ items, annotations, errorMarkers, loopEpisodes, expanded, onToggle }: Props) {
  const turns = groupByTurns(items);
  const pbMap = buildPushbackMap(annotations);
  const intentMap = buildIntentMap(annotations);

  // Count user messages per turn group to map to backend target_idx
  // Backend target_idx counts individual user messages across the trajectory
  let userMsgCounter = 0;
  return (
    <>
      {turns.map((t, i) => {
        if (t.kind === "user") {
          const uk = `u-${i}`;
          // Find pushback for any user message in this turn group
          const userMsgs = t.items.filter((it) => it.type === "message" && it.role === "user");
          let turnPb: Annotation | null = null;
          let turnIntent: string | null = null;
          const startIdx = userMsgCounter;
          for (let j = 0; j < userMsgs.length; j++) {
            const pb = pbMap.get(startIdx + j);
            if (pb) turnPb = pb;
            const intent = intentMap.get(startIdx + j);
            if (intent) turnIntent = intent;
          }
          userMsgCounter += userMsgs.length;
          return (
            <UserCard
              key={uk}
              id={uk}
              pushback={turnPb}
              intent={turnIntent}
              items={t.items}
              isExpanded={expanded.has(uk)}
              onToggle={() => onToggle(uk)}
            />
          );
        }
        return (
          <RunGroup
            key={`r-${t.run_id}`}
            runId={t.run_id!}
            items={t.items}
            errorMarkers={errorMarkers}
            loopEpisodes={loopEpisodes}
            expanded={expanded}
            onToggle={onToggle}
          />
        );
      })}
    </>
  );
}
