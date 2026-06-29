import { parseAnnotationValue, type Annotation, type Item } from "../api";

export type ErrorMarkerKind = "error" | "recovered";

export interface StepErrorMarker {
  key: string;
  runId: number;
  stepId: number;
  kind: ErrorMarkerKind;
  hasError: boolean;
  recovered: boolean | null;
  summary: string | null;
}

export function stepMarkerKey(runId: number, stepId: number): string {
  return `${runId}-${stepId}`;
}

function enumerateStepKeys(items: Item[]): string[] {
  const keys: string[] = [];
  let current: string | null = null;
  for (const it of items) {
    if (it.run_id == null || it.step_id == null) {
      current = null;
      continue;
    }
    const key = stepMarkerKey(it.run_id, it.step_id);
    if (key !== current) {
      keys.push(key);
      current = key;
    }
  }
  return keys;
}

export function buildStepErrorMarkers(annotations: Annotation[], items: Item[] = []): Map<string, StepErrorMarker> {
  const map = new Map<string, StepErrorMarker>();
  const stepKeys = enumerateStepKeys(items);
  for (const a of annotations) {
    if (a.annotator_id !== "error_recovery" || a.target_type !== "step") continue;
    if (a.target_idx == null) continue;
    const v = parseAnnotationValue(a);
    if (!v.has_error) continue;

    const targetKey = stepKeys[a.target_idx];
    const [runId, stepId] = targetKey
      ? targetKey.split("-").map((n) => Number(n))
      : [typeof v.run_id === "number" ? v.run_id : 0, a.target_idx];
    const recovered = v.recovered === true ? true : v.recovered === false ? false : null;
    const key = stepMarkerKey(runId, stepId);
    map.set(key, {
      key,
      runId,
      stepId,
      kind: recovered === true ? "recovered" : "error",
      hasError: true,
      recovered,
      summary: typeof v.error_summary === "string" && v.error_summary ? v.error_summary : null,
    });
  }
  return map;
}

export function markerForItem(item: Item, markers: Map<string, StepErrorMarker>): StepErrorMarker | null {
  if (item.run_id == null || item.step_id == null) return null;
  return markers.get(stepMarkerKey(item.run_id, item.step_id)) ?? null;
}

export function minimapMarkerClass(marker: StepErrorMarker | null): string {
  if (!marker) return "";
  return marker.kind === "recovered" ? "flag-recovered" : "flag-error";
}

export function markerBadgeText(marker: StepErrorMarker | null): string {
  if (!marker) return "";
  return marker.recovered === true ? "ERR+REC" : "ERR";
}
