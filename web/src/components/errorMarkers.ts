import { parseAnnotationValue, type Annotation, type Item } from "../api";

export interface StepErrorMarker {
  key: string;
  runId: number;
  stepId: number;
  hasError: boolean;
  hasRecovery: boolean;
  recoveredFromKey: string | null;
  recoversKey: string | null;
  errorSummary: string | null;
  recoverySummary: string | null;
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
  const ensureMarker = (key: string): StepErrorMarker => {
    const existing = map.get(key);
    if (existing) return existing;
    const [runId, stepId] = key.split("-").map((n) => Number(n));
    const marker: StepErrorMarker = {
      key,
      runId,
      stepId,
      hasError: false,
      hasRecovery: false,
      recoveredFromKey: null,
      recoversKey: null,
      errorSummary: null,
      recoverySummary: null,
    };
    map.set(key, marker);
    return marker;
  };

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
    const marker = ensureMarker(key);
    marker.hasError = true;
    marker.errorSummary = typeof v.error_summary === "string" && v.error_summary ? v.error_summary : marker.errorSummary;

    if (recovered === true) {
      const recoveryKey = stepKeys[a.target_idx + 1];
      marker.recoversKey = recoveryKey ?? null;
      if (recoveryKey) {
        const recoveryMarker = ensureMarker(recoveryKey);
        recoveryMarker.hasRecovery = true;
        recoveryMarker.recoveredFromKey = key;
        recoveryMarker.recoverySummary = marker.errorSummary;
      }
    }
  }
  return map;
}

export function markerForItem(item: Item, markers: Map<string, StepErrorMarker>): StepErrorMarker | null {
  if (item.run_id == null || item.step_id == null) return null;
  return markers.get(stepMarkerKey(item.run_id, item.step_id)) ?? null;
}

export function minimapMarkerClass(marker: StepErrorMarker | null): string {
  if (!marker) return "";
  if (marker.hasError && marker.hasRecovery) return "flag-error-recovered";
  if (marker.hasError) return "flag-error";
  return marker.hasRecovery ? "flag-recovered" : "";
}

export function markerBadgeText(marker: StepErrorMarker | null): string {
  if (!marker) return "";
  if (marker.hasError && marker.hasRecovery) return "ERR+REC";
  if (marker.hasError) return "ERR";
  return marker.hasRecovery ? "REC" : "";
}
