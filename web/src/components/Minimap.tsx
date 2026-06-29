import { useRef, useCallback } from "react";
import type { Item } from "../api";
import { markerForItem, minimapMarkerClass, type StepErrorMarker } from "./errorMarkers";
import { minimapLoopClass, stepKey, type LoopEpisode } from "./loopMarkers";

interface Props {
  items: Item[];
  pushbackIndices: Set<number>;
  errorMarkers: Map<string, StepErrorMarker>;
  loopEpisodes: LoopEpisode[];
  viewportTop: number;
  viewportHeight: number;
  onClickTick: (index: number) => void;
}

function tickClass(it: Item): string {
  if (it.type === "message") {
    if (it.role === "user") return "t-user";
    if (it.role === "system" || it.role === "developer") return "t-sys";
    return "t-asst";
  }
  if (it.type === "reasoning") return "t-reason";
  if (it.type === "function_call") return "t-call";
  return "t-tool";
}

interface AggTick {
  key: string;
  cls: string;
  flagClass: string;
  loopClass: string;
  startIdx: number;
}

function aggregateByStep(
  items: Item[],
  pbSet: Set<number>,
  errorMarkers: Map<string, StepErrorMarker>,
  loopEpisodes: LoopEpisode[],
): AggTick[] {
  const ticks: AggTick[] = [];
  let cur: AggTick | null = null;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const key = it.run_id === null ? `u-${i}` : `${it.run_id}-${it.step_id}`;
    if (!cur || cur.key !== key) {
      cur = { key, cls: tickClass(it), flagClass: "", loopClass: "", startIdx: i };
      ticks.push(cur);
    }
    const errClass = minimapMarkerClass(markerForItem(it, errorMarkers));
    if (errClass) cur.flagClass = errClass;
    else if (!cur.flagClass && pbSet.has(i)) cur.flagClass = "flag-pushback";
    if (it.run_id != null && it.step_id != null) {
      cur.loopClass ||= minimapLoopClass(stepKey(it.run_id, it.step_id), loopEpisodes);
    }
  }
  return ticks;
}

export function Minimap({ items, pushbackIndices, errorMarkers, loopEpisodes, viewportTop, viewportHeight, onClickTick }: Props) {
  const ticksRef = useRef<HTMLDivElement>(null);

  const aggregate = items.length > 200;
  const ticks = aggregate ? aggregateByStep(items, pushbackIndices, errorMarkers, loopEpisodes) : null;
  const count = ticks ? ticks.length : items.length;
  // ponytail: no gap when dense (>80 ticks), 1px otherwise
  const gap = count > 80 ? 0 : 1;

  const handleClick = useCallback((idx: number) => {
    onClickTick(idx);
  }, [onClickTick]);

  // viewbox is positioned as % of the ticks container
  const vbTopPct = `${(viewportTop * 100).toFixed(1)}%`;
  const vbHPct = `${(Math.max(0.03, viewportHeight) * 100).toFixed(1)}%`;

  return (
    <div className="mini">
      <div className="ticks" ref={ticksRef} style={{ gap }}>
        {ticks
          ? ticks.map((t) => (
              <div
                key={t.key}
                className={`tick ${t.cls}`}
                onClick={() => handleClick(t.startIdx)}
              >
                {t.flagClass && <span className={`flag ${t.flagClass}`} />}
                {t.loopClass && <span className={`loop-mini ${t.loopClass}`} />}
              </div>
            ))
          : items.map((it, i) => (
              <div
                key={i}
                className={`tick ${tickClass(it)}`}
                onClick={() => handleClick(i)}
              >
                {(() => {
                  const flagClass = minimapMarkerClass(markerForItem(it, errorMarkers))
                    || (pushbackIndices.has(i) ? "flag-pushback" : "");
                  const loopClass = it.run_id != null && it.step_id != null
                    ? minimapLoopClass(stepKey(it.run_id, it.step_id), loopEpisodes)
                    : "";
                  return (
                    <>
                      {flagClass ? <span className={`flag ${flagClass}`} /> : null}
                      {loopClass ? <span className={`loop-mini ${loopClass}`} /> : null}
                    </>
                  );
                })()}
              </div>
            ))}
        <div className="viewbox" style={{ top: vbTopPct, height: vbHPct }} />
      </div>
    </div>
  );
}
