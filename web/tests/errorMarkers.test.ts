import assert from "node:assert/strict";
import type { Annotation, Item } from "../src/api";
import {
  buildStepErrorMarkers,
  markerBadgeText,
  markerForItem,
  minimapMarkerClass,
} from "../src/components/errorMarkers";

function ann(targetIdx: number, value: Record<string, unknown>): Annotation {
  return {
    target_hash: `target-${targetIdx}`,
    annotator_id: "error_recovery",
    annotator_version: "v1",
    value: JSON.stringify(value),
    produced_at: "2026-06-29T00:00:00Z",
    target_type: "step",
    target_idx: targetIdx,
  };
}

function item(runId: number | null, stepId: number | null): Item {
  return {
    type: "function_call_output",
    output: "",
    step_id: stepId,
    run_id: runId,
    provenance: null,
  };
}

const markers = buildStepErrorMarkers([
  ann(0, { has_error: true, recovered: false, error_summary: "FAILED test_a" }),
  ann(1, { has_error: true, recovered: true, error_summary: "exit code 1" }),
  ann(2, { has_error: false, recovered: null, error_summary: null }),
], [
  item(0, 0),
  item(0, 1),
  item(0, 2),
  item(0, 3),
]);

assert.equal(markers.size, 3);
assert.deepEqual(markers.get("0-0"), {
  key: "0-0",
  runId: 0,
  stepId: 0,
  hasRecovery: false,
  hasError: true,
  recoveredFromKey: null,
  recoversKey: null,
  errorSummary: "FAILED test_a",
  recoverySummary: null,
});
assert.equal(markers.get("0-1")?.hasError, true);
assert.equal(markers.get("0-1")?.recoversKey, "0-2");
assert.equal(markers.get("0-1")?.errorSummary, "exit code 1");
assert.equal(markers.get("0-2")?.hasRecovery, true);
assert.equal(markers.get("0-2")?.recoveredFromKey, "0-1");
assert.equal(markers.get("0-2")?.recoverySummary, "exit code 1");

assert.equal(markerForItem(item(0, 1), markers)?.hasError, true);
assert.equal(markerForItem(item(null, null), markers), null);
assert.equal(markerForItem(item(2, 1), markers), null);

assert.equal(minimapMarkerClass(null), "");
assert.equal(minimapMarkerClass(markers.get("0-0") ?? null), "flag-error");
assert.equal(minimapMarkerClass(markers.get("0-1") ?? null), "flag-error");
assert.equal(minimapMarkerClass(markers.get("0-2") ?? null), "flag-recovered");
assert.equal(markerBadgeText(markers.get("0-0") ?? null), "ERR");
assert.equal(markerBadgeText(markers.get("0-1") ?? null), "ERR");
assert.equal(markerBadgeText(markers.get("0-2") ?? null), "REC");

const multiRunMarkers = buildStepErrorMarkers([
  ann(0, { has_error: true, recovered: false }),
  ann(1, { has_error: true, recovered: true }),
], [
  item(3, 0),
  item(3, 0),
  item(null, null),
  item(4, 0),
]);

assert.equal(multiRunMarkers.has("3-0"), true);
assert.equal(multiRunMarkers.has("4-0"), true);
assert.equal(multiRunMarkers.get("4-0")?.hasError, true);

const chainedMarkers = buildStepErrorMarkers([
  ann(1, { has_error: true, recovered: true, error_summary: "first failure" }),
  ann(2, { has_error: true, recovered: true, error_summary: "second failure" }),
], [
  item(0, 0),
  item(0, 1),
  item(0, 2),
  item(0, 3),
]);

assert.equal(markerBadgeText(chainedMarkers.get("0-2") ?? null), "ERR+REC");
assert.equal(minimapMarkerClass(chainedMarkers.get("0-2") ?? null), "flag-error-recovered");
assert.equal(chainedMarkers.get("0-2")?.errorSummary, "second failure");
assert.equal(chainedMarkers.get("0-2")?.recoverySummary, "first failure");
