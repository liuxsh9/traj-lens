import assert from "node:assert/strict";
import {
  formatListResolution,
  getListAcceptClass,
  getListColumnIds,
  getListScoreClass,
  getListSortParams,
  EXPORT_MODE_HINT,
  shouldResetListForExternalFilters,
  shouldShowExportSelection,
} from "../src/components/ListView";

assert.deepEqual(getListSortParams([]), { sortBy: "score", sortDir: "desc" });

assert.deepEqual(
  Object.fromEntries(getListColumnIds().map((id) => [id, getListSortParams([{ id, desc: true }]).sortBy])),
  {
    title: "title",
    turns: "turns",
    steps: "steps",
    tools: "tools",
    resolution: "resolution",
    acceptance: "acceptance",
    pb: "pushback_count",
    errors: "error_steps",
    loop: "loop_count",
    recovery: "recovery_count",
    sec: "security_findings",
    score: "score",
    created_at: "created_at",
  },
);

assert.deepEqual(getListColumnIds(), [
  "title",
  "turns",
  "steps",
  "tools",
  "resolution",
  "acceptance",
  "pb",
  "errors",
  "loop",
  "recovery",
  "sec",
  "score",
  "created_at",
]);

assert.equal(getListScoreClass(90), "res-ok");
assert.equal(getListScoreClass(45), "res-part");
assert.equal(getListScoreClass(30), "res-fail");

assert.equal(formatListResolution("resolved"), "resolved");
assert.equal(formatListResolution("partially_resolved"), "partially");
assert.equal(formatListResolution("unresolved"), "unresolved");

assert.equal(getListAcceptClass("high"), "res-ok");
assert.equal(getListAcceptClass("medium"), "res-part");
assert.equal(getListAcceptClass("low"), "res-fail");

assert.equal(
  EXPORT_MODE_HINT,
  "基于当前筛选后的样本集创建，进入后可勾选或取消再导出。",
);

assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 2,
  exportMode: false,
}), false);
assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 2,
  exportMode: true,
}), true);
assert.equal(shouldShowExportSelection({
  datasetId: undefined,
  total: 2,
  exportMode: true,
}), false);
assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 0,
  exportMode: true,
}), false);

assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: true,
  previousKey: null,
  nextKey: "[]",
}), false);
assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: true,
  previousKey: "[]",
  nextKey: "[tags]",
}), true);
assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: false,
  previousKey: "[]",
  nextKey: "[tags]",
}), false);
