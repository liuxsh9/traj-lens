import type { CodeChange, Item, LoopEpisode as ApiLoopEpisode } from "../api";

export const LOOP_GAP_STEPS = 4;

export type LoopStepRole = "start" | "trigger" | "middle" | "end" | "single";

export interface LoopEditPoint {
  key: string;
  runId: number;
  stepId: number;
  itemIdx: number;
}

export interface LoopEpisode {
  id: string;
  path: string;
  editCount: number;
  startKey: string;
  triggerKey: string;
  endKey: string;
  startIdx: number;
  endIdx: number;
  intervalKeys: string[];
  points: LoopEditPoint[];
}

export interface LoopStepMarker {
  episode: LoopEpisode;
  role: LoopStepRole;
}

export function stepKey(runId: number, stepId: number): string {
  return `${runId}-${stepId}`;
}

function enumerateStepOrder(items: Item[]): { keys: string[]; order: Map<string, number> } {
  const keys: string[] = [];
  const order = new Map<string, number>();
  let current: string | null = null;
  for (const it of items) {
    if (it.run_id == null || it.step_id == null) {
      current = null;
      continue;
    }
    const key = stepKey(it.run_id, it.step_id);
    if (key !== current) {
      current = key;
      if (!order.has(key)) {
        order.set(key, keys.length);
        keys.push(key);
      }
    }
  }
  return { keys, order };
}

function pathLabel(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? path;
}

export function loopEpisodeLabel(ep: LoopEpisode): string {
  return `${pathLabel(ep.path)} ×${ep.editCount}`;
}

export function loopEpisodeTitle(ep: LoopEpisode): string {
  return `loop: ${ep.path}\nsteps ${ep.startKey} → ${ep.endKey}\nconfirmed at ${ep.triggerKey}\n${ep.editCount} edits`;
}

export function buildLoopEpisodes(
  changes: CodeChange[] = [],
  items: Item[] = [],
  gapSteps = LOOP_GAP_STEPS,
): LoopEpisode[] {
  const { keys, order } = enumerateStepOrder(items);
  const byPath = new Map<string, LoopEditPoint[]>();
  const seenStepsByPath = new Map<string, Set<string>>();

  for (const c of changes) {
    if ((c.op !== "create" && c.op !== "edit") || !c.path) continue;
    if (c.run_id == null || c.step_id == null) continue;
    const key = stepKey(c.run_id, c.step_id);
    const seenSteps = seenStepsByPath.get(c.path) ?? new Set<string>();
    if (seenSteps.has(key)) continue;
    seenSteps.add(key);
    seenStepsByPath.set(c.path, seenSteps);
    const point: LoopEditPoint = {
      key,
      runId: c.run_id,
      stepId: c.step_id,
      itemIdx: c.item_idx,
    };
    const arr = byPath.get(c.path) ?? [];
    arr.push(point);
    byPath.set(c.path, arr);
  }

  const episodes: LoopEpisode[] = [];
  for (const [path, points] of byPath) {
    points.sort((a, b) => {
      const ao = order.get(a.key) ?? Number.MAX_SAFE_INTEGER;
      const bo = order.get(b.key) ?? Number.MAX_SAFE_INTEGER;
      return ao - bo || a.itemIdx - b.itemIdx;
    });

    let burst: LoopEditPoint[] = [];
    const flush = () => {
      if (burst.length >= 3) {
        const start = burst[0];
        const trigger = burst[2];
        const end = burst[burst.length - 1];
        const startIdx = order.get(start.key) ?? 0;
        const endIdx = order.get(end.key) ?? startIdx;
        episodes.push({
          id: `${path}:${start.key}:${end.key}:${episodes.length}`,
          path,
          editCount: burst.length,
          startKey: start.key,
          triggerKey: trigger.key,
          endKey: end.key,
          startIdx,
          endIdx,
          intervalKeys: keys.slice(startIdx, endIdx + 1),
          points: [...burst],
        });
      }
      burst = [];
    };

    for (const point of points) {
      const prev = burst.at(-1);
      if (prev) {
        const prevIdx = order.get(prev.key) ?? 0;
        const curIdx = order.get(point.key) ?? prevIdx;
        if (point.runId !== prev.runId || curIdx - prevIdx > gapSteps) flush();
      }
      burst.push(point);
    }
    flush();
  }

  episodes.sort((a, b) => a.startIdx - b.startIdx || a.endIdx - b.endIdx || a.path.localeCompare(b.path));
  return episodes;
}

export function normalizeLoopEpisodes(episodes: ApiLoopEpisode[] = []): LoopEpisode[] {
  return episodes.map((ep) => ({
    id: ep.id,
    path: ep.path,
    editCount: ep.editCount ?? ep.edit_count ?? 0,
    startKey: ep.startKey ?? ep.start_key ?? "",
    triggerKey: ep.triggerKey ?? ep.trigger_key ?? "",
    endKey: ep.endKey ?? ep.end_key ?? "",
    startIdx: ep.startIdx ?? ep.start_idx ?? 0,
    endIdx: ep.endIdx ?? ep.end_idx ?? 0,
    intervalKeys: ep.intervalKeys ?? ep.interval_keys ?? [],
    points: ep.points.map((p) => ({
      key: p.key,
      runId: p.runId ?? p.run_id ?? 0,
      stepId: p.stepId ?? p.step_id ?? 0,
      itemIdx: p.itemIdx ?? p.item_idx ?? 0,
    })),
  }));
}

export function loopStepRole(ep: LoopEpisode, key: string): LoopStepRole | null {
  if (ep.startKey === ep.endKey && key === ep.startKey) return "single";
  if (key === ep.startKey) return "start";
  if (key === ep.endKey) return "end";
  if (key === ep.triggerKey) return "trigger";
  return ep.intervalKeys.includes(key) ? "middle" : null;
}

export function loopMarkersForStep(key: string, episodes: LoopEpisode[]): LoopStepMarker[] {
  const out: LoopStepMarker[] = [];
  for (const ep of episodes) {
    const role = loopStepRole(ep, key);
    if (role) out.push({ episode: ep, role });
  }
  return out;
}

export function loopMarkerForStep(key: string, episodes: LoopEpisode[]): LoopStepMarker[] {
  return loopMarkersForStep(key, episodes);
}

export function loopLabelMarkersForStep(key: string, episodes: LoopEpisode[]): LoopStepMarker[] {
  return loopMarkersForStep(key, episodes).filter((m) => m.episode.startKey === key);
}

export function minimapLoopClass(key: string, episodes: LoopEpisode[]): string {
  const markers = loopMarkersForStep(key, episodes);
  if (markers.length === 0) return "";
  const role = markers[0].role;
  if (role === "start" || role === "single") return "flag-loop-start";
  if (role === "end") return "flag-loop-end";
  return "flag-loop";
}
