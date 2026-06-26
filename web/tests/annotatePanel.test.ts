import assert from "node:assert/strict";
import {
  formatAnnotatorLabel,
  formatAnnotatorTarget,
  sortAnnotatorsForDisplay,
  visibleStatsTags,
  COLLAPSED_TAG_LIMIT,
} from "../src/components/DatasetDetail";
import { buildCreateJobBody, type AnnotatorInfo } from "../src/api";

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

const tags = Array.from({ length: 12 }, (_, i) => `tag-${i}`);
assert.equal(COLLAPSED_TAG_LIMIT, 10);
assert.deepEqual(visibleStatsTags(tags, false), tags.slice(0, 10));
assert.deepEqual(visibleStatsTags(tags, true), tags);

assert.deepEqual(buildCreateJobBody("/tmp/pushback.yaml", "ds1"), {
  annotator: "/tmp/pushback.yaml",
  dataset_id: "ds1",
});
assert.deepEqual(buildCreateJobBody("/tmp/pushback.yaml", "ds1", true), {
  annotator: "/tmp/pushback.yaml",
  dataset_id: "ds1",
  force: true,
});
