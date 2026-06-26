import assert from "node:assert/strict";
import {
  formatAnnotatorLabel,
  formatAnnotatorTarget,
  sortAnnotatorsForDisplay,
} from "../src/components/DatasetDetail";
import type { AnnotatorInfo } from "../src/api";

function annotator(id: string, target = "session"): AnnotatorInfo {
  return { id, type: "rule", target, path: `/tmp/${id}.yaml` };
}

assert.equal(formatAnnotatorLabel("change_acceptance"), "Change acceptance");
assert.equal(formatAnnotatorLabel("loop_detect"), "Loop detect");
assert.equal(formatAnnotatorTarget("user_turn"), "user turn");

assert.deepEqual(
  sortAnnotatorsForDisplay([
    annotator("loop_detect", "step"),
    annotator("change_acceptance"),
    annotator("resolution"),
    annotator("pushback", "user_turn"),
  ]).map((a) => a.id),
  ["resolution", "change_acceptance", "pushback", "loop_detect"],
);
