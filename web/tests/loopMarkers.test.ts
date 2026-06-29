import assert from "node:assert/strict";
import type { CodeChange, Item } from "../src/api";
import {
  buildLoopEpisodes,
  loopMarkerForStep,
  loopStepRole,
  minimapLoopClass,
} from "../src/components/loopMarkers";

function item(runId: number, stepId: number): Item {
  return {
    type: "function_call",
    name: "edit",
    arguments: "{}",
    call_id: `${runId}-${stepId}`,
    step_id: stepId,
    run_id: runId,
    provenance: null,
  };
}

function change(path: string, stepId: number, itemIdx = stepId, runId = 0): CodeChange {
  return {
    item_idx: itemIdx,
    step_id: stepId,
    run_id: runId,
    tool: "edit",
    op: "edit",
    path,
    old: "before",
    new: "after",
    command: null,
  };
}

const items = Array.from({ length: 26 }, (_, i) => item(0, i));

const episodes = buildLoopEpisodes([
  change("a.ts", 2),
  change("a.ts", 3),
  change("a.ts", 5),
  change("a.ts", 6),
  change("a.ts", 18),
  change("a.ts", 19),
  change("a.ts", 21),
  change("b.ts", 4),
  { ...change("b.ts", 5), op: "run", command: "npm test", path: null },
], items);

assert.equal(episodes.length, 2);
assert.deepEqual(episodes.map((e) => ({
  path: e.path,
  startKey: e.startKey,
  triggerKey: e.triggerKey,
  endKey: e.endKey,
  editCount: e.editCount,
})), [
  { path: "a.ts", startKey: "0-2", triggerKey: "0-5", endKey: "0-6", editCount: 4 },
  { path: "a.ts", startKey: "0-18", triggerKey: "0-21", endKey: "0-21", editCount: 3 },
]);

assert.equal(loopStepRole(episodes[0], "0-2"), "start");
assert.equal(loopStepRole(episodes[0], "0-5"), "trigger");
assert.equal(loopStepRole(episodes[0], "0-6"), "end");
assert.equal(loopStepRole(episodes[0], "0-4"), "middle");
assert.equal(loopStepRole(episodes[0], "0-7"), null);
assert.equal(loopStepRole(episodes[1], "0-21"), "end");

const triggerMarker = loopMarkerForStep("0-5", episodes);
assert.equal(triggerMarker.length, 1);
assert.equal(triggerMarker[0].role, "trigger");
assert.equal(triggerMarker[0].episode.editCount, 4);

assert.equal(minimapLoopClass("0-2", episodes), "flag-loop-start");
assert.equal(minimapLoopClass("0-4", episodes), "flag-loop");
assert.equal(minimapLoopClass("0-6", episodes), "flag-loop-end");
assert.equal(minimapLoopClass("0-7", episodes), "");

const multiRunItems = [
  item(0, 0), item(0, 1), item(0, 2), item(0, 3),
  item(1, 0), item(1, 1), item(1, 2),
  item(2, 0), item(2, 1), item(2, 2), item(2, 3), item(2, 4),
  item(3, 0), item(3, 1), item(3, 2), item(3, 3), item(3, 4), item(3, 5), item(3, 6),
  item(4, 0), item(4, 1), item(4, 2), item(4, 3), item(4, 4), item(4, 5),
];
const researchEdits = [
  change("research-client.tsx", 3, 7, 0),
  change("research-client.tsx", 2, 15, 1),
  change("research-client.tsx", 3, 25, 2),
  change("research-client.tsx", 4, 27, 2),
  change("research-client.tsx", 3, 37, 3),
  change("research-client.tsx", 4, 39, 3),
  change("research-client.tsx", 6, 43, 3),
  change("research-client.tsx", 2, 53, 4),
  change("research-client.tsx", 5, 59, 4),
];
const researchEpisodes = buildLoopEpisodes(researchEdits, multiRunItems);

assert.deepEqual(researchEpisodes.map((e) => ({
  startKey: e.startKey,
  triggerKey: e.triggerKey,
  endKey: e.endKey,
  editCount: e.editCount,
})), [
  { startKey: "3-3", triggerKey: "3-6", endKey: "3-6", editCount: 3 },
]);
assert.equal(loopMarkerForStep("2-3", researchEpisodes).length, 0);
assert.equal(loopMarkerForStep("3-6", researchEpisodes)[0]?.episode.path, "research-client.tsx");
