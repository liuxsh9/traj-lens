import { useRef, useCallback } from "react";
import type { Item } from "../api";

interface Props {
  items: Item[];
  pushbackIndices: Set<number>;
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
  flag: boolean;
  startIdx: number;
}

function aggregateByStep(items: Item[], pbSet: Set<number>): AggTick[] {
  const ticks: AggTick[] = [];
  let cur: AggTick | null = null;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const key = it.run_id === null ? `u-${i}` : `${it.run_id}-${it.step_id}`;
    if (!cur || cur.key !== key) {
      cur = { key, cls: tickClass(it), flag: false, startIdx: i };
      ticks.push(cur);
    }
    if (pbSet.has(i)) cur.flag = true;
  }
  return ticks;
}

export function Minimap({ items, pushbackIndices, viewportTop, viewportHeight, onClickTick }: Props) {
  const ticksRef = useRef<HTMLDivElement>(null);

  const aggregate = items.length > 200;
  const ticks = aggregate ? aggregateByStep(items, pushbackIndices) : null;
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
                {t.flag && <span className="flag" />}
              </div>
            ))
          : items.map((it, i) => (
              <div
                key={i}
                className={`tick ${tickClass(it)}`}
                onClick={() => handleClick(i)}
              >
                {pushbackIndices.has(i) && <span className="flag" />}
              </div>
            ))}
        <div className="viewbox" style={{ top: vbTopPct, height: vbHPct }} />
      </div>
    </div>
  );
}
